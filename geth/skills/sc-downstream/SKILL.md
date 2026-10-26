---
name: sc-downstream
description: How to design a single-cell RNA-seq downstream analysis (QC filtering, doublets, normalisation, HVGs, PCA, neighbours, Leiden clustering, markers, CellTypist annotation) for Geth's sc_downstream toolbox, following single-cell best practices; and when a revision after seeing the diagnostics is justified.
---

# Designing a single-cell downstream analysis (Geth toolbox `sc_downstream`)

Use this for a **follow-up** of a finished nf-core/scrnaseq run. Pipeline name in the plan: `sc_downstream`.
The design is a list of `key=value` lines from a fixed menu; Geth runs it, nothing else.

## Input (the plan's samplesheet)
`sample,h5ad` with one row: the sample name and the absolute path of its **filtered** count matrix from the
upstream run. Prefer the CellBender-corrected matrix (`*cellbender*filter*.h5ad`) when the upstream ran
CellBender; otherwise `star/mtx_conversions/<sample>/<sample>_filtered_matrix.h5ad`. List the upstream
`results/` folder to find it. Call **SC_INSPECT** on it before choosing QC thresholds.

**Multiplexed upstream (Cell Ranger multi: OCM, CellPlex, Flex):** never use a sample's own CellBender
matrix (`cellrangermulti/mtx_conversions/<sample>/<sample>_cellbender_filter_matrix.h5ad`): it is not valid,
because a sample's raw matrix lacks the library's empty droplets. Use the sample's Cell Ranger matrix
(`<sample>_filtered_matrix.h5ad`), and choose QC thresholds that remove empty droplets: the upstream
report's "Cells per sample after CellBender" table says how many real cells to expect.

## Menu (keys, meaning, good starting values)
- QC (per cell): `qc.min_genes` (typically 200–500), optional `qc.max_genes` (doublet-like cells, e.g. the
  99th percentile), optional `qc.min_counts`/`qc.max_counts`, `qc.max_pct_mt` (mitochondrial %: fresh PBMC
  ~10–20; choose from the SC_INSPECT distribution, e.g. median + 3 MAD), `qc.min_cells_per_gene` (3).
  Prefer data-driven thresholds (MAD-based outliers from SC_INSPECT) over fixed textbook values; do not remove
  more than ~10–15% of cells unless the data are clearly poor.
- Doublets: `doublets.method=scrublet`; `doublets.expected_rate` ≈ 0.008 per 1,000 recovered 10x cells
  (e.g. 0.008 for 1k cells, 0.04 for 5k); `doublets.threshold=auto` (recommended: Scrublet's bimodal minimum of
  simulated doublet scores) or a fixed score cut-off (lower = stricter).
- Normalisation: `normalize.target_sum=10000` (log1p applied).
- Features: `hvg.n_top_genes` (2000–3000), `hvg.flavor` (`seurat` or `cell_ranger`).
- Embedding: `pca.n_comps` (30–50), `neighbors.n_neighbors` (10–30), `neighbors.n_pcs` (≤ pca.n_comps, 20–40).
- Clustering: `leiden.resolutions` (2–4 values, e.g. `0.4,0.8,1.2`) and `leiden.chosen` (one of them). Choose
  from how many populations the tissue should contain: PBMC ≈ 8–14 clusters at a useful resolution.
- Markers: `markers.method=wilcoxon`, `markers.n_genes` (10), `markers.panel` = canonical markers of the
  populations expected in this tissue (comma-separated gene symbols), e.g. PBMC:
  `CD3E,CD4,IL7R,CD8A,NKG7,GNLY,MS4A1,CD79A,CD14,LYZ,FCGR3A,FCER1A,CLEC10A,LILRA4,PPBP`.
- Annotation: `annotation.model` = a CellTypist model from LIST_REFERENCES matching tissue **and species**
  (immune cells: `Immune_All_Low.pkl` fine-grained, `Immune_All_High.pkl` broad); `annotation.majority_voting=true`.
  CellTypist has models for human and mouse only. For another species (chicken, zebrafish ...) or a tissue no
  model covers, **leave `annotation.model` out**: the clusters are then named from their markers, so put the
  tissue's known markers in `markers.panel` (up to 40; those the scientist gives first). The plan check refuses a
  model of another species than the cells'.
- Single-nucleus data: no mitochondrial reads are expected in nuclei; a high `pct_counts_mt` means cytoplasmic
  contamination, so keep `qc.max_pct_mt` low (e.g. 5) unless the inspection shows otherwise.

## Revision (analyst, at most once)
After the first analysis you see the diagnostics, ending with FLAGS computed by Geth (cells kept < 85%,
doublet rate far from expected, clusters with CellTypist agreement < 60%, clusters under 10 cells). Address
each flag: revise, or explain why it needs no change (e.g. a small but real population such as pDCs). Revise only if a diagnostic shows a real problem, and change
only tunable keys (QC thresholds, doublet rate/threshold, HVG number, neighbours, Leiden resolutions/chosen).
Add `justification=` citing the diagnostic, for example:
- a filter removed far more cells than expected (cells kept < 85%) → relax that threshold;
- a cluster mixes two CellTypist labels (agreement < 60%) or clearly distinct canonical markers → higher resolution;
- many tiny clusters of one cell type (same CellTypist label, same markers) → lower resolution;
- doublet rate far from the expected rate → adjust `doublets.threshold`.
If the diagnostics look sound, do not revise.

## Annotating clusters (analyst's final answer)
For each cluster give `cluster=label`, using the canonical markers first and CellTypist as support (if the
design has a model); say "uncertain" when they disagree, or when the markers do not point to one cell type.
Never invent populations that neither markers nor CellTypist support.
