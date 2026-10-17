#!/usr/bin/env bash
# Planner benchmark: plan-only repeats on staged test deliveries, each plan scored against the known design
# (bench/eval_plan.py). Nothing is approved or run. One planner at a time (one Nextflow driver).
# Usage: bench_plan.sh <tag> <repeats> <delivery> [<delivery> ...]
#   deliveries: chipseq_spt5 atacseq_osmotic methylseq_wgbs ampliseq_16s nanoseq_barcoded eager_mammoth isoseq_brain
#   (bench/stage_deliveries.sh), bulk_yeast sc_mouse_chr19 (bench/stage_testdata.sh),
#   airway_index_test pbmc_index_test (bench/stage_index_tests.sh)
# Results: $GETH_BENCH_DIR/<tag>.jsonl (default $GETH_WORK_ROOT/bench)
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; repeats=$2; shift 2
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"

declare -A question=(
    [chipseq_spt5]="Find where Spt5 binds the genome at each time point, compared with the input controls."
    [atacseq_osmotic]="Find the open chromatin regions in each condition so that we can compare 0 and 15 minutes of osmotic stress."
    [methylseq_wgbs]="Measure DNA methylation at every CpG in this sample."
    [ampliseq_16s]="Which bacteria are in these soil samples? Compare the control and the warmed plots."
    [nanoseq_barcoded]="Demultiplex these Nanopore reads and align them to the reference."
    [eager_mammoth]="Map these ancient mammoth reads to the mitochondrial genome and report mapping, duplication and DNA damage."
    [isoseq_brain]="Identify the full-length transcripts in this Iso-Seq library and map them to chromosome 19."
    [bulk_yeast]="Quantify gene expression in these yeast RNA-seq samples so that we can compare wild type with the RAP1 conditions."
    [sc_mouse_chr19]="Process these single-cell RNA-seq samples into count matrices and give me a QC overview of the cells."
    [airway_index_test]="Quantify gene expression in these two samples (untreated and dexamethasone-treated)."
    [pbmc_index_test]="Process this single-cell RNA-seq sample into a count matrix with STARsolo and give me a QC overview of the cells."
    [chicken_wgs]="Call germline SNVs and small indels in these three chickens, genotyped together, and annotate them."
    [taxprofiler_reads]="Which organisms are in these two metagenomic samples, and how abundant are they?"
    [mag_gut]="Reconstruct the bacterial genomes in these mouse gut metagenomes and tell me how complete they are." )
declare -A dataset=( [bulk_yeast]=bulk [sc_mouse_chr19]=sc )

for delivery in "$@"; do
    [ -n "${question[$delivery]:-}" ] || { echo "unknown delivery: $delivery" >&2; continue; }
    for i in $(seq 1 "$repeats"); do
        name=${tag}_${delivery}_$i
        t0=$(date +%s)
        "$geth" plan "$GETH_DATA_ROOT/testdata/$delivery" "${question[$delivery]}" "$name" > /dev/null 2>&1 \
            && status=ok || status=failed
        t1=$(date +%s)
        python3 "$GETH_HOME/bench/eval_plan.py" "$GETH_RUNS_DIR/$name" "${dataset[$delivery]:-$delivery}" \
            | python3 -c 'import json, os, sys
d = json.load(sys.stdin)
run_dir, status, minutes = sys.argv[1], sys.argv[2], int(sys.argv[3]) / 60
check = os.path.join(run_dir, "plan_check.txt")
d.update(plan_status=status, plan_min=round(minutes, 1),
         plan_check=open(check).readline().strip() if os.path.isfile(check) else "none")
print(json.dumps(d))' "$GETH_RUNS_DIR/$name" "$status" "$(( t1 - t0 ))" 2>/dev/null \
            || echo "{\"run\": \"$name\", \"error\": \"scoring failed\", \"plan_status\": \"$status\"}"
    done
done | tee -a "$out"
