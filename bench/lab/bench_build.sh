#!/usr/bin/env bash
# Lab benchmark, arm B (EXPERIMENTAL): agents build checked designs into sandboxed pipelines, which then run on
# the full data; each build is scored by bench/lab/eval_build.py. One build at a time.
# Usage: bench_build.sh <tag> <skill|noskill|c> <design run>:<kang2018|pbmc1k> [...]   (c: arm C, build-c)
# Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"
here=$(cd "$(dirname "$0")/../.." && pwd)
tag=$1 arm=$2; shift 2
case $arm in skill) cmd=build flag=() ;; noskill) cmd=build flag=(--no-skill) ;; c) cmd=build-c flag=() ;; esac
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
for item in "$@"; do
    design=${item%%:*} dataset=${item##*:}
    name=${tag}_${design#lab_}
    start=$(date +%s)
    "$here/geth/geth" lab "$cmd" "$design" "$name" "${flag[@]}" > /dev/null 2>&1
    minutes=$(( ($(date +%s) - start) / 60 ))
    "$here/bench/lab/score_build.sh" "$GETH_RUNS_DIR/lab/$name" "$dataset" | tail -n 1 \
        | python3 -c "import json,sys; r=json.loads(sys.stdin.read()); r['design']='$design'; r['arm']='$arm'; r['minutes']=$minutes; print(json.dumps(r))" \
        | tee -a "$out"
done
