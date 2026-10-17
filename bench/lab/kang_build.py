"""Build the Kang 2018 lab delivery from GEO GSE96583 (batch 2), inside the pinned Scanpy/CellTypist container.

Usage: kang_build.py <source_dir> <delivery_dir> <truth_dir>
The delivery holds what a facility would hand over: raw counts, condition, donor (genotype demultiplexing) and
the demultiplexer's singlet/doublet calls. The published cell types are the truth and go to <truth_dir> only.
"""
import os
import sys

import anndata as ad
import numpy as np
import pandas as pd
import scipy.io
import scipy.sparse as sp

src, delivery, truth = sys.argv[1:4]
genes = pd.read_csv(os.path.join(src, "GSE96583_batch2.genes.tsv.gz"), sep="\t", header=None, names=["gene_ids", "symbol"])
meta = pd.read_csv(os.path.join(src, "GSE96583_batch2.total.tsne.df.tsv.gz"), sep="\t")
meta["barcode"] = [i.replace("-11", "-1") for i in meta.index]  # R made duplicated stim barcodes unique with "1"
meta = meta.set_index(["barcode", "stim"])

parts = []
for gsm, condition in (("GSM2560248_2.1", "ctrl"), ("GSM2560249_2.2", "stim")):
    counts = sp.csr_matrix(scipy.io.mmread(os.path.join(src, f"{gsm}.mtx.gz")).T.astype(np.float32))
    barcodes = pd.read_csv(os.path.join(src, f"{gsm.split('_')[0]}_barcodes.tsv.gz"), header=None)[0].tolist()
    m = meta.loc[[(b, condition) for b in barcodes]]
    obs = pd.DataFrame({"barcode": barcodes, "condition": condition, "donor": m["ind"].astype(str).values,
                        "demuxlet_call": m["multiplets"].values},
                       index=[f"{b}_{condition}" for b in barcodes])
    a = ad.AnnData(X=counts, obs=obs)
    a.obs["published_cell_type"] = m["cell"].values
    parts.append(a)

adata = ad.concat(parts, join="outer")
adata.var_names = pd.Index(genes["symbol"].astype(str)).copy()
adata.var["gene_ids"] = genes["gene_ids"].values
adata.var_names_make_unique()

os.makedirs(truth, exist_ok=True)
adata.obs[["condition", "donor", "demuxlet_call", "published_cell_type"]].to_csv(os.path.join(truth, "cells.tsv"), sep="\t")
del adata.obs["published_cell_type"]
os.makedirs(delivery, exist_ok=True)
adata.write_h5ad(os.path.join(delivery, "kang2018_pbmc_ctrl_ifnb.h5ad"), compression="gzip")
print(adata)
print(adata.obs.groupby(["condition", "donor"], observed=True).size().unstack(0))
