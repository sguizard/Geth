#!/usr/bin/env bash
# Lab benchmark (phase 11, experimental): Kang et al. 2018, Nat Biotechnol 36:89 (GEO GSE96583, batch 2).
# PBMCs of 8 lupus patients, pooled, control and stimulated with IFN-beta for 6 h; 10x Chromium; cells assigned
# to donors by genotype (demuxlet). About 80 MB from GEO. The delivery ($GETH_DATA_ROOT/testdata/lab_kang2018)
# holds raw counts and per-cell condition, donor and demuxlet call; the published cell types (the truth for
# scoring) go to $GETH_WORK_ROOT/lab_truth/kang2018, outside the data area the agents can read.
set -euo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"
here=$(cd "$(dirname "$0")" && pwd)
src=$GETH_WORK_ROOT/lab_truth/kang2018/source
delivery=$GETH_DATA_ROOT/testdata/lab_kang2018
geo=https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl
mkdir -p "$src"
for f in GSE96583_RAW.tar GSE96583_batch2.genes.tsv.gz GSE96583_batch2.total.tsne.df.tsv.gz; do
    [ -s "$src/$f" ] || { curl -fsSL --retry 3 -o "$src/$f.part" "$geo/$f" && mv "$src/$f.part" "$src/$f"; }
done
tar -xf "$src/GSE96583_RAW.tar" -C "$src" GSM2560248_2.1.mtx.gz GSM2560248_barcodes.tsv.gz \
    GSM2560249_2.2.mtx.gz GSM2560249_barcodes.tsv.gz
image=${GETH_LAB_IMAGE:-https://depot.galaxyproject.org/singularity/celltypist:1.7.1--pyhdfd78af_2}
OMP_NUM_THREADS=2 apptainer exec -B "$GETH_WORK_ROOT" -B "$here" "$image" \
    python3 "$here/kang_build.py" "$src" "$delivery" "$(dirname "$src")"
cat > "$delivery/README.txt" <<'TXT'
Single-cell RNA-seq of peripheral blood mononuclear cells (PBMCs) from 8 lupus patients (Kang et al. 2018,
GEO GSE96583, batch 2). The cells of the 8 donors were pooled, then split in two: one half left untreated
(condition "ctrl"), the other stimulated with interferon-beta for 6 hours (condition "stim"). 10x Genomics
Chromium, one lane per condition. Each cell was assigned to its donor from its genotype (demuxlet), which also
called singlets, doublets and ambiguous droplets ("demuxlet_call").
Raw UMI counts with per-cell metadata in kang2018_pbmc_ctrl_ifnb.h5ad (obs: condition, donor, demuxlet_call).
Gene symbols as variable names (Ensembl IDs in var gene_ids).
TXT
ls -la "$delivery"
