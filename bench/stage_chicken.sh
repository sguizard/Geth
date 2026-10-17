#!/usr/bin/env bash
# A realistic chicken germline delivery for nf-core/sarek: three birds of DDBJ study PRJDB17746 (whole-genome
# resequencing, Illumina NovaSeq 6000, paired-end 150 bp), the first 2,000,000 read pairs of each (about 0.6x
# coverage), one bird delivered on two lanes; plus the GRCg7b genome, Ensembl's known variants and the VEP cache
# in the reference catalogue. Downloads about 2.5 GB. Run it as a job where downloads are allowed:
#   SGE: qsub -v GETH_HOME="$GETH_HOME" -cwd -j y -l h_rt=06:00:00 [-q <transfer queue>] [-P <project>] bench/stage_chicken.sh
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}/env.sh"

"$GETH_HOME/geth/references/stage_ensembl.sh" gallus_gallus bGalGal1.mat.broiler.GRCg7b 116 "Gallus gallus (chicken)"
"$GETH_HOME/geth/references/stage_ensembl_variation.sh" gallus_gallus bGalGal1.mat.broiler.GRCg7b 116

d=$GETH_DATA_ROOT/testdata/chicken_wgs
mkdir -p "$d/fastq"
ena=https://ftp.sra.ebi.ac.uk/vol1/fastq

reads() {  # reads <run> <mate> <first_pair> <pairs> <out.fastq.gz>: a slice of a run's reads, streamed
    [ -s "$5" ] && return 0
    local from=$(( ($3 - 1) * 4 + 1 )) n=$(( $4 * 4 ))
    { curl -fsSL --retry 3 "$ena/${1:0:6}/$1/$1_$2.fastq.gz" || true; } | { zcat || true; } \
        | { tail -n "+$from" || true; } | head -n "$n" | gzip > "$5.part"
    [ "$(zcat "$5.part" | wc -l)" -eq "$n" ] || { echo "Short read slice for $1 mate $2" >&2; exit 1; }
    mv "$5.part" "$5"
}
for m in 1 2; do
    reads DRR539243 $m 1 2000000 "$d/fastq/red1_S1_L001_R${m}_001.fastq.gz"
    reads DRR539244 $m 1 1000000 "$d/fastq/A191_S2_L001_R${m}_001.fastq.gz"
    reads DRR539244 $m 1000001 1000000 "$d/fastq/A191_S2_L002_R${m}_001.fastq.gz"
    reads DRR539245 $m 1 2000000 "$d/fastq/bird3_S3_L001_R${m}_001.fastq.gz"
done

cat > "$d/README.txt" <<'EOF'
Whole-genome resequencing of three chickens (Gallus gallus), from DDBJ study PRJDB17746.
Illumina NovaSeq 6000, paired-end 150 bp. For this test, each bird has only its first 2,000,000 read
pairs (about 0.6x coverage). Bird A191 was sequenced on two lanes (L001 and L002).
See samples.tsv. Reference: Ensembl GRCg7b (bGalGal1.mat.broiler.GRCg7b), in the reference catalogue.
We want germline SNVs and small indels for each bird, genotyped together, and annotated.
EOF
tr '|' '\t' > "$d/samples.tsv" <<'EOF'
bird|archive run|description
red1|DRR539243|OSM breed, male
A191|DRR539244|White Leghorn (WL-T), female; two lanes
bird3|DRR539245|no description in the archive
EOF
du -sh "$d"
