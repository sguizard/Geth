#!/usr/bin/env bash
# Full runs of benchmark plans that are already planned (e.g. by bench_plan.sh): approve automatically
# (benchmark data only: public test deliveries), run with the operator and reporter agents, score.
# Usage: bench_run.sh <tag> <run_name>:<dataset>[:<planned run>] ...   (datasets: bench/eval_plan.py)
#   <planned run>: copy that run's plan into a new run <run_name> first (the same plan for two runners).
# One run at a time (two Nextflow drivers). Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; shift
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"

{  # Ctrl-C: the run is in its own process group (the time limit's), so stop it explicitly
trap 'echo "Interrupted: stopping ${name:-the current run} ..." >&2; [ -n "${name:-}" ] && "$geth" stop "$name" >&2; exit 130' INT TERM
for item in "$@"; do
    IFS=: read -r name kind from <<< "$item"
    if [ -n "$from" ] && [ ! -e "$GETH_RUNS_DIR/$name" ]; then
        mkdir -p "$GETH_RUNS_DIR/$name"
        cp "$GETH_RUNS_DIR/$from"/{question.txt,data_dir.txt} "$GETH_RUNS_DIR/$from"/plan_* "$GETH_RUNS_DIR/$name"/
    fi
    if ! "$geth" approve "$name" --yes > /dev/null 2>&1; then
        echo "{\"run\": \"$name\", \"error\": \"plan check failed: not approved\"}"
        continue
    fi
    # timed from when the run has its driver slots (its pid file), not from when it started waiting for them
    "$geth" run "$name" > /dev/null 2>&1 &
    pid=$!
    while kill -0 $pid 2>/dev/null && [ ! -f "$GETH_RUNS_DIR/$name/.geth_run.pid" ]; do sleep 2; done
    t0=$(date +%s)
    wait $pid
    t1=$(date +%s)
    python3 "$GETH_HOME/bench/eval_run.py" "$GETH_RUNS_DIR/$name" "$kind" 0 $(( t1 - t0 )) \
        || echo "{\"run\": \"$name\", \"error\": \"scoring failed\"}"
done
} | tee -a "$out"
