#!/usr/bin/env bash
# Stage realistic "sequencing deliveries" for the planner benchmark of the pipelines added in v1.4: files from
# nf-core test datasets, renamed the way a sequencing facility would deliver them, with a free-text README
# and a sample table. The planner must work out the design from these, as for a real delivery.
# About 250 MB under $GETH_DATA_ROOT/testdata/<delivery>. Usage: stage_deliveries.sh [<delivery> ...]
#   chipseq_spt5  atacseq_osmotic  methylseq_wgbs  ampliseq_16s  nanoseq_barcoded  eager_mammoth  isoseq_brain
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"

TD=https://raw.githubusercontent.com/nf-core/test-datasets
ROOT=$GETH_DATA_ROOT/testdata
deliveries=${*:-chipseq_spt5 atacseq_osmotic methylseq_wgbs ampliseq_16s nanoseq_barcoded eager_mammoth isoseq_brain}

get() {  # get <url> <file>: download once
    [ -s "$2" ] && return 0
    mkdir -p "$(dirname "$2")"
    curl -fsSL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}

split_lanes() {  # split_lanes <in.fastq.gz> <out_lane1.fastq.gz> <out_lane2.fastq.gz>: first/second half of the reads
    python3 -I - "$@" <<'EOF'
import gzip, sys
src, a, b = sys.argv[1:]
lines = gzip.open(src, "rt").read().splitlines(keepends=True)
half = (len(lines) // 8) * 4
with gzip.open(a, "wt") as fa, gzip.open(b, "wt") as fb:
    fa.writelines(lines[:half]); fb.writelines(lines[half:])
EOF
}

chipseq_spt5() {
    local d=$ROOT/chipseq_spt5 a=$TD/atacseq/testdata c=$TD/chipseq/testdata
    local -A ip=( [CHIP01_S1]=SRR1822153 [CHIP02_S2]=SRR1822154 [CHIP03_S3]=SRR1822157 [CHIP04_S4]=SRR1822158 )
    for lib in "${!ip[@]}"; do
        get "$a/${ip[$lib]}_1.fastq.gz" "$d/fastq/${lib}_L001_R1_001.fastq.gz"
        get "$a/${ip[$lib]}_2.fastq.gz" "$d/fastq/${lib}_L001_R2_001.fastq.gz"
    done
    local srr=(SRR5204809 SRR5204810)
    for i in 1 2; do
        get "$c/${srr[i-1]}_Spt5-ChIP_Input${i}_SacCer_ChIP-Seq_ss100k_R1.fastq.gz" "$d/fastq/INPUT0${i}_S$((4 + i))_L001_R1_001.fastq.gz"
        get "$c/${srr[i-1]}_Spt5-ChIP_Input${i}_SacCer_ChIP-Seq_ss100k_R2.fastq.gz" "$d/fastq/INPUT0${i}_S$((4 + i))_L001_R2_001.fastq.gz"
    done
    get "$TD/atacseq/reference/genome.fa" "$d/reference/genome.fa"
    get "$TD/atacseq/reference/genes.gtf" "$d/reference/genes.gtf"
    cat > "$d/README.txt" <<'EOF'
ChIP-seq of the transcription elongation factor Spt5 in budding yeast (Saccharomyces cerevisiae),
at two time points: 0 min and 15 min. Two independent cultures (biological replicates 1 and 2) per time
point. From each culture we also sequenced the input DNA (no antibody), which is the control for that
culture's ChIP samples. See samples.tsv.
Illumina paired-end sequencing, 50 bp reads (subsampled to a few thousand read pairs for this test).
Reference genome (S. cerevisiae R64, Ensembl chromosome names) and gene annotation are in reference/.
EOF
    tr '|' '\t' > "$d/samples.tsv" <<'EOF'
library|antibody|time_point|culture|notes
CHIP01|Spt5|0 min|1|
CHIP02|Spt5|0 min|2|
CHIP03|Spt5|15 min|1|
CHIP04|Spt5|15 min|2|
INPUT01|none|-|1|input DNA of culture 1
INPUT02|none|-|2|input DNA of culture 2
EOF
}

atacseq_osmotic() {
    local d=$ROOT/atacseq_osmotic a=$TD/atacseq/testdata t=$ROOT/.cache_atac
    get "$a/SRR1822153_1.fastq.gz" "$t/SRR1822153_1.fastq.gz"
    get "$a/SRR1822153_2.fastq.gz" "$t/SRR1822153_2.fastq.gz"
    mkdir -p "$d/fastq"
    for r in 1 2; do  # library ATAC01 was sequenced on two lanes
        [ -s "$d/fastq/ATAC01_S1_L002_R${r}_001.fastq.gz" ] || split_lanes "$t/SRR1822153_${r}.fastq.gz" \
            "$d/fastq/ATAC01_S1_L001_R${r}_001.fastq.gz" "$d/fastq/ATAC01_S1_L002_R${r}_001.fastq.gz"
    done
    rm -f "$t"/SRR1822153_[12].fastq.gz && rmdir "$t"
    local -A lib=( [ATAC02_S2]=SRR1822154 [ATAC03_S3]=SRR1822157 [ATAC04_S4]=SRR1822158 )
    for l in "${!lib[@]}"; do
        get "$a/${lib[$l]}_1.fastq.gz" "$d/fastq/${l}_L001_R1_001.fastq.gz"
        get "$a/${lib[$l]}_2.fastq.gz" "$d/fastq/${l}_L001_R2_001.fastq.gz"
    done
    get "$TD/atacseq/reference/genome.fa" "$d/reference/genome.fa"
    get "$TD/atacseq/reference/genes.gtf" "$d/reference/genes.gtf"
    cat > "$d/README.txt" <<'EOF'
ATAC-seq of budding yeast (Saccharomyces cerevisiae) before (0 min) and 15 min after osmotic stress.
Two biological replicates per time point (see samples.tsv). Library ATAC01 was sequenced on two lanes.
Illumina paired-end sequencing, 50 bp reads (subsampled for this test). No input controls.
Reference genome (S. cerevisiae R64, Ensembl chromosome names, mitochondrial genome included) and gene
annotation are in reference/. We want accessible regions for each condition and their differences.
EOF
    tr '|' '\t' > "$d/samples.tsv" <<'EOF'
library|condition|replicate|notes
ATAC01|osmotic stress 0 min|1|sequenced on lanes L001 and L002
ATAC02|osmotic stress 0 min|2|
ATAC03|osmotic stress 15 min|1|
ATAC04|osmotic stress 15 min|2|
EOF
}

methylseq_wgbs() {
    local d=$ROOT/methylseq_wgbs m=$TD/methylseq
    for i in 1 2 3; do
        get "$m/testdata/SRR389222_sub${i}.fastq.gz" "$d/fastq/WGBS-07_S7_L00${i}_R1_001.fastq.gz"
    done
    get "$m/reference/genome.fa.gz" "$d/reference/genome.fa.gz"
    cat > "$d/README.txt" <<'EOF'
Whole-genome bisulfite sequencing (WGBS) of one sample (library WGBS-07): standard directional bisulfite
library (no PBAT, not RRBS, not enzymatic conversion). The library was sequenced on three lanes,
single-end reads (subsampled for this test).
The reference sequence for this test is in reference/genome.fa.gz.
We want per-CpG methylation levels.
EOF
}

ampliseq_16s() {
    local d=$ROOT/ampliseq_16s a=$TD/ampliseq/testdata
    for s in 1_S103 1a_S103 2_S115 2a_S115; do
        get "$a/${s}_L001_R1_001.fastq.gz" "$d/fastq/${s}_L001_R1_001.fastq.gz"
        get "$a/${s}_L001_R2_001.fastq.gz" "$d/fastq/${s}_L001_R2_001.fastq.gz"
    done
    cat > "$d/README.txt" <<'EOF'
16S rRNA gene amplicon sequencing (V4 region) of four soil samples, two control plots and two warmed plots.
PCR primers: 515F (GTGYCAGCMGCCGCGGTAA) and 806R (GGACTACNVGGGTWTCTAAT); primers are still in the reads.
Illumina MiSeq, paired-end. The samples were sequenced in two different MiSeq runs (see samples.tsv);
the file names start with the facility's sample number (1, 2, 1a, 2a).
We would like the taxonomic composition of each sample and a comparison of control and warmed plots.
EOF
    tr '|' '\t' > "$d/samples.tsv" <<'EOF'
facility_id|plot|treatment|sequencing_run
1|plot_A|control|run_2026_03
2|plot_B|control|run_2026_03
1a|plot_C|warmed|run_2026_05
2a|plot_D|warmed|run_2026_05
EOF
}

nanoseq_barcoded() {
    local d=$ROOT/nanoseq_barcoded n=$TD/nanoseq
    get "$n/fastq/nondemultiplexed/sample_nobc_dx.fastq.gz" "$d/fastq_pass/FAQ91234_pass_0.fastq.gz"
    get "$n/reference/hg19_KCMF1.fa" "$d/reference/hg19_KCMF1.fa"
    cat > "$d/README.txt" <<'EOF'
Oxford Nanopore (MinION, R9.4.1 flow cell) DNA sequencing of the human KCMF1 locus: two replicate
libraries of the same sample, multiplexed with the native barcoding kits EXP-NBD103/EXP-NBD104.
Replicate 1 = barcode 06, replicate 2 = barcode 12. Reads are basecalled but NOT demultiplexed:
everything is in one FASTQ file in fastq_pass/.
Reference sequence (hg19 region around KCMF1) in reference/. Please align the reads to it.
EOF
}

eager_mammoth() {
    local d=$ROOT/eager_mammoth e=$TD/eager/testdata/Mammoth/fastq
    get "$e/JK2782_TGGCCGATCAACGA_L008_R1_001.fastq.gz.tengrand.fq.gz" "$d/fastq/JK2782_TGGCCGATCAACGA_L008_R1_001.fastq.gz"
    get "$e/JK2782_TGGCCGATCAACGA_L008_R2_001.fastq.gz.tengrand.fq.gz" "$d/fastq/JK2782_TGGCCGATCAACGA_L008_R2_001.fastq.gz"
    get "$e/JK2802_AGAATAACCTACCA_L008_R1_001.fastq.gz.tengrand.fq.gz" "$d/fastq/JK2802_AGAATAACCTACCA_L008_R1_001.fastq.gz"
    get "$TD/eager/reference/Mammoth/Mammoth_MT_Krause.fasta" "$d/reference/Mammoth_MT_Krause.fasta"
    cat > "$d/README.txt" <<'EOF'
Ancient DNA from two woolly mammoth (Mammuthus primigenius) specimens, JK2782 and JK2802: one
double-stranded library per specimen.
- JK2782: no UDG treatment; sequenced paired-end on a HiSeq 4000 (lane 8).
- JK2802: full UDG treatment; sequenced single-end on a NextSeq 500 (lane 8).
Reads are subsampled for this test. Reference: mammoth mitochondrial genome (Krause et al. 2006) in
reference/. We want mapping statistics, deduplication and DNA damage profiles.
EOF
}

isoseq_brain() {
    local d=$ROOT/isoseq_brain i=$TD/isoseq
    get "$i/testdata/alz.1perc.subreads.10000.bam" "$d/raw/alz_brain.subreads.bam"
    get "$i/testdata/alz.1perc.subreads.10000.bam.pbi" "$d/raw/alz_brain.subreads.bam.pbi"
    get "$i/testdata/primers.fasta" "$d/primers.fasta"
    get "$i/reference/Homo_sapiens.GRCh38.dna.chromosome.19.fasta" "$d/reference/Homo_sapiens.GRCh38.dna.chromosome.19.fasta"
    get "$i/reference/Homo_sapiens.GRCh38.104.chr.13_18_19.gtf" "$d/reference/Homo_sapiens.GRCh38.104.chr.13_18_19.gtf"
    cat > "$d/README.txt" <<'EOF'
PacBio Iso-Seq (full-length cDNA, Sequel) of human brain tissue from an Alzheimer's disease donor: one
library, raw subreads (BAM with its .pbi index; a 1% subset for this test). The cDNA primer sequences
used for the library are in primers.fasta.
Reference: GRCh38 chromosome 19 (Ensembl) and the Ensembl 104 annotation of chromosomes 13, 18 and 19,
in reference/. We want the full-length transcripts and their structures on chromosome 19.
EOF
}

for x in $deliveries; do
    "$x"
    echo "OK $x: $(du -sh "$ROOT/$x" | cut -f1)"
done
