#!/usr/bin/env python3
"""Spike 1: probe what the free ELM models can do for an agent runtime.

Checks, per model: plain chat (latency, tokens), tool calling (auto + forced),
a full tool round-trip, JSON-schema structured output, and long-context recall.
Only the models in GETH_ALLOWED_MODELS may be called; anything else aborts.

Usage: source Geth/env.sh; python3 elm_probe.py [--models M ...] [--quick] [--out results.json]
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("GETH_ELM_BASE_URL", "https://elm.edina.ac.uk/api/v1")
ALLOWED = set(os.environ.get(
    "GETH_ALLOWED_MODELS",
    "Qwen/Qwen3.5-397B-A17B-FP8 mistralai/Mistral-Small-4-119B-2603").split())

FASTQC_TOOL = {
    "type": "function",
    "function": {
        "name": "run_fastqc",
        "description": "Run FastQC quality control on one FASTQ file and return a summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "fastq": {"type": "string", "description": "Path to the FASTQ file"},
                "threads": {"type": "integer", "description": "CPU threads to use"},
            },
            "required": ["fastq"],
        },
    },
}

SAMPLESHEET_SCHEMA = {
    "name": "rnaseq_samplesheet",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "samples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sample": {"type": "string"},
                        "fastq_1": {"type": "string"},
                        "fastq_2": {"type": "string"},
                        "strandedness": {"type": "string", "enum": ["auto", "forward", "reverse", "unstranded"]},
                    },
                    "required": ["sample", "fastq_1", "fastq_2", "strandedness"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["samples"],
        "additionalProperties": False,
    },
}


def chat(model, messages, timeout=300, **extra):
    """POST /chat/completions; return (json, seconds, rate-limit headers)."""
    if model not in ALLOWED:
        sys.exit(f"REFUSED: model '{model}' is not in the free-model allowlist {sorted(ALLOWED)}")
    body = {"model": model, "messages": messages, **extra}
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["ELM_API_KEY"],
                 "Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            headers = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
            return json.load(r), time.time() - t0, headers
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None


def msg(resp):
    return resp["choices"][0]["message"]


def test_basic(model):
    resp, dt, headers = chat(model, [{"role": "user", "content": "In one sentence: what does FastQC do?"}],
                             max_tokens=2000)
    m = msg(resp)
    ok = bool((m.get("content") or "").strip())
    return ok, {"latency_s": round(dt, 2), "usage": resp.get("usage"), "ratelimit_headers": headers,
                "has_reasoning": bool(m.get("reasoning_content") or m.get("reasoning")),
                "answer": (m.get("content") or "")[:200]}


def test_tool_auto(model):
    resp, dt, _ = chat(model, [
        {"role": "system", "content": "You are a bioinformatics assistant. Use tools when they help."},
        {"role": "user", "content": "Please run quality control on /data/S1_R1.fastq.gz using 2 threads."},
    ], tools=[FASTQC_TOOL], tool_choice="auto", max_tokens=2000)
    calls = msg(resp).get("tool_calls") or []
    args = json.loads(calls[0]["function"]["arguments"]) if calls else {}
    ok = bool(calls) and calls[0]["function"]["name"] == "run_fastqc" and args.get("fastq") == "/data/S1_R1.fastq.gz"
    return ok, {"latency_s": round(dt, 2), "tool_calls": calls[:2], "content": (msg(resp).get("content") or "")[:200]}


def test_tool_forced(model):
    resp, dt, _ = chat(model, [
        {"role": "user", "content": "Check the read quality of /data/S2_R1.fastq.gz."},
    ], tools=[FASTQC_TOOL], tool_choice={"type": "function", "function": {"name": "run_fastqc"}}, max_tokens=2000)
    calls = msg(resp).get("tool_calls") or []
    ok = bool(calls) and calls[0]["function"]["name"] == "run_fastqc"
    return ok, {"latency_s": round(dt, 2), "tool_calls": calls[:2]}


def test_tool_roundtrip(model):
    messages = [
        {"role": "system", "content": "You are a bioinformatics assistant. Use tools, then answer the user."},
        {"role": "user", "content": "Run FastQC on /data/S3_R1.fastq.gz and tell me whether adapters need trimming."},
    ]
    resp, dt1, _ = chat(model, messages, tools=[FASTQC_TOOL], tool_choice="auto", max_tokens=2000)
    m = msg(resp)
    calls = m.get("tool_calls") or []
    if not calls:
        return False, {"error": "no tool call in first turn", "content": (m.get("content") or "")[:200]}
    messages.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
    messages.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps({
        "total_sequences": 1250000, "per_base_quality": "PASS",
        "adapter_content": "FAIL (Illumina Universal Adapter, 18% of reads at position >60)",
        "overrepresented_sequences": "WARN"})})
    resp2, dt2, _ = chat(model, messages, tools=[FASTQC_TOOL], max_tokens=2000)
    answer = (msg(resp2).get("content") or "")
    ok = "adapter" in answer.lower() and any(w in answer.lower() for w in ("trim", "yes"))
    return ok, {"latency_s": round(dt1 + dt2, 2), "answer": answer[:300]}


def test_structured(model):
    prompt = ("Build an nf-core/rnaseq samplesheet for these files; strandedness unknown.\n"
              "/seq/ctrl_rep1_R1.fq.gz /seq/ctrl_rep1_R2.fq.gz /seq/ctrl_rep2_R1.fq.gz /seq/ctrl_rep2_R2.fq.gz\n"
              "/seq/kd_rep1_R1.fq.gz /seq/kd_rep1_R2.fq.gz /seq/kd_rep2_R1.fq.gz /seq/kd_rep2_R2.fq.gz")
    resp, dt, _ = chat(model, [{"role": "user", "content": prompt}],
                       response_format={"type": "json_schema", "json_schema": SAMPLESHEET_SCHEMA}, max_tokens=3000)
    content = msg(resp).get("content") or ""
    try:
        data = json.loads(content)
        samples = data["samples"]
        ok = (len(samples) == 4
              and all(s["fastq_1"].endswith("_R1.fq.gz") and s["fastq_2"].endswith("_R2.fq.gz") for s in samples)
              and all(s["strandedness"] == "auto" for s in samples))
        return ok, {"latency_s": round(dt, 2), "samples": samples}
    except (ValueError, KeyError, TypeError) as e:
        return False, {"latency_s": round(dt, 2), "error": repr(e), "content": content[:300]}


def test_context(model, approx_tokens):
    """Needle-in-a-haystack recall from a synthetic log of ~approx_tokens tokens."""
    line = "INFO  [task 0000] process RNASEQ:ALIGN_STAR (sample_{i}) completed, exit 0, 812 MB peak RSS\n"
    n = approx_tokens // 30
    lines = [line.replace("0000", f"{i:05d}").replace("{i}", str(i)) for i in range(n)]
    lines[n * 2 // 3] = "ERROR [task 31337] process RNASEQ:SALMON_QUANT (sample_kd7) failed, exit 137 (out of memory)\n"
    prompt = "".join(lines) + "\nWhich sample failed, in which process, and with which exit code? Answer in one line."
    resp, dt, _ = chat(model, [{"role": "user", "content": prompt}], max_tokens=2000, timeout=600)
    answer = msg(resp).get("content") or ""
    ok = "kd7" in answer and "137" in answer
    return ok, {"latency_s": round(dt, 2), "prompt_tokens": (resp.get("usage") or {}).get("prompt_tokens"),
                "answer": answer[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=sorted(ALLOWED))
    ap.add_argument("--quick", action="store_true", help="only the basic chat test")
    ap.add_argument("--context", nargs="*", type=int, default=[8000, 32000, 100000])
    ap.add_argument("--out")
    args = ap.parse_args()
    for m in args.models:
        if m not in ALLOWED:
            sys.exit(f"REFUSED: model '{m}' is not in the free-model allowlist {sorted(ALLOWED)}")

    tests = [("basic_chat", test_basic)]
    if not args.quick:
        tests += [("tool_auto", test_tool_auto), ("tool_forced", test_tool_forced),
                  ("tool_roundtrip", test_tool_roundtrip), ("structured_json", test_structured)]
        tests += [(f"context_{n // 1000}k", lambda m, n=n: test_context(m, n)) for n in args.context]

    results = {"host": socket.gethostname(), "base_url": BASE_URL, "time": time.strftime("%F %T"), "models": {}}
    for model in args.models:
        results["models"][model] = {}
        for name, fn in tests:
            try:
                ok, info = fn(model)
            except Exception as e:  # report and keep probing
                ok, info = False, {"error": str(e)[:500]}
            results["models"][model][name] = {"pass": ok, **info}
            lat = info.get("latency_s", "-")
            print(f"{'PASS' if ok else 'FAIL'}  {model:40s} {name:16s} {lat}s"
                  + ("" if ok else f"  {json.dumps(info)[:300]}"), flush=True)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        print("results ->", args.out)


if __name__ == "__main__":
    main()
