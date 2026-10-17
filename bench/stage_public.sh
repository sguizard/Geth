#!/usr/bin/env bash
# Stage the public real-size benchmark data (about 30 GB of downloads) under $GETH_DATA_ROOT/data:
#   airway (GSE52778 / PRJNA229998): 8 untreated/dexamethasone runs, as delivered by ENA (24 GB)
#   pbmc_1k_v3: 10x Genomics public FASTQs (5 GB)
#   GRCh38 (Ensembl 116 primary assembly + GTF) and CellTypist immune models into the reference catalogue
# Run it where large downloads are allowed, e.g. as a job on a cluster's data-transfer queue. Jobs run a copy
# of the script, so tell it where Geth is:
#   SGE:   qsub -v GETH_HOME="$GETH_HOME" -cwd -j y -l h_rt=12:00:00 [-q <transfer queue>] [-P <project>] bench/stage_public.sh
#   Slurm: sbatch --time=12:00:00 [--partition=<transfer partition>] bench/stage_public.sh
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"

# --- airway: files exactly as ENA serves them (some runs include a third file of unpaired reads)
A=$GETH_DATA_ROOT/data/airway_GSE52778
mkdir -p "$A/fastq"
runs="SRR1039508 SRR1039509 SRR1039512 SRR1039513 SRR1039516 SRR1039517 SRR1039520 SRR1039521"
curl -fsSL "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJNA229998&result=read_run&fields=run_accession,sample_title,library_layout,read_count,fastq_md5,fastq_ftp&format=tsv" > "$A/.ena_filereport.tsv"
{
    printf 'run_accession\tsample_title\tlibrary_layout\tread_count\n'
    for r in $runs; do awk -F'\t' -v r="$r" '$1 == r {print $1"\t"$2"\t"$3"\t"$4}' "$A/.ena_filereport.tsv"; done
} > "$A/metadata.tsv"
for r in $runs; do
    line=$(awk -F'\t' -v r="$r" '$1 == r' "$A/.ena_filereport.tsv")
    IFS=';' read -r -a md5s <<< "$(cut -f5 <<< "$line")"
    IFS=';' read -r -a urls <<< "$(cut -f6 <<< "$line")"
    for i in "${!urls[@]}"; do
        f=$A/fastq/$(basename "${urls[$i]}")
        if [ ! -s "$f" ] || [ "$(md5sum < "$f" | cut -d' ' -f1)" != "${md5s[$i]}" ]; then
            curl -fsSL --retry 3 -o "$f.part" "https://${urls[$i]}"
            [ "$(md5sum < "$f.part" | cut -d' ' -f1)" = "${md5s[$i]}" ] || { echo "md5 mismatch: $f" >&2; exit 1; }
            mv "$f.part" "$f"
        fi
        echo "OK $(basename "$f")"
    done
done
rm -f "$A/.ena_filereport.tsv"
cat > "$A/README.txt" <<'EOF'
Himes et al. 2014, PLoS One (GEO GSE52778, ENA PRJNA229998).
Primary human airway smooth muscle cells from four donors, untreated or treated with
1 uM dexamethasone for 18 hours. Illumina HiSeq 2000, paired-end 63 bp reads.
FASTQ files as downloaded from ENA.
EOF

# --- PBMC 1k v3 (10x Genomics public dataset)
P=$GETH_DATA_ROOT/data/pbmc_1k_v3
mkdir -p "$P"
if [ ! -d "$P/fastq" ]; then
    curl -fsSL --retry 3 -o "$P/pbmc_1k_v3_fastqs.tar" https://cf.10xgenomics.com/samples/cell-exp/3.0.0/pbmc_1k_v3/pbmc_1k_v3_fastqs.tar
    mkdir -p "$P/fastq.tmp"
    tar -xf "$P/pbmc_1k_v3_fastqs.tar" -C "$P/fastq.tmp" --strip-components=1
    mv "$P/fastq.tmp" "$P/fastq"
    rm -f "$P/pbmc_1k_v3_fastqs.tar"
fi
cat > "$P/README.txt" <<'EOF'
10x Genomics public dataset "pbmc_1k_v3": peripheral blood mononuclear cells (PBMCs) from a
healthy human donor, about 1,000 cells. Chromium Single Cell 3' v3 chemistry, NovaSeq.
Source: https://www.10xgenomics.com/datasets (pbmc_1k_v3, Cell Ranger 3.0.0)
EOF
ls -la "$P/fastq"

# --- GRCh38 reference and CellTypist immune models into the catalogue
"$GETH_HOME/geth/references/stage_ensembl.sh" homo_sapiens GRCh38 116 "Homo sapiens (human)"
"$GETH_HOME/geth/references/stage_celltypist.sh" celltypist_immune_v2 "Homo sapiens (human)" "human immune cells" \
    Immune_All_Low Immune_All_High
du -sh "$A" "$P" "$GETH_REFERENCES"/*
