#!/usr/bin/env bash
# Lab benchmark, phase 11.5 (EXPERIMENTAL): three designs and a judge. For each set of designs of the same
# request, a judge agent writes the best design; the judged design and its inputs are scored by eval_design.py.
# Usage: bench_judge.sh <tag> <kang2018|pbmc1k> <design>,<design>,<design> [...]    Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"
here=$(cd "$(dirname "$0")/../.." && pwd)
tag=$1 dataset=$2; shift 2
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
n=0
for set in "$@"; do
    n=$((n + 1)); name=${tag}_${dataset}_$n
    IFS=, read -r -a designs <<< "$set"
    start=$(date +%s)
    "$here/geth/geth" lab judge "$name" "${designs[@]}" > /dev/null 2>&1
    minutes=$(( ($(date +%s) - start) / 60 ))
    python3 - "$here" "$GETH_RUNS_DIR/lab" "$name" "$dataset" "$minutes" "${designs[@]}" <<'PYEOF' | tee -a "$out"
import json, subprocess, sys
here, lab, name, dataset, minutes, designs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6:]
def score(run):
    r = json.loads(subprocess.run(["python3", f"{here}/bench/lab/eval_design.py", f"{lab}/{run}", dataset],
                                  capture_output=True, text=True).stdout)
    got, total = map(int, r["score"].split("/"))
    return got, total, r["failed"]
inputs = [score(d) for d in designs]
judged = score(name)
print(json.dumps({"run": name, "dataset": dataset, "inputs": dict(zip(designs, [i[0] for i in inputs])),
                  "input_mean": round(sum(i[0] for i in inputs) / len(inputs), 1), "input_best": max(i[0] for i in inputs),
                  "judged": judged[0], "total": judged[1], "judged_failed": judged[2], "minutes": minutes}))
PYEOF
done
