#!/usr/bin/env bash
# Deliveries for the project benchmark (geth legion, R5), in $GETH_DATA_ROOT/testdata:
#   project_multiomics_yeast  RNA-seq (RNA/) and ATAC-seq (ATAC/) of yeast in one delivery: two independent steps
#   project_yeast_noref       the yeast RNA-seq without its reference: Ensembl's yeast genome must be staged first
#   project_smallrna          human small-RNA (miRNA) reads, which no Geth pipeline handles: a gap (nf-core/smrnaseq)
# The yeast files are hard links to bench/stage_testdata.sh and stage_deliveries.sh deliveries; the small-RNA reads
# come from nf-core/test-datasets (about 70 MB). Usage: stage_projects.sh
set -euo pipefail
[ -n "${GETH_DATA_ROOT:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"
t=$GETH_DATA_ROOT/testdata

d=$t/project_multiomics_yeast
if [ ! -d "$d" ]; then
    mkdir -p "$d/RNA" "$d/ATAC"
    cp -al "$t/bulk_yeast/." "$d/RNA/"
    cp -al "$t/atacseq_osmotic/." "$d/ATAC/"
    cat > "$d/README.txt" <<'EOF'
Yeast (Saccharomyces cerevisiae) project delivery from the sequencing facility.
RNA/   bulk RNA-seq (see RNA/README.txt and RNA/metadata.tsv)
ATAC/  ATAC-seq (see ATAC/README.txt and ATAC/samples.tsv)
Each folder has its own reference genome and annotation in reference/.
EOF
fi

d=$t/project_yeast_noref
if [ ! -d "$d" ]; then
    mkdir -p "$d/fastq"
    cp -al "$t/bulk_yeast/fastq/." "$d/fastq/"
    cp -al "$t/bulk_yeast/metadata.tsv" "$d/"
    cat > "$d/README.txt" <<'EOF'
Yeast (Saccharomyces cerevisiae, reference strain S288C) RNA-seq, Illumina, mix of paired-end and single-end runs.
Library strandedness is not documented. No reference genome is included: use the standard reference.
Sample information is in metadata.tsv.
EOF
fi

d=$t/project_smallrna
if [ ! -d "$d" ]; then
    mkdir -p "$d/fastq.part"
    base=https://raw.githubusercontent.com/nf-core/test-datasets/smrnaseq/testdata
    curl -fsSL -o "$d/fastq.part/Control_S1_L001_R1_001.fastq.gz" "$base/sample_1.fastq.gz"
    curl -fsSL -o "$d/fastq.part/Clone1_S2_L001_R1_001.fastq.gz" "$base/sample_2.fastq.gz"
    mv "$d/fastq.part" "$d/fastq"
    cat > "$d/README.txt" <<'EOF'
Human cell line, small RNA sequencing (single-end reads, 150 cycles).
Control_S1: parental line. Clone1_S2: knock-out clone.
The libraries target microRNAs; adapters were not trimmed.
EOF
fi
ls -d "$t"/project_*
