#!/usr/bin/env bash
# Planner benchmark: plan-only repeats on staged test deliveries, each plan scored against the known design
# (bench/eval_plan.py). Nothing is approved or run. One planner at a time (one Nextflow driver).
# Usage: bench_plan.sh <tag> <repeats> <delivery> [<delivery> ...]
#   deliveries: chipseq_spt5 atacseq_osmotic methylseq_wgbs ampliseq_16s nanoseq_barcoded eager_mammoth isoseq_brain
#   (bench/stage_deliveries.sh), bulk_yeast sc_mouse_chr19 (bench/stage_testdata.sh),
#   airway_index_test pbmc_index_test (bench/stage_index_tests.sh), sc_rat_ocm (multiplexed 10x)
# Results: $GETH_BENCH_DIR/<tag>.jsonl (default $GETH_WORK_ROOT/bench)
# Rannoch R3: GETH_BENCH_TESTDATA=testdata_sparse plans the sparse deliveries (bench/stage_sparse.sh);
# GETH_BENCH_ANSWERS=yes lets a stand-in scientist answer the planner from bench/facts/<delivery>.txt;
# GETH_PLANNER_ASK=off plans without questions.
# A paid planner model (GETH_MODEL_MODEL, see geth/harness/llm.py) needs GETH_BENCH_BUDGET_USD: no plan starts
# once the plans of this tag have spent it (each plan is also capped by GETH_MODEL_BUDGET_USD).
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
    [mag_gut]="Reconstruct the bacterial genomes in these mouse gut metagenomes and tell me how complete they are."
    [sc_rat_ocm]="Process these single-cell RNA-seq data into count matrices and give me a QC overview of the cells." )
declare -A dataset=( [bulk_yeast]=bulk [sc_mouse_chr19]=sc )

if [ -n "${GETH_MODEL_MODEL:-${GETH_PLANNER_MODEL:-}}" ] && [ -z "${GETH_BENCH_BUDGET_USD:-}" ]; then
    echo "A chosen model is set (GETH_MODEL_MODEL): set GETH_BENCH_BUDGET_USD too (the most this benchmark may spend)" >&2; exit 1
fi
spent() {  # USD spent so far by the plans of this tag (from their recorded model usage)
    python3 -c 'import json, sys
total = 0.0
for line in open(sys.argv[1]) if __import__("os").path.isfile(sys.argv[1]) else []:
    try:
        total += (json.loads(line).get("model_usage") or {}).get("usd", 0)
    except ValueError:
        pass
print(f"{total:.4f}")' "$out"
}
{  # Ctrl-C: the planner runs in its own process group (the time limit's), so stop the current plan explicitly
trap 'echo "Interrupted: stopping ${name:-the current plan} ..." >&2; [ -n "${name:-}" ] && "$geth" stop "$name" >&2; exit 130' INT TERM
for delivery in "$@"; do
    [ -n "${question[$delivery]:-}" ] || { echo "unknown delivery: $delivery" >&2; continue; }
    for i in $(seq 1 "$repeats"); do
        if [ -n "${GETH_BENCH_BUDGET_USD:-}" ] && python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) >= float(sys.argv[2]) else 1)' "$(spent)" "$GETH_BENCH_BUDGET_USD"; then
            echo "Budget reached: \$$(spent) spent of \$$GETH_BENCH_BUDGET_USD; no further plan started." >&2
            break 2
        fi
        name=${tag}_${delivery}_$i
        t0=$(date +%s)
        rss=$(mktemp)
        answers=()
        [ "${GETH_BENCH_ANSWERS:-no}" = yes ] && answers=(--answers "$GETH_HOME/bench/facts/$delivery.txt")
        /usr/bin/time -f "%M" -o "$rss" "$geth" plan "$GETH_DATA_ROOT/${GETH_BENCH_TESTDATA:-testdata}/$delivery" \
            "${question[$delivery]}" "$name" "${answers[@]}" < /dev/null > /dev/null 2>&1 && status=ok || status=failed
        t1=$(date +%s)
        python3 "$GETH_HOME/bench/eval_plan.py" "$GETH_RUNS_DIR/$name" "${dataset[$delivery]:-$delivery}" \
            | python3 -c 'import json, os, sys
d = json.load(sys.stdin)
run_dir, status, minutes = sys.argv[1], sys.argv[2], int(sys.argv[3]) / 60
check = os.path.join(run_dir, "plan_check.txt")
d.update(plan_status=status, plan_min=round(minutes, 1),
         plan_check=open(check).readline().strip() if os.path.isfile(check) else "none",
         planner="rannoch", peak_rss_mb=round(int(sys.argv[4] or 0) / 1024))
log = os.path.join(run_dir, "geth_plan.log")
usage = [l for l in open(log) if l.startswith("Model usage:")] if os.path.isfile(log) else []
if usage:
    d["model_usage"] = json.loads(usage[-1].split(":", 1)[1])  # printed by the harness
qa = os.path.join(run_dir, "plan_questions.md")
if os.path.isfile(qa):
    text = open(qa).read()
    d.update(questions=text.count("\n**"), unknown_answers=text.count("know: use your recommendation"),
             rounds=text.count("\n## Round"))
print(json.dumps(d))' "$GETH_RUNS_DIR/$name" "$status" "$(( t1 - t0 ))" "$(tail -n 1 "$rss" 2>/dev/null)" 2>/dev/null \
            || echo "{\"run\": \"$name\", \"error\": \"scoring failed\", \"plan_status\": \"$status\"}"
        rm -f "$rss"
    done
done
} | tee -a "$out"
