---
name: sc-build-lab
description: How to implement a single-cell downstream analysis as sandboxed Python step scripts in Geth's lab image (scanpy 1.11, anndata 0.13, celltypist 1.7, pydeseq2 0.5, harmonypy 0.0.10, scikit-image, scikit-misc, pandas 3, numpy 2), with working code for QC, normalisation, Harmony, clustering, CellTypist, markers and pseudobulk DESeq2.
---

# Implementing a single-cell analysis as step scripts (EXPERIMENTAL lab skill)

## The step contract
- `python3 step.py <input.h5ad> <output.h5ad>`: read `sys.argv[1]`, write the AnnData for the next step to
  `sys.argv[2]`, even when the step only writes tables (pass the data on unchanged).
- No network. Only the working folder is writable; write tables (`.tsv`, tab separated, `index=False`) and
  figures (`.png`, matplotlib's Agg backend is set) there with relative names. Models: `./models/*.pkl`.
- Allowed imports: scanpy, anndata, celltypist, pydeseq2, harmonypy, numpy, pandas, scipy, sklearn,
  statsmodels, matplotlib, seaborn, and plain standard modules (json, re, os, math...). No subprocess, no
  shell, no absolute paths.
- Print what each step did (cells kept, genes, clusters, labels, tests run): the test output is how you and the
  reviewer check it.

## Keep raw counts
- First step: `adata.layers["counts"] = adata.X.copy()` before any normalisation; never overwrite it.
- Subsetting cells keeps layers; `sc.pp.filter_genes` keeps them in step.

## QC
- Mitochondrial genes: `adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")`; if none, the
  species names them without the prefix (chicken): `adata.var_names.str.upper().isin(["ND1", "ND2", "ND3", "ND4",
  "ND4L", "ND5", "ND6", "COX1", "COX2", "COX3", "ATP6", "ATP8", "CYTB"])`. Then
  `sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)` gives
  `total_counts`, `n_genes_by_counts`, `pct_counts_mt`. Skip mito filtering only if neither finds a gene.
- Gene names: count matrices from nf-core/scrnaseq may hold gene ids in `var_names` and symbols in
  `var["gene_symbol"]`: use the symbols (`adata.var_names = adata.var["gene_symbol"].astype(str)`, then
  `adata.var_names_make_unique()`); genes without a symbol keep their id.
- MAD thresholds per sample: `med = s.median(); mad = (s - med).abs().median()`; keep `abs(s - med) <= 5 * mad`
  (counts, genes; log scale is common) and `pct_counts_mt <= med + 3 * mad`, computed within each sample with
  `groupby(sample_col, observed=True)`.
- Genotype doublet calls (demuxlet): keep `obs["demuxlet_call"] == "singlet"`. Otherwise
  `sc.pp.scrublet(adata, batch_key=sample_col)` (built into scanpy) on raw counts, then drop
  `obs["predicted_doublet"]`. Its automatic threshold uses scikit-image (installed). Never catch a step's
  error and carry on: a doublet rate of exactly 0 means the detector did not run.

## Normalisation, features, PCA
- `sc.pp.normalize_total(adata, target_sum=1e4)`, `sc.pp.log1p(adata)`.
- `sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat", batch_key=...)` on log data, or
  `flavor="seurat_v3", layer="counts"` on raw counts (scikit-misc is installed).
- Never subset the AnnData to the variable genes: mark them (`var["highly_variable"]`) and use
  `mask_var="highly_variable"` for PCA. Differential expression and annotation need every gene.
- `sc.pp.pca(adata, n_comps=30, mask_var="highly_variable")` (keeps every gene in the object).

## Integration, neighbours, clusters
- Harmony: `sc.external.pp.harmony_integrate(adata, key="donor")` (or another obs column) writes
  `obsm["X_pca_harmony"]`; then `sc.pp.neighbors(adata, n_neighbors=15, use_rep="X_pca_harmony")`.
- Without integration: `sc.pp.neighbors(adata, n_neighbors=15, n_pcs=30)`.
- `sc.tl.leiden(adata, resolution=1.0, flavor="igraph", n_iterations=2, directed=False, key_added="leiden")`.
- `sc.tl.umap(adata)` only if a figure needs it (`sc.pl.umap(..., show=False)`, then `plt.savefig`).

## Annotation (CellTypist: human and mouse only)
- For another species (chicken ...) do not use the models: name each cluster from its top markers and the
  scientist's known markers (print their mean expression and share of expressing cells per cluster), and write
  `obs["cell_type"]` from that, "uncertain" where the markers do not point to one cell type.
- Input must be log1p of counts normalised to 10,000 per cell, with gene symbols: the normalised `adata.X`
  above is right (keep all genes, not only the variable ones).
- `model = celltypist.models.Model.load(model="models/Immune_All_Low.pkl")`
  `pred = celltypist.annotate(adata, model=model, majority_voting=True, over_clustering="leiden")`
  `adata.obs["cell_type"] = pred.predicted_labels["majority_voting"].astype(str).values`
- Check the labels against canonical markers (e.g. CD3E T, CD8A CD8 T, MS4A1 B, NKG7/GNLY NK, CD14/LYZ classical
  monocytes, FCGR3A non-classical monocytes, FCER1A/CST3 dendritic cells, PPBP platelets): print the mean
  expression of these markers per label, and say where labels and markers disagree.
- Interferon-stimulated monocytes can be labelled macrophages by CellTypist: the markers tell you.

## Markers of clusters or cell types
- `sc.tl.rank_genes_groups(adata, "cell_type", method="wilcoxon")`, then
  `df = sc.get.rank_genes_groups_df(adata, group=None)`: columns `group, names, scores, logfoldchanges, pvals,
  pvals_adj`. Write markers.tsv with `cell_type, gene, log2fc, padj` renamed from `group, names,
  logfoldchanges, pvals_adj`. Cell-level tests are fine for markers, not for conditions.

## Conditions: pseudobulk + pyDESeq2 0.5
- Per cell type, sum raw counts (`layers["counts"]`) per sample (donor x condition); keep samples with at
  least 10 cells; keep cell types with at least 3 donors in each condition; keep genes with at least 10
  counts in total.
```python
groups = sub.obs.groupby(["donor", "condition"], observed=True).indices        # {(donor, cond): positions}
counts = pd.DataFrame(np.vstack([np.asarray(sub.layers["counts"][idx].sum(axis=0)).ravel() for idx in groups.values()]),
                      index=[f"{d}_{c}" for d, c in groups], columns=sub.var_names).round().astype(int)
meta = pd.DataFrame({"donor": [d for d, _ in groups], "condition": [c for _, c in groups]}, index=counts.index)
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats
from pydeseq2.default_inference import DefaultInference
inference = DefaultInference(n_cpus=2)
dds = DeseqDataSet(counts=counts, metadata=meta, design="~donor + condition", inference=inference, quiet=True)
dds.deseq2()
stats = DeseqStats(dds, contrast=["condition", "stim", "ctrl"], inference=inference, quiet=True)  # target, reference
stats.summary()
res = stats.results_df          # baseMean, log2FoldChange, lfcSE, stat, pvalue, padj (Benjamini-Hochberg)
```
- Write de_results.tsv with one row per cell type and gene: `cell_type, gene, log2fc, padj` (+ pvalue,
  baseMean). The contrast order is `[factor, target, reference]`: positive log2fc = higher in the target.
- Metadata columns must be strings (donor IDs like 1015 become text with `.astype(str)`).

## pandas 3 and numpy 2
- No chained assignment (`df["a"][mask] = x` does nothing): use `df.loc[mask, "a"] = x`.
- `groupby` on categoricals: pass `observed=True`. Strings default to the `str` dtype.
- Sparse matrices: `np.asarray(m.sum(axis=0)).ravel()`; never `.toarray()` the full matrix (25,000 cells x
  30,000 genes is 3 GB as float32).

## Resources for the full data
- Tens of thousands of cells: preprocessing 4 cpus, 32 GB, 60 min; CellTypist 2 cpus, 16 GB, 30 min;
  pseudobulk DESeq2 2-4 cpus, 16 GB, 60 min. The subset test time times 10 is a fair guide.
