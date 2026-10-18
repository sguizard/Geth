#!/usr/bin/env python3
"""Reference step: pseudobulk per cell type (sum of raw counts per donor and condition), pyDESeq2
~ donor + condition, stim vs ctrl, Benjamini-Hochberg (pyDESeq2's padj)."""
import sys

import numpy as np
import pandas as pd
import scanpy as sc
from pydeseq2.dds import DeseqDataSet
from pydeseq2.default_inference import DefaultInference
from pydeseq2.ds import DeseqStats

adata = sc.read_h5ad(sys.argv[1])
inference = DefaultInference(n_cpus=2)
tables = []
for cell_type, cells in adata.obs.groupby("cell_type", observed=True):
    sub = adata[cells.index]
    groups = sub.obs.groupby(["donor", "condition"], observed=True).indices
    groups = {k: v for k, v in groups.items() if len(v) >= 10}
    donors = {d for d, c in groups if (d, "ctrl") in groups and (d, "stim") in groups}
    if len(donors) < 3:
        print(f"{cell_type}: skipped ({len(donors)} donors with 10+ cells in both conditions)")
        continue
    keys = [k for k in groups if k[0] in donors]
    counts = pd.DataFrame(np.vstack([np.asarray(sub.layers["counts"][groups[k]].sum(axis=0)).ravel() for k in keys]),
                          index=[f"{d}_{c}" for d, c in keys], columns=sub.var_names).round().astype(int)
    counts = counts.loc[:, counts.sum(axis=0) >= 10]
    meta = pd.DataFrame({"donor": [d for d, _ in keys], "condition": [c for _, c in keys]}, index=counts.index)
    dds = DeseqDataSet(counts=counts, metadata=meta, design="~donor + condition", inference=inference, quiet=True)
    dds.deseq2()
    stats = DeseqStats(dds, contrast=["condition", "stim", "ctrl"], inference=inference, quiet=True)
    stats.summary()
    res = stats.results_df.rename(columns={"log2FoldChange": "log2fc"})
    res = res.assign(cell_type=cell_type, gene=res.index)[["cell_type", "gene", "log2fc", "padj", "pvalue", "baseMean"]]
    tables.append(res)
    print(f"{cell_type}: {len(donors)} donors, {counts.shape[1]} genes, {(res['padj'] < 0.05).sum()} with padj < 0.05")
pd.concat(tables).to_csv("de_results.tsv", sep="\t", index=False)
adata.write_h5ad(sys.argv[2])
