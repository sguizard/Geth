#!/usr/bin/env python3
"""Reference step: CellTypist (Immune_All_Low) with majority voting over the clusters."""
import sys

import celltypist
import scanpy as sc

adata = sc.read_h5ad(sys.argv[1])
model = celltypist.models.Model.load(model="models/Immune_All_Low.pkl")
pred = celltypist.annotate(adata, model=model, majority_voting=True, over_clustering="leiden")
adata.obs["cell_type"] = pred.predicted_labels["majority_voting"].astype(str).values
adata.obs["cell_type"].value_counts().rename_axis("cell_type").reset_index().to_csv("cell_types.tsv", sep="\t", index=False)
print(adata.obs["cell_type"].value_counts().head(15).to_string())
adata.write_h5ad(sys.argv[2])
