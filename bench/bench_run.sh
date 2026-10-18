#!/usr/bin/env bash
# Full runs of benchmark plans that are already planned (e.g. by bench_plan.sh): approve automatically
# (benchmark data only: public test deliveries), run with the operator and reporter agents, score.
# Usage: bench_run.sh <tag> <run_name>:<dataset> [<run_name>:<dataset> ...]   (datasets: bench/eval_plan.py)
# One run at a time (two Nextflow drivers). Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; shift
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"

for item in "$@"; do
    name=${item%%:*}; kind=${item#*:}
    if ! "$geth" approve "$name" --yes > /dev/null 2>&1; then
        echo "{\"run\": \"$name\", \"error\": \"plan check failed: not approved\"}"
        continue
    fi
    t0=$(date +%s)
    "$geth" run "$name" > /dev/null 2>&1 || true
    t1=$(date +%s)
    python3 "$GETH_HOME/bench/eval_run.py" "$GETH_RUNS_DIR/$name" "$kind" 0 $(( t1 - t0 )) \
        || echo "{\"run\": \"$name\", \"error\": \"scoring failed\"}"
done | tee -a "$out"
