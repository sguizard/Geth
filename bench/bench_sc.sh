#!/usr/bin/env bash
# Benchmark agent-designed single-cell downstream analyses on a finished scrnaseq run:
# plan (designer) -> approve (automatic: benchmark only) -> run (analyst + reporter) -> score.
# Usage: bench_sc.sh <tag> <repeats> <upstream_run>
# Results: $PERSEUS_VEIL/geth/bench/<tag>.jsonl
set -uo pipefail
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

tag=$1; repeats=$2; upstream=$3
geth=$GETH_HOME/geth/geth
out=$PERSEUS_VEIL/geth/bench/$tag.jsonl
question="Analyse the cells of this PBMC sample: filter low-quality cells and doublets, cluster them, and identify the cell types with their marker genes."
mkdir -p "$(dirname "$out")"

for i in $(seq 1 "$repeats"); do
    name=${tag}_$i
    t0=$(date +%s)
    "$geth" plan --from "$upstream" "$question" "$name" > /dev/null 2>&1 \
        || { echo "{\"run\": \"$name\", \"error\": \"plan failed\"}" | tee -a "$out"; continue; }
    t1=$(date +%s)
    "$geth" approve "$name" --yes > /dev/null 2>&1 \
        || { echo "{\"run\": \"$name\", \"error\": \"plan check failed\"}" | tee -a "$out"; continue; }
    "$geth" run "$name" > /dev/null 2>&1 || true
    t2=$(date +%s)
    python3 "$GETH_HOME/bench/eval_sc.py" "$PERSEUS_VEIL/geth/runs/$name" \
        | python3 -c "import json, sys; d = json.load(sys.stdin); d.update(plan_min=round(($t1-$t0)/60, 1), run_min=round(($t2-$t1)/60, 1)); print(json.dumps(d))" \
        | tee -a "$out"
done
