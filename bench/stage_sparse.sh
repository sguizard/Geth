#!/usr/bin/env bash
# Sparse deliveries for the Rannoch R3 benchmark: the same reads and references as the test deliveries
# (hard links: no extra space, and visible in the agent sandbox), with a one-line README. What the README no
# longer says is in bench/facts/<delivery>.txt, the answers file of a stand-in scientist.
# Usage: stage_sparse.sh [<delivery> ...]  ->  $GETH_DATA_ROOT/testdata_sparse/<delivery>
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"
SRC=$GETH_DATA_ROOT/testdata
DST=$GETH_DATA_ROOT/testdata_sparse
declare -A readme=(
    [bulk_yeast]="Yeast RNA-seq for the RAP1 project (Illumina). Reference genome and annotation in reference/."
    [chipseq_spt5]="Spt5 ChIP-seq in budding yeast, with input controls (Illumina). Reference in reference/."
    [ampliseq_16s]="16S rRNA amplicon sequencing of soil samples, Illumina MiSeq paired-end."
    [eager_mammoth]="Ancient DNA from two woolly mammoth specimens. Reference (mitochondrial genome) in reference/."
    [methylseq_wgbs]="DNA methylation sequencing of one sample, three lanes. Reference in reference/."
    [sc_rat_ocm]="Single-cell RNA-seq of rat PBMCs, 10x Genomics. Reference (rat chromosome 6) in reference/."
    # held out: not used to tune the planner
    [nanoseq_barcoded]="Oxford Nanopore DNA sequencing (MinION) of the human KCMF1 locus. Reference in reference/."
    [atacseq_osmotic]="ATAC-seq of budding yeast under osmotic stress, Illumina paired-end. Reference in reference/."
    [isoseq_brain]="PacBio Iso-Seq of human brain tissue. Reference in reference/." )
for d in "${@:-${!readme[@]}}"; do
    [ -n "${readme[$d]:-}" ] || { echo "unknown delivery: $d" >&2; continue; }
    rm -rf "${DST:?}/$d"
    mkdir -p "$DST/$d"
    for f in "$SRC/$d"/*; do  # everything but the delivery's text (README, sample tables)
        case "$(basename "$f")" in README*|*.txt|*.tsv|*.csv) ;; *) cp -al "$f" "$DST/$d/" ;; esac
    done
    echo "${readme[$d]}" > "$DST/$d/README.txt"
    echo "OK $d: $(find "$DST/$d" -type f | wc -l) files"
done
