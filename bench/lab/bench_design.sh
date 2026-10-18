#!/usr/bin/env bash
# Lab benchmark, arm A (EXPERIMENTAL): design-only repeats on the lab datasets, each design scored by
# bench/lab/eval_design.py. Nothing runs on the data. One designer at a time.
# Usage: bench_design.sh <tag> <repeats> <skill|noskill> <kang2018|pbmc1k> [...]
# Datasets: bench/lab/stage_kang.sh (kang2018); testdata/lab_pbmc1k (pbmc1k). Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"

tag=$1; repeats=$2; arm=$3; shift 3
[ "$arm" = skill ] && flag="" || flag="--no-skill"
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
declare -A data=( [kang2018]=$GETH_DATA_ROOT/testdata/lab_kang2018 [pbmc1k]=$GETH_DATA_ROOT/testdata/lab_pbmc1k )
declare -A question=(
    [kang2018]="Which genes respond to interferon-beta in each immune cell type of these PBMCs? Design the complete analysis."
    [pbmc1k]="Which cell types are in this PBMC sample, and what are their marker genes? Design the complete analysis." )

for ds in "$@"; do
    for i in $(seq 1 "$repeats"); do
        name=${tag}_${ds}_${arm}_$i
        t0=$(date +%s)
        "$GETH_HOME/geth/lab/lab.sh" design "${data[$ds]}" "${question[$ds]}" "$name" $flag > /dev/null 2>&1 \
            && status=ok || status=failed
        t1=$(date +%s)
        python3 "$GETH_HOME/bench/lab/eval_design.py" "$GETH_RUNS_DIR/lab/$name" "$ds" \
            | python3 -c 'import json, sys; d = json.load(sys.stdin); d.update(status=sys.argv[1], minutes=round(int(sys.argv[2]) / 60, 1)); print(json.dumps(d))' \
                "$status" "$(( t1 - t0 ))" \
            || echo "{\"run\": \"$name\", \"error\": \"scoring failed\", \"status\": \"$status\"}"
    done
done | tee -a "$out"
