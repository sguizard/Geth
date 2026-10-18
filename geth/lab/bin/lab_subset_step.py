"""Geth lab (EXPERIMENTAL), trusted step run in the sandbox: 3000 random cells of the input (seed 0), every
column kept, for testing agent-written steps quickly."""
import sys

import anndata as ad
import numpy as np

a = ad.read_h5ad(sys.argv[1])
if a.n_obs > 3000:
    a = a[np.sort(np.random.default_rng(0).choice(a.n_obs, 3000, replace=False))].copy()
a.write_h5ad(sys.argv[2])
# The gene symbols, for the results-contract check: a symbol column when the var names are IDs (Ensembl).
column = next((c for c in ("gene_symbol", "gene_symbols", "feature_name", "gene_name") if c in a.var), None)
symbols = a.var[column] if column and a.var_names.str.startswith("ENS").mean() > 0.5 else a.var_names
with open("genes.txt", "w") as fh:
    fh.write("\n".join(map(str, symbols)) + "\n")
print(f"subset: {a.n_obs} cells x {a.n_vars} genes")
