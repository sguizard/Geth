#!/usr/bin/env bash
# Stage nf-core test datasets as realistic "sequencing deliveries" (raw files + free-text metadata),
# so the planner agent has to build samplesheets/params itself (bench/bench.sh). About 120 MB, under
# $GETH_DATA_ROOT/testdata.
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"

TD=https://raw.githubusercontent.com/nf-core/test-datasets
BULK=$GETH_DATA_ROOT/testdata/bulk_yeast
SC=$GETH_DATA_ROOT/testdata/sc_mouse_chr19
mkdir -p $BULK/fastq $BULK/reference $SC/fastq $SC/reference

# --- bulk RNA-seq (S. cerevisiae, GSE110004 subset) ---
for f in SRR6357070_1 SRR6357070_2 SRR6357071_1 SRR6357071_2 SRR6357072_1 SRR6357072_2 \
         SRR6357073_1 SRR6357074_1 SRR6357075_1 SRR6357076_1 SRR6357076_2; do
    [ -s $BULK/fastq/$f.fastq.gz ] || curl -fsSL -o $BULK/fastq/$f.fastq.gz $TD/rnaseq/testdata/GSE110004/$f.fastq.gz
done
REF=$TD/626c8fab639062eade4b10747e919341cbf9b41a/reference
[ -s $BULK/reference/genome.fasta ] || curl -fsSL -o $BULK/reference/genome.fasta $REF/genome.fasta
[ -s $BULK/reference/genes.gtf.gz ] || curl -fsSL -o $BULK/reference/genes.gtf.gz $REF/genes_with_empty_tid.gtf.gz
cat > $BULK/metadata.tsv <<'EOF'
run	condition	biological_replicate	notes
SRR6357070	wild_type	1	same library as SRR6357071 (two sequencing runs)
SRR6357071	wild_type	1	same library as SRR6357070 (two sequencing runs)
SRR6357072	wild_type	2
SRR6357073	RAP1_uninduced	1	single-end
SRR6357074	RAP1_uninduced	2	single-end, same library as SRR6357075
SRR6357075	RAP1_uninduced	2	single-end, same library as SRR6357074
SRR6357076	RAP1_IAA_30min	1
EOF
cat > $BULK/README.txt <<'EOF'
Yeast (Saccharomyces cerevisiae) RNA-seq, Illumina, mix of paired-end and single-end runs.
Library strandedness is not documented. Reference genome and annotation are in reference/
(a small subset of the genome, for testing).
EOF

# --- scRNA-seq (mouse, chr19 subset, 10x Chromium) ---
for f in Sample_X_S1_L001_R1_001 Sample_X_S1_L001_R2_001 Sample_Y_S1_L001_R1_001 Sample_Y_S1_L001_R2_001 \
         Sample_Y_S1_L002_R1_001 Sample_Y_S1_L002_R2_001; do
    [ -s $SC/fastq/$f.fastq.gz ] || curl -fsSL -o $SC/fastq/$f.fastq.gz $TD/scrnaseq/testdata/cellranger/$f.fastq.gz
done
[ -s $SC/reference/GRCm38.p6.genome.chr19.fa ] || curl -fsSL -o $SC/reference/GRCm38.p6.genome.chr19.fa \
    https://github.com/nf-core/test-datasets/raw/scrnaseq/reference/GRCm38.p6.genome.chr19.fa
[ -s $SC/reference/gencode.vM19.annotation.chr19.gtf ] || curl -fsSL -o $SC/reference/gencode.vM19.annotation.chr19.gtf \
    https://github.com/nf-core/test-datasets/raw/scrnaseq/reference/gencode.vM19.annotation.chr19.gtf
cat > $SC/README.txt <<'EOF'
Mouse single-cell RNA-seq, 10x Genomics Chromium Single Cell 3' v2 chemistry.
Two samples: Sample_X (sequenced at Broad Institute) and Sample_Y (CRG Barcelona, two lanes).
About 5000 cells expected per sample. Reference: GRCm38 chromosome 19 only, GENCODE vM19 annotation.
EOF

du -sh $BULK $SC
