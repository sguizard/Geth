#!/usr/bin/env bash
# Lab benchmark, arm B (EXPERIMENTAL): agents build checked designs into sandboxed pipelines, which then run on
# the full data; each build is scored by bench/lab/eval_build.py. One build at a time.
# Usage: bench_build.sh <tag> <design run>:<kang2018|pbmc1k> [...]       Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"
here=$(cd "$(dirname "$0")/../.." && pwd)
tag=$1; shift
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
for item in "$@"; do
    design=${item%%:*} dataset=${item##*:}
    name=${tag}_${design#lab_}
    start=$(date +%s)
    "$here/geth/geth" lab build "$design" "$name" > /dev/null 2>&1
    minutes=$(( ($(date +%s) - start) / 60 ))
    "$here/bench/lab/score_build.sh" "$GETH_RUNS_DIR/lab/$name" "$dataset" | tail -n 1 \
        | python3 -c "import json,sys; r=json.loads(sys.stdin.read()); r['design']='$design'; r['minutes']=$minutes; print(json.dumps(r))" \
        | tee -a "$out"
done
