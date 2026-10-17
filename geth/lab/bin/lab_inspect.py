#!/usr/bin/env python3
"""Geth lab (EXPERIMENTAL): describe a single-cell count matrix for the designer agent.

Usage: lab_inspect.py <matrix.h5ad>
Prints the matrix size, every metadata column (values and counts), how cells split across the categorical
columns, and per-cell QC distributions (counts, genes, mitochondrial percentage), overall and per group.
Runs inside the pinned Scanpy/CellTypist container.
"""
import os
import sys
import tempfile

_cache = os.environ.get("GETH_CACHE") or tempfile.mkdtemp(prefix="geth_lab_")
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(_cache, "numba"))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(_cache, "mpl"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scanpy as sc  # noqa: E402


def quantiles(values):
    return " ".join(f"q{p}={np.percentile(values, p):.4g}" for p in (1, 5, 25, 50, 75, 95, 99))


adata = sc.read_h5ad(sys.argv[1])
if "gene_symbol" in adata.var:  # nf-core/scrnaseq matrices are named by Ensembl ID, with symbols in var
    adata.var_names = [str(s) for s in adata.var["gene_symbol"]]
    adata.var_names_make_unique()
print(f"Matrix: {adata.n_obs} cells x {adata.n_vars} genes")
print(f"Values: {'integer counts' if np.allclose(adata.X[:200].toarray() % 1, 0) else 'not integers (normalised?)'}")
print("\nCell metadata (obs):")
categorical = []
for col in adata.obs.columns:
    values = adata.obs[col].astype(str)
    counts = values.value_counts()
    if len(counts) <= 30:
        categorical.append(col)
        print(f"- {col}: {len(counts)} values: " + ", ".join(f"{k} ({v})" for k, v in counts.items()))
    else:
        print(f"- {col}: {len(counts)} distinct values (e.g. {', '.join(counts.index[:3])})")
if len(categorical) >= 2:
    a, b = categorical[:2]
    print(f"\nCells per {a} x {b}:")
    print(pd.crosstab(adata.obs[a].astype(str), adata.obs[b].astype(str)).to_string())

adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], inplace=True, percent_top=None, log1p=False)
print(f"\nMitochondrial genes found: {int(adata.var['mt'].sum())}")
print("\nPer-cell QC, all cells:")
for key, label in (("total_counts", "UMIs per cell"), ("n_genes_by_counts", "genes per cell"), ("pct_counts_mt", "% mitochondrial")):
    print(f"- {label}: {quantiles(adata.obs[key])}")
for col in categorical[:2]:
    print(f"\nMedian per {col}:")
    print(adata.obs.groupby(col, observed=True)[["total_counts", "n_genes_by_counts", "pct_counts_mt"]].median().round(2).to_string())
