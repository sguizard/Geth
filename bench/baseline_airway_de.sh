#!/usr/bin/env bash
# Baseline (no agents) for the airway differential-expression benchmark: nf-core/differentialabundance with the
# textbook design written by a person (dexamethasone vs untreated, blocking on donor), on the counts of a
# finished nf-core/rnaseq run of the airway data (bench/stage_public.sh, then a Geth run, by default airway_1).
# The sample names are those of the reference run: <donor>_untreated and <donor>_Dex.
# Usage: baseline_airway_de.sh [<rnaseq_run_name>]
# Results: $GETH_BASELINES_DIR/airway_de/results (default $GETH_WORK_ROOT/baselines), read by eval_run.py.
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"
here=$(cd "$(dirname "$0")/.." && pwd)

up=$GETH_RUNS_DIR/${1:-airway_1}
star=$up/results/star_salmon
[ -f "$star/salmon.merged.gene_counts.tsv" ] || { echo "No count matrix in $star: run the airway rnaseq analysis first" >&2; exit 1; }
gtf=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["gtf"])' "$up/plan_params.json")
out=${GETH_BASELINES_DIR:-$GETH_WORK_ROOT/baselines}/airway_de
mkdir -p "$out"
cd "$out"
{
    echo "sample,condition,donor"
    for donor in N61311 N052611 N080611 N061011; do
        echo "${donor}_untreated,untreated,$donor"
        echo "${donor}_Dex,dex,$donor"
    done
} > observations.csv
printf 'id,variable,reference,target,blocking\ndex_vs_untreated,condition,untreated,dex,donor\n' > contrasts.csv

revision=$(python3 "$here/geth/bin/geth_checks.py" revision differentialabundance)
extra=()
[ -n "${GETH_NFCORE_CONFIG:-}" ] && extra+=(-c "$GETH_NFCORE_CONFIG")
nextflow run nf-core/differentialabundance -r "$revision" -profile "${GETH_NFCORE_PROFILE:+$GETH_NFCORE_PROFILE,}rnaseq" \
    -c "$here/geth/conf/test.config" "${extra[@]}" \
    --input observations.csv --contrasts contrasts.csv \
    --matrix "$star/salmon.merged.gene_counts.tsv" --feature_length_matrix "$star/salmon.merged.gene_lengths.tsv" \
    --gtf "$gtf" --outdir "$out/results" -w "$out/work" -ansi-log false > "$out/run.log" 2>&1
rc=$?
echo "airway_de baseline: exit=$rc (log: $out/run.log)"
exit $rc
