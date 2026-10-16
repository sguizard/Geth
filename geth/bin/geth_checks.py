#!/usr/bin/env python3
"""Deterministic checks that keep Geth's agents honest.

  geth_checks.py check-plan <pipeline> <samplesheet.csv> <params.json> [<normalised_params_out>]
      Validate a plan against the pinned pipeline's samplesheet and parameter schemas.
  geth_checks.py approve <run_dir> <approver>
      Record approval of the plan files in <run_dir> (hashes them into APPROVED).
  geth_checks.py gate <run_dir> <pipeline> <samplesheet.csv> <params.json>
      Refuse an operator attempt that departs from the approved plan without a reason
      given by the previous error.
  geth_checks.py record <run_dir> <ok|check|nextflow> <samplesheet.csv> <params.json> [<error.txt>]
      Store an accepted attempt as the new baseline, with the error that may justify the next change.

Exit status 0 = OK, 1 = problems (described on stdout).
"""
import csv
import difflib
import getpass
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HERE, "..", "schemas")
PINNED = {"rnaseq": "3.27.0", "scrnaseq": "4.2.0"}
OWNED = ("input", "outdir", "custom_config_base", "custom_config_version")  # set by Geth, never by agents
IDENTITY = ("sample", "fastq_1", "fastq_2")                                 # define the experimental design
PLAN_FILES = ("plan_pipeline.txt", "plan_samplesheet.csv", "plan_params.json")


# ---------------------------------------------------------------- parsing

def pipeline_name(name):
    return name.strip().replace("nf-core/", "")


def load_schema(pipeline, kind):
    return json.load(open(os.path.join(SCHEMAS, f"{pipeline}-{PINNED[pipeline]}.{kind}.json")))


def param_names(pipeline):
    schema = load_schema(pipeline, "params")
    groups = (schema.get("$defs") or schema.get("definitions") or {}).values()
    return {k for g in groups for k in g.get("properties", {})}


def parse_params(text):
    params = json.loads(text) if text.strip() else {}
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")
    return {k: v for k, v in params.items() if k not in OWNED}


def parse_sheet(text):
    reader = csv.DictReader(io.StringIO(text.strip()))
    header = [h.strip() for h in (reader.fieldnames or [])]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return header, rows


def identity(rows):
    return sorted(tuple(r.get(c, "") for c in IDENTITY) for r in rows)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ---------------------------------------------------------------- plan validation

def check_plan(pipeline, sheet_text, params_text):
    problems = []
    if pipeline not in PINNED:
        return [f"pipeline must be one of {sorted(PINNED)} (got '{pipeline}')"], {}
    try:
        params = parse_params(params_text)
    except ValueError as e:
        problems.append(f"params_json is not a valid JSON object: {e}")
        params = {}
    known = param_names(pipeline)
    for key in sorted(set(params) - known):
        close = difflib.get_close_matches(key, known, n=3)
        problems.append(f"param '{key}' does not exist in nf-core/{pipeline} {PINNED[pipeline]}"
                        + (f" (closest: {', '.join(close)})" if close else ""))
    if "genome" in params and ("fasta" in params or "gtf" in params):
        problems.append("set either 'genome' or 'fasta'/'gtf', not both")
    for key in ("fasta", "gtf", "gff", "transcript_fasta"):
        if isinstance(params.get(key), str) and not os.path.isfile(params[key]):
            problems.append(f"param '{key}' points to a file that does not exist: {params[key]}")

    schema = load_schema(pipeline, "input")["items"]
    props, required = schema["properties"], schema.get("required", [])
    header, rows = parse_sheet(sheet_text)
    for col in required:
        if col not in header:
            problems.append(f"samplesheet: required column '{col}' is missing (header is: {','.join(header)})")
    for col in header:
        if col not in props:
            problems.append(f"samplesheet: column '{col}' is not used by nf-core/{pipeline}")
    if not rows:
        problems.append("samplesheet has no rows")
    seen = {}
    for i, row in enumerate(rows, start=2):
        for col, spec in props.items():
            value = row.get(col, "")
            if not value:
                if col in required and not (col == "fastq_2" and pipeline == "rnaseq"):
                    problems.append(f"samplesheet line {i}: '{col}' is empty")
                continue
            if "enum" in spec and value not in spec["enum"]:
                problems.append(f"samplesheet line {i}: '{col}' must be one of {spec['enum']} (got '{value}')")
            if "pattern" in spec and not re.search(spec["pattern"], value):
                problems.append(f"samplesheet line {i}: '{col}' value '{value}' is not valid ({spec.get('errorMessage', 'pattern ' + spec['pattern'])})")
            if spec.get("type") == "integer" and not value.isdigit():
                problems.append(f"samplesheet line {i}: '{col}' must be an integer (got '{value}')")
            if spec.get("format") == "file-path":
                if not value.startswith("/"):
                    problems.append(f"samplesheet line {i}: '{col}' must be an absolute path (got '{value}')")
                elif not os.path.isfile(value):
                    problems.append(f"samplesheet line {i}: '{col}' file does not exist: {value}")
        fq1 = row.get("fastq_1", "")
        if fq1 and fq1 in seen:
            problems.append(f"samplesheet line {i}: fastq_1 already used on line {seen[fq1]}")
        seen[fq1] = i
    if pipeline == "rnaseq":
        layout = {}
        for row in rows:
            layout.setdefault(row.get("sample"), set()).add(bool(row.get("fastq_2")))
        for sample, kinds in layout.items():
            if len(kinds) > 1:
                problems.append(f"samplesheet: sample '{sample}' mixes single-end and paired-end rows")
    return problems, params


# ---------------------------------------------------------------- approval and the plan-diff gate

def approve(run_dir, approver):
    missing = [f for f in PLAN_FILES if not os.path.isfile(os.path.join(run_dir, f))]
    if missing:
        print(f"Cannot approve: missing plan files {missing}")
        return 1
    record = {"approved_by": approver, "approved_at": time.strftime("%F %T"),
              "sha256": {f: sha256(os.path.join(run_dir, f)) for f in PLAN_FILES}}
    json.dump(record, open(os.path.join(run_dir, "APPROVED"), "w"), indent=2)
    state = os.path.join(run_dir, "gate_state.json")
    if os.path.exists(state):
        os.remove(state)  # a new approval restarts the attempt history
    print(f"Plan approved by {approver}.")
    return 0


def approved_plan(run_dir):
    """Return (pipeline, sheet_text, params) of the approved plan, or raise ValueError."""
    path = os.path.join(run_dir, "APPROVED")
    if not os.path.isfile(path):
        raise ValueError("the plan has not been approved by a person (run `geth approve`)")
    hashes = json.load(open(path))["sha256"]
    for f in PLAN_FILES:
        if sha256(os.path.join(run_dir, f)) != hashes.get(f):
            raise ValueError(f"{f} changed after approval; it must be approved again")
    read = lambda f: open(os.path.join(run_dir, f)).read()
    return pipeline_name(read("plan_pipeline.txt")), read("plan_samplesheet.csv"), parse_params(read("plan_params.json"))


def load_state(run_dir, plan_sheet, plan_params):
    path = os.path.join(run_dir, "gate_state.json")
    if os.path.isfile(path):
        return json.load(open(path))
    return {"sheet": plan_sheet, "params": plan_params, "error": None}


def mentioned(name, text):
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text or "") is not None


def gate(run_dir, pipeline, sheet_text, params_text):
    try:
        plan_pipeline, plan_sheet, plan_params = approved_plan(run_dir)
        params = parse_params(params_text)
    except ValueError as e:
        return [str(e)]
    problems = []
    if pipeline != plan_pipeline:
        problems.append(f"pipeline must stay '{plan_pipeline}' as approved (got '{pipeline}')")

    # 1. Experimental design: sample names and files must match the approved plan exactly.
    _, plan_rows = parse_sheet(plan_sheet)
    _, rows = parse_sheet(sheet_text)
    if identity(rows) != identity(plan_rows):
        before = {r.get("fastq_1"): r for r in plan_rows}
        after = {r.get("fastq_1"): r for r in rows}
        for fq in sorted(set(before) | set(after)):
            b, a = before.get(fq), after.get(fq)
            name = os.path.basename(fq or "?")
            if b is None:
                problems.append(f"design change: file {name} was added")
            elif a is None:
                problems.append(f"design change: file {name} was removed")
            else:
                for col in IDENTITY:
                    if b.get(col, "") != a.get(col, ""):
                        problems.append(f"design change: {col} of {name} changed from '{b.get(col, '')}' to '{a.get(col, '')}'")

    state = load_state(run_dir, plan_sheet, plan_params)
    error = state.get("error") or {}
    text = error.get("text", "")

    # 2. Other samplesheet columns may change only if the previous error names them.
    _, base_rows = parse_sheet(state["sheet"])
    base = {r.get("fastq_1"): r for r in base_rows}
    for row in rows:
        old = base.get(row.get("fastq_1"), {})
        for col in sorted((set(row) | set(old)) - set(IDENTITY)):
            if row.get(col, "") != old.get(col, "") and not mentioned(col, text):
                problems.append(f"samplesheet column '{col}' changed for {os.path.basename(row.get('fastq_1', '?'))} "
                                f"('{old.get(col, '')}' -> '{row.get(col, '')}') but the previous error does not mention it")

    # 3. Params may change only where the previous error points.
    old = state["params"]
    added = sorted(set(params) - set(old))
    removed = sorted(set(old) - set(params))
    changed = sorted(k for k in set(params) & set(old) if params[k] != old[k])
    if error.get("kind") == "check":
        unknown = set(error.get("unknown", []))
        renames = error.get("suggestions", {})
        for k in removed:
            if k not in unknown and not mentioned(k, text):
                problems.append(f"param '{k}' was removed but the previous error does not mention it")
        for k in added:
            sources = [u for u in removed if k in renames.get(u, []) and old.get(u) == params[k]]
            if not sources:
                problems.append(f"param '{k}' was added; after a plan-check error only a misspelt param may be "
                                f"renamed to a suggested name, keeping its value")
        for k in changed:
            if not mentioned(k, text):
                problems.append(f"param '{k}' changed ({old[k]!r} -> {params[k]!r}) but the previous error does not mention it")
    else:
        for k in added + removed + changed:
            if not mentioned(k, text):
                what = "added" if k in added else "removed" if k in removed else f"changed ({old[k]!r} -> {params[k]!r})"
                problems.append(f"param '{k}' was {what} but the previous error does not mention it"
                                + ("" if text else " (the approved plan must be launched unchanged first)"))
    return problems


def record(run_dir, kind, sheet_text, params_text, error_text=""):
    _, plan_sheet, plan_params = approved_plan(run_dir)
    state = load_state(run_dir, plan_sheet, plan_params)
    state["sheet"], state["params"] = sheet_text, parse_params(params_text)
    if kind == "ok":
        state["error"] = None
    else:
        err = {"kind": kind, "text": error_text}
        if kind == "check":
            err["unknown"] = re.findall(r"param '([^']+)' does not exist", error_text)
            err["suggestions"] = {m.group(1): [s.strip() for s in m.group(2).split(",")]
                                  for m in re.finditer(r"param '([^']+)' does not exist[^\n]*\(closest: ([^)]*)\)", error_text)}
        state["error"] = err
    json.dump(state, open(os.path.join(run_dir, "gate_state.json"), "w"), indent=2)


# ---------------------------------------------------------------- CLI

def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check-plan":
        pipeline = pipeline_name(argv[2])
        problems, params = check_plan(pipeline, open(argv[3]).read(), open(argv[4]).read())
        if problems:
            print(f"PLAN CHECK: {len(problems)} problem(s)")
            print("\n".join(f"- {p}" for p in problems))
            return 1
        if len(argv) > 5:
            json.dump(params, open(argv[5], "w"), indent=2)
        print("PLAN CHECK: OK")
        return 0
    if cmd == "approve":
        return approve(argv[2], argv[3] if len(argv) > 3 else getpass.getuser())
    if cmd == "gate":
        problems = gate(argv[2], pipeline_name(argv[3]), open(argv[4]).read(), open(argv[5]).read())
        if problems:
            print("\n".join(f"- {p}" for p in problems))
            return 1
        return 0
    if cmd == "record":
        error_text = open(argv[6]).read() if len(argv) > 6 else ""
        record(argv[2], argv[3], open(argv[4]).read(), open(argv[5]).read(), error_text)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
