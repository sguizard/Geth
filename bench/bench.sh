#!/usr/bin/env bash
# Benchmark Geth v1 on the staged test deliveries: plan -> approve (automatic) -> run -> score.
# Usage: bench.sh <tag> <repeats> [bulk] [sc]
# Runs one after another so the drivers on node1q01 stay within 4 CPUs.
# Results: $PERSEUS_VEIL/geth/bench/<tag>.jsonl
set -uo pipefail
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

tag=$1; repeats=$2; shift 2
datasets=${*:-bulk sc}
geth=$GETH_HOME/geth/geth
out=$PERSEUS_VEIL/geth/bench/$tag.jsonl
mkdir -p "$(dirname "$out")"

declare -A data=( [bulk]=$PERSEUS_VEIL/testdata/bulk_yeast [sc]=$PERSEUS_VEIL/testdata/sc_mouse_chr19 )
declare -A question=(
    [bulk]="Quantify gene expression in these yeast RNA-seq samples so that we can compare wild type with the RAP1 conditions."
    [sc]="Process these single-cell RNA-seq samples into count matrices and give me a QC overview of the cells." )

for kind in $datasets; do
    for i in $(seq 1 "$repeats"); do
        name=${tag}_${kind}_$i
        t0=$(date +%s)
        "$geth" plan "${data[$kind]}" "${question[$kind]}" "$name" > /dev/null 2>&1 || { echo "{\"run\": \"$name\", \"error\": \"plan failed\"}" | tee -a "$out"; continue; }
        t1=$(date +%s)
        "$geth" approve "$name" --yes > /dev/null 2>&1
        "$geth" run "$name" > /dev/null 2>&1 || true
        t2=$(date +%s)
        python3 "$GETH_HOME/bench/eval_run.py" "$PERSEUS_VEIL/geth/runs/$name" "$kind" $((t1 - t0)) $((t2 - t1)) | tee -a "$out"
    done
done
