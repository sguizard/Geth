"""Geth lab (EXPERIMENTAL), trusted step run in the sandbox: 3000 random cells of the input (seed 0), every
column kept, for testing agent-written steps quickly."""
import sys

import anndata as ad
import numpy as np

a = ad.read_h5ad(sys.argv[1])
if a.n_obs > 3000:
    a = a[np.sort(np.random.default_rng(0).choice(a.n_obs, 3000, replace=False))].copy()
a.write_h5ad(sys.argv[2])
with open("genes.txt", "w") as fh:  # the gene symbols, for the results-contract check
    fh.write("\n".join(map(str, a.var_names)) + "\n")
print(f"subset: {a.n_obs} cells x {a.n_vars} genes")
