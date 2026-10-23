#!/usr/bin/env bash
# Reporter benchmark: the reports of finished runs written again by the reporter of GETH_RUNNER (nextflow, or
# harness for Rannoch's), on copies of the runs: <tag>_<source run>, with the results hard-linked (no space used,
# the source run is left as it was).
# Usage: bench_report.sh <tag> <source run> [<source run> ...]
# Scores: numbers traced by the report check, the five sections asked for, minutes and model usage.
# Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; shift
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"

{
trap 'echo "Interrupted: stopping ${name:-the current report} ..." >&2; [ -n "${name:-}" ] && "$geth" stop "$name" >&2; exit 130' INT TERM
for src in "$@"; do
    s=$GETH_RUNS_DIR/$src; name=${tag}_$src; d=$GETH_RUNS_DIR/$name
    [ -f "$s/outcome.txt" ] && [ -d "$s/results" ] || { echo "{\"run\": \"$name\", \"error\": \"$src has no finished run\"}"; continue; }
    if [ ! -e "$d" ]; then
        mkdir -p "$d"
        cp -a "$s"/{APPROVED,question.txt,outcome.txt} "$s"/plan_* "$d"/
        [ -f "$s/data_dir.txt" ] && cp -a "$s/data_dir.txt" "$d"/
        for a in "$s"/attempt_*; do [ -d "$a" ] && cp -a "$a" "$d"/; done
        cp -al "$s/results" "$d/results"
    fi
    rm -f "$d/report.md" "$d/report_check.txt" "$d/harness_trace_report.jsonl"
    t0=$(date +%s)
    "$geth" report "$name" < /dev/null > /dev/null 2>&1 && status=ok || status=failed
    t1=$(date +%s)
    python3 - "$d" "$src" "$status" "$(( t1 - t0 ))" <<'EOF' || echo "{\"run\": \"$name\", \"error\": \"scoring failed\"}"
import json, os, re, sys
d, src, status, seconds = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
read = lambda f: open(os.path.join(d, f), errors="replace").read() if os.path.isfile(os.path.join(d, f)) else ""
check, report = read("report_check.txt").strip(), read("report.md")
m = re.search(r"(\d+)/(\d+) numbers traced", check)
sections = {k: bool(re.search(rf"^#+\s*(\d+\.\s*)?{k}", report, re.M | re.I))
            for k in ("Summary", "Samples", "Quality control", "Results", "Caveats")}
usage = [l for l in read("geth_report.log").splitlines() if l.startswith("Model usage:")]
trace = [json.loads(l) for l in read("harness_trace_report.jsonl").splitlines() if l.strip()]
print(json.dumps({
    "run": os.path.basename(d), "source": src, "runner": os.environ.get("GETH_RUNNER", "nextflow"), "status": status,
    "succeeded_run": "succeeded: true" in read("outcome.txt"),
    "report_numbers": f"{m.group(1)}/{m.group(2)}" if m else "n/a",
    "report_untraced": check.split("not traced: ")[1].split(";")[0] if "not traced:" in check else "",
    "sections": sum(sections.values()), "missing_sections": [k for k, v in sections.items() if not v],
    "report_words": len(report.split()), "minutes": round(seconds / 60, 1),
    "submissions": sum(1 for t in trace if t.get("event") == "tool" and t.get("name") == "SUBMIT_REPORT"),
    **({"model_usage": json.loads(usage[-1].split(":", 1)[1])} if usage else {}),
}))
EOF
done
} | tee -a "$out"
