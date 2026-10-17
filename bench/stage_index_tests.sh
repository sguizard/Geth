#!/usr/bin/env bash
# Small deliveries cut from the public real-size data (bench/stage_public.sh) to test index reuse quickly:
#   airway_index_test: 2 airway runs (untreated, dexamethasone), first 200,000 read pairs each
#   pbmc_index_test:   PBMC 1k v3, lane 1, first 300,000 reads
# They have no reference of their own: the planner must take GRCh38 and its STAR index from the catalogue.
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"

src=$GETH_DATA_ROOT/data
dst=$GETH_DATA_ROOT/testdata
head_fastq() {  # head_fastq <in.fastq.gz> <reads> <out.fastq.gz>
    [ -s "$3" ] && return 0
    mkdir -p "$(dirname "$3")"
    { zcat "$1" || true; } | head -n $(( $2 * 4 )) | gzip > "$3.part" && mv "$3.part" "$3"
}

a=$dst/airway_index_test
for r in SRR1039508 SRR1039509; do
    for m in 1 2; do head_fastq "$src/airway_GSE52778/fastq/${r}_$m.fastq.gz" 200000 "$a/fastq/${r}_$m.fastq.gz"; done
done
printf 'run_accession\tsample_title\tlibrary_layout\nSRR1039508\tN61311_untreated\tPAIRED\nSRR1039509\tN61311_Dex\tPAIRED\n' > "$a/metadata.tsv"
cat > "$a/README.txt" <<'EOF'
Himes et al. 2014 (GEO GSE52778): primary human airway smooth muscle cells of donor N61311, untreated or
treated with 1 uM dexamethasone for 18 hours. Illumina HiSeq 2000, paired-end 63 bp reads.
Test subset: the first 200,000 read pairs of each run.
EOF

p=$dst/pbmc_index_test
for r in R1 R2 I1; do
    head_fastq "$src/pbmc_1k_v3/fastq/pbmc_1k_v3_S1_L001_${r}_001.fastq.gz" 300000 "$p/fastq/pbmc_1k_v3_S1_L001_${r}_001.fastq.gz"
done
cat > "$p/README.txt" <<'EOF'
10x Genomics public dataset "pbmc_1k_v3": peripheral blood mononuclear cells (PBMCs) from a healthy human
donor, about 1,000 cells. Chromium Single Cell 3' v3 chemistry, NovaSeq.
Test subset: the first 300,000 reads of lane 1 (a few hundred reads per cell: too few for real analysis).
EOF
du -sh "$a" "$p"
