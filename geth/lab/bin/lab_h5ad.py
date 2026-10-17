#!/usr/bin/env python3
"""Geth lab (EXPERIMENTAL), trusted helper run inside the sandbox container.

  lab_h5ad.py subset <in.h5ad> <out.h5ad> [n]   n random cells (default 3000, seed 0), every column kept
  lab_h5ad.py summary <folder>                   what a step wrote: its output AnnData and the heads of its tables
"""
import os
import sys


def subset(src, dst, n=3000):
    import anndata as ad
    import numpy as np
    a = ad.read_h5ad(src)
    if a.n_obs > n:
        keep = np.sort(np.random.default_rng(0).choice(a.n_obs, n, replace=False))
        a = a[keep].copy()
    a.write_h5ad(dst)
    print(f"subset: {a.n_obs} cells x {a.n_vars} genes")


def describe(a):
    import numpy as np
    import scipy.sparse as sp
    lines = [f"AnnData: {a.n_obs} cells x {a.n_vars} genes"]
    x = a.X[: min(200, a.n_obs)]
    x = x.toarray() if sp.issparse(x) else np.asarray(x)
    lines.append(f"X: {a.X.dtype}, {'integer counts' if np.allclose(x, np.round(x)) else 'non-integer values'}, "
                 f"max {x.max():.3g}" if x.size else "X: empty")
    for name in a.layers.keys():
        if name is not None:  # recent anndata lists X itself as layers[None]
            lines.append(f"layer '{name}': {a.layers[name].dtype}")
    lines.append("raw: " + (f"{a.raw.n_vars} genes" if a.raw is not None else "none"))
    for col in a.obs.columns:
        s = a.obs[col]
        if s.dtype.kind in "biuf" and s.nunique() > 30:
            lines.append(f"obs '{col}': numeric, median {s.median():.4g}, min {s.min():.4g}, max {s.max():.4g}")
        elif s.nunique() > 0.5 * len(s) and s.nunique() > 30:
            lines.append(f"obs '{col}': {s.nunique()} distinct values (identifiers), e.g. {', '.join(map(str, s.head(3)))}")
        else:
            counts = s.astype(str).value_counts()
            shown = ", ".join(f"{k} ({v})" for k, v in counts.head(12).items())
            lines.append(f"obs '{col}': {counts.size} values: {shown}{' ...' if counts.size > 12 else ''}")
    lines.append("var columns: " + (", ".join(map(str, a.var.columns)) or "none"))
    lines.append("obsm: " + (", ".join(f"{k} {a.obsm[k].shape}" for k in a.obsm) or "none"))
    lines.append("uns: " + (", ".join(sorted(a.uns.keys())) or "none"))
    return lines


def summary(folder):
    import anndata as ad
    import pandas as pd
    out = []
    h5 = os.path.join(folder, "output.h5ad")
    if os.path.isfile(h5):
        try:
            out += ["--- output.h5ad ---"] + describe(ad.read_h5ad(h5))
        except Exception as e:
            out.append(f"--- output.h5ad could not be read: {type(e).__name__}: {e}")
    else:
        out.append("--- no output.h5ad was written")
    tables = sorted(f for f in os.listdir(folder) if f.endswith((".tsv", ".csv")))
    for name in tables[:10]:
        path = os.path.join(folder, name)
        try:
            df = pd.read_csv(path, sep="\t" if name.endswith(".tsv") else ",")
            out.append(f"--- {name}: {len(df)} rows; columns: {', '.join(map(str, df.columns))}")
            out.append(df.head(8).to_string(max_colwidth=40))
        except Exception as e:
            out.append(f"--- {name} could not be read as a table: {type(e).__name__}: {e}")
    text = "\n".join(out)
    print(text[:9000] + ("\n[summary cut at 9000 characters]" if len(text) > 9000 else ""))


if __name__ == "__main__":
    if sys.argv[1] == "subset":
        subset(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 3000)
    elif sys.argv[1] == "summary":
        summary(sys.argv[2])
    else:
        sys.exit(__doc__)
