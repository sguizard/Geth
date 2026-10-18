#!/usr/bin/env python3
"""Reference step (written by hand, not by an agent): singlets, normalisation, features, Harmony, clusters."""
import sys

import scanpy as sc

adata = sc.read_h5ad(sys.argv[1])
adata = adata[adata.obs["demuxlet_call"] == "singlet"].copy()
sc.pp.filter_genes(adata, min_cells=10)
adata.layers["counts"] = adata.X.copy()
sc.pp.normalize_total(adata, target_sum=1e4)
sc.pp.log1p(adata)
sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat", batch_key="condition")
sc.pp.pca(adata, n_comps=30, mask_var="highly_variable")
sc.external.pp.harmony_integrate(adata, key="condition")
sc.pp.neighbors(adata, n_neighbors=15, use_rep="X_pca_harmony")
sc.tl.leiden(adata, resolution=1.0, flavor="igraph", n_iterations=2, directed=False)
print(f"{adata.n_obs} singlets, {adata.n_vars} genes, {adata.obs['leiden'].nunique()} clusters")
adata.write_h5ad(sys.argv[2])
