#!/usr/bin/env bash
# Run Geth on one test dataset with one model.
# Usage: run_geth.sh <bulk|sc> <qwen|mistral> <run_name> [--plan_only true]
set -euo pipefail
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

kind=$1; model_tag=$2; name=$3; shift 3
case $model_tag in
    qwen)    model=Qwen/Qwen3.5-397B-A17B-FP8 ;;
    mistral) model=mistralai/Mistral-Small-4-119B-2603 ;;
    *) echo "unknown model tag $model_tag" >&2; exit 1 ;;
esac
case $kind in
    bulk) data=$PERSEUS_VEIL/testdata/bulk_yeast
          question="Quantify gene expression in these yeast RNA-seq samples so that we can compare wild type with the RAP1 conditions." ;;
    sc)   data=$PERSEUS_VEIL/testdata/sc_mouse_chr19
          question="Process these single-cell RNA-seq samples into count matrices and give me a QC overview of the cells." ;;
    *) echo "unknown dataset $kind" >&2; exit 1 ;;
esac

run_dir=$PERSEUS_VEIL/spikes/nfcore/runs/$name
mkdir -p "$run_dir"
cd "$run_dir"
start=$(date +%s)
nextflow run "$GETH_HOME/spikes/nfcore/geth/main.nf" -c "$GETH_HOME/spikes/nfcore/geth/nextflow.config" \
    --model "$model" --question "$question" --data_dir "$data" --run_dir "$run_dir" "$@" \
    -w "$run_dir/geth_work" -with-agent-trace -with-trace "$run_dir/geth_trace.txt" -ansi-log false \
    > "$run_dir/geth.log" 2>&1 && rc=0 || rc=$?
echo "$name exit=$rc wall=$(( $(date +%s) - start ))s"
python3 -I "$GETH_HOME/spikes/nfcore/eval_plan.py" "$run_dir" "$kind"
