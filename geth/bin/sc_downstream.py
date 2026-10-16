#!/usr/bin/env python3
"""Geth single-cell downstream toolbox: executes an analysis design chosen from a fixed menu.

  sc_downstream.py inspect <matrix.h5ad>
      Print per-cell QC distributions (and MAD-based outlier counts) to help design QC thresholds.
  sc_downstream.py run <matrix.h5ad> <design.json> <outdir>
      QC filters -> doublets -> normalisation -> HVG -> PCA -> neighbours -> UMAP -> Leiden -> markers ->
      CellTypist. Writes processed.h5ad, diagnostics.json, figures, and prints a diagnostics summary.

Agents never run code here: they only choose values from the menu (validated by geth_checks.py).
Runs inside the pinned CellTypist container (scanpy, scrublet via scanpy, celltypist, leidenalg).
"""
import json
import os
import sys
import tempfile

# Caches must be writable and must not land in the home directory.
_cache = os.environ.get("GETH_CACHE") or tempfile.mkdtemp(prefix="geth_sc_")
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(_cache, "numba"))
os.environ.setdefault("MPLCONFIGDIR", os.path.join(_cache, "mpl"))

import warnings  # noqa: E402

warnings.filterwarnings("ignore")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import numpy as np  # noqa: E402
import scanpy as sc  # noqa: E402

DEFAULTS = {
    "qc.min_genes": 200, "qc.max_genes": None, "qc.min_counts": None, "qc.max_counts": None,
    "qc.max_pct_mt": 20.0, "qc.min_cells_per_gene": 3,
    "doublets.method": "scrublet", "doublets.expected_rate": 0.06, "doublets.threshold": 0.25,
    "normalize.target_sum": 10000, "hvg.n_top_genes": 2000, "hvg.flavor": "seurat", "scale": True,
    "pca.n_comps": 50, "neighbors.n_neighbors": 15, "neighbors.n_pcs": 30,
    "leiden.resolutions": [0.5, 1.0], "leiden.chosen": 1.0,
    "markers.method": "wilcoxon", "markers.n_genes": 10, "markers.panel": [],
    "annotation.model": None, "annotation.majority_voting": True,
}


def load(path):
    adata = sc.read_h5ad(path)
    symbols = adata.var["gene_symbol"] if "gene_symbol" in adata.var else adata.var_names
    adata.var["gene_id"] = adata.var_names
    adata.var_names = [str(s) for s in symbols]
    adata.var_names_make_unique()
    adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
    adata.var["ribo"] = adata.var_names.str.upper().str.match(r"^RP[SL]")
    adata.var["hb"] = adata.var_names.str.upper().str.match(r"^HB(?!P)")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt", "ribo", "hb"], inplace=True, log1p=True, percent_top=None)
    return adata


def mad_outliers(values, nmads):
    med = np.median(values)
    mad = np.median(np.abs(values - med))
    return (values < med - nmads * mad) | (values > med + nmads * mad), med, mad


def q(values):
    return {f"q{p}": round(float(np.percentile(values, p)), 2) for p in (1, 5, 25, 50, 75, 95, 99)}


def inspect(path):
    a = load(path)
    obs = a.obs
    out = {"cells": int(a.n_obs), "genes": int(a.n_vars), "mito_genes": int(a.var["mt"].sum()),
           "genes_in_3plus_cells": int((np.asarray((a.X > 0).sum(axis=0)).ravel() >= 3).sum())}
    for col in ("total_counts", "n_genes_by_counts", "pct_counts_mt", "pct_counts_ribo", "pct_counts_hb"):
        out[col] = q(obs[col].to_numpy())
    out_counts, _, _ = mad_outliers(obs["log1p_total_counts"].to_numpy(), 5)
    out_genes, _, _ = mad_outliers(obs["log1p_n_genes_by_counts"].to_numpy(), 5)
    mt = obs["pct_counts_mt"].to_numpy()
    out_mt_mad, mt_med, mt_mad = mad_outliers(mt, 3)
    out["mad_outliers"] = {"log_total_counts_5MAD": int(out_counts.sum()), "log_n_genes_5MAD": int(out_genes.sum()),
                           "pct_mt_above_median_plus_3MAD": int(((mt > mt_med + 3 * mt_mad)).sum()),
                           "pct_mt_median_plus_3MAD_value": round(float(mt_med + 3 * mt_mad), 2)}
    out["cells_above_pct_mt"] = {str(t): int((mt > t).sum()) for t in (5, 10, 15, 20, 25)}
    out["cells_below_n_genes"] = {str(t): int((obs["n_genes_by_counts"] < t).sum()) for t in (100, 200, 300, 500)}
    lines = [f"Matrix: {path}", f"Cells: {out['cells']:,}  Genes: {out['genes']:,}  (expressed in >= 3 cells: "
             f"{out['genes_in_3plus_cells']:,}; mitochondrial genes: {out['mito_genes']})", "",
             "| Per-cell metric | 1% | 5% | 25% | median | 75% | 95% | 99% |", "|---|---|---|---|---|---|---|---|"]
    for col in ("total_counts", "n_genes_by_counts", "pct_counts_mt", "pct_counts_ribo", "pct_counts_hb"):
        v = out[col]
        lines.append(f"| {col} | " + " | ".join(f"{v[k]:g}" for k in ("q1", "q5", "q25", "q50", "q75", "q95", "q99")) + " |")
    lines += ["", "MAD-based outliers: " + "; ".join(f"{k}={v}" for k, v in out["mad_outliers"].items()),
              "Cells above pct_counts_mt threshold: " + "; ".join(f">{k}%: {v}" for k, v in out["cells_above_pct_mt"].items()),
              "Cells below n_genes threshold: " + "; ".join(f"<{k}: {v}" for k, v in out["cells_below_n_genes"].items())]
    print("\n".join(lines))


def run(path, design_path, outdir):
    d = dict(DEFAULTS)
    d.update(json.load(open(design_path)))
    os.makedirs(outdir, exist_ok=True)
    sc.settings.figdir = outdir
    a = load(path)
    diag = {"design": d, "input": path, "cells_input": int(a.n_obs), "qc_steps": []}

    def step(name, mask):
        before = a.n_obs
        diag["qc_steps"].append({"filter": name, "removed": int(before - mask.sum()), "kept": int(mask.sum())})
        return a[mask].copy()

    if d["qc.min_genes"]:
        a = step(f"n_genes >= {d['qc.min_genes']}", (a.obs["n_genes_by_counts"] >= d["qc.min_genes"]).to_numpy())
    if d["qc.max_genes"]:
        a = step(f"n_genes <= {d['qc.max_genes']}", (a.obs["n_genes_by_counts"] <= d["qc.max_genes"]).to_numpy())
    if d["qc.min_counts"]:
        a = step(f"total_counts >= {d['qc.min_counts']}", (a.obs["total_counts"] >= d["qc.min_counts"]).to_numpy())
    if d["qc.max_counts"]:
        a = step(f"total_counts <= {d['qc.max_counts']}", (a.obs["total_counts"] <= d["qc.max_counts"]).to_numpy())
    if d["qc.max_pct_mt"] is not None:
        a = step(f"pct_counts_mt <= {d['qc.max_pct_mt']}", (a.obs["pct_counts_mt"] <= d["qc.max_pct_mt"]).to_numpy())
    if d["qc.min_cells_per_gene"]:
        sc.pp.filter_genes(a, min_cells=int(d["qc.min_cells_per_gene"]))
    a.layers["counts"] = a.X.copy()

    if d["doublets.method"] == "scrublet":
        # Explicit score threshold: Scrublet's automatic one needs scikit-image (absent from the container).
        sc.pp.scrublet(a, expected_doublet_rate=float(d["doublets.expected_rate"]),
                       threshold=float(d["doublets.threshold"]), random_state=0)
        doublets = a.obs["predicted_doublet"].to_numpy().astype(bool)
        diag["doublets"] = {"detected": int(doublets.sum()), "rate": round(float(doublets.mean()), 4),
                            "score_median": round(float(a.obs["doublet_score"].median()), 3)}
        a = step("scrublet singlets", ~doublets)
    else:
        diag["doublets"] = {"detected": 0, "rate": 0.0, "note": "doublet detection off"}
    diag["cells_kept"] = int(a.n_obs)
    diag["cells_kept_fraction"] = round(a.n_obs / diag["cells_input"], 4)
    diag["genes_kept"] = int(a.n_vars)

    sc.pp.normalize_total(a, target_sum=float(d["normalize.target_sum"]))
    sc.pp.log1p(a)
    a.raw = a
    n_hvg = int(min(d["hvg.n_top_genes"], a.n_vars - 1))
    # seurat_v3 needs scikit-misc, absent from the container: the menu offers seurat and cell_ranger.
    sc.pp.highly_variable_genes(a, n_top_genes=n_hvg, flavor=d["hvg.flavor"])
    b = a[:, a.var["highly_variable"]].copy()
    if d["scale"]:
        sc.pp.scale(b, max_value=10)
    n_comps = int(min(d["pca.n_comps"], b.n_vars - 1, b.n_obs - 1))
    sc.pp.pca(b, n_comps=n_comps, random_state=0)
    a.obsm["X_pca"] = b.obsm["X_pca"]
    diag["pca_variance_ratio_first10"] = [round(float(x), 4) for x in b.uns["pca"]["variance_ratio"][:10]]
    sc.pp.neighbors(a, n_neighbors=int(d["neighbors.n_neighbors"]), n_pcs=int(min(d["neighbors.n_pcs"], n_comps)), random_state=0)
    sc.tl.umap(a, random_state=0)
    diag["leiden"] = {}
    for res in d["leiden.resolutions"]:
        key = f"leiden_{res}"
        sc.tl.leiden(a, resolution=float(res), key_added=key, random_state=0, flavor="igraph", n_iterations=2)
        diag["leiden"][str(res)] = {"clusters": int(a.obs[key].nunique()),
                                    "smallest_cluster": int(a.obs[key].value_counts().min())}
    chosen = f"leiden_{d['leiden.chosen']}"
    a.obs["cluster"] = a.obs[chosen].astype(str)

    sc.tl.rank_genes_groups(a, "cluster", method=d["markers.method"], use_raw=True)
    rgg = a.uns["rank_genes_groups"]
    panel = [g for g in d["markers.panel"] if g in a.raw.var_names]
    diag["markers_panel_missing"] = [g for g in d["markers.panel"] if g not in a.raw.var_names]

    # CellTypist on log1p(10k)-normalised counts, as the models expect.
    import anndata
    import celltypist
    ct = anndata.AnnData(X=a.layers["counts"].copy(), obs=a.obs[["cluster"]].copy(), var=a.var[[]].copy())
    sc.pp.normalize_total(ct, target_sum=1e4)
    sc.pp.log1p(ct)
    pred = celltypist.annotate(ct, model=d["annotation.model"], majority_voting=bool(d["annotation.majority_voting"]),
                               over_clustering="cluster")
    labels = pred.predicted_labels
    a.obs["celltypist_label"] = labels["predicted_labels"].astype(str).values
    if "majority_voting" in labels:
        a.obs["celltypist_majority"] = labels["majority_voting"].astype(str).values

    clusters = []
    agree_cells = 0
    for cl in sorted(a.obs["cluster"].unique(), key=lambda x: int(x)):
        cells = a.obs["cluster"] == cl
        sub = a.obs.loc[cells, "celltypist_label"]
        top_label = sub.value_counts().index[0]
        agreement = float((sub == top_label).mean())
        agree_cells += int((sub == top_label).sum())
        top = [{"gene": str(rgg["names"][cl][i]), "log2fc": round(float(rgg["logfoldchanges"][cl][i]), 2),
                "padj": float(f"{rgg['pvals_adj'][cl][i]:.2g}")} for i in range(int(d["markers.n_genes"]))]
        expr = a.raw[cells, panel].X if panel else None
        panel_stats = {}
        for j, g in enumerate(panel):
            col = expr[:, j].toarray().ravel() if hasattr(expr, "toarray") else np.asarray(expr[:, j]).ravel()
            panel_stats[g] = {"mean": round(float(col.mean()), 2), "pct_expressing": round(float((col > 0).mean() * 100), 1)}
        clusters.append({"cluster": cl, "cells": int(cells.sum()), "top_markers": top, "panel": panel_stats,
                         "celltypist_label": top_label, "celltypist_agreement": round(agreement, 3),
                         "pct_counts_mt_median": round(float(a.obs.loc[cells, "pct_counts_mt"].median()), 2),
                         "n_genes_median": int(a.obs.loc[cells, "n_genes_by_counts"].median())})
    diag["clusters"] = clusters
    diag["celltypist_cluster_agreement"] = round(agree_cells / a.n_obs, 4)
    comp = a.obs["celltypist_label"].value_counts()
    diag["celltypist_composition"] = {str(k): int(v) for k, v in comp.items()}

    sc.pl.umap(a, color=["cluster", "celltypist_label"], save="_clusters.png", show=False, legend_loc="on data", legend_fontsize=6)
    sc.pl.violin(a, ["n_genes_by_counts", "total_counts", "pct_counts_mt"], jitter=0.3, multi_panel=True, save="_qc.png", show=False)
    a.write_h5ad(os.path.join(outdir, "processed.h5ad"), compression="gzip")
    json.dump(diag, open(os.path.join(outdir, "diagnostics.json"), "w"), indent=2)
    print(summary(diag))


def summary(diag):
    lines = [f"Cells: {diag['cells_input']:,} in, {diag['cells_kept']:,} kept ({diag['cells_kept_fraction'] * 100:.1f}%); "
             f"genes kept: {diag['genes_kept']:,}", "", "| QC step | removed | kept |", "|---|---|---|"]
    lines += [f"| {s['filter']} | {s['removed']:,} | {s['kept']:,} |" for s in diag["qc_steps"]]
    dbl = diag["doublets"]
    lines += ["", f"Doublets: {dbl['detected']:,} detected (rate {dbl['rate'] * 100:.1f}%)",
              "Leiden: " + "; ".join(f"resolution {r}: {v['clusters']} clusters (smallest {v['smallest_cluster']} cells)"
                                     for r, v in diag["leiden"].items()),
              f"Chosen resolution: {diag['design']['leiden.chosen']}",
              f"CellTypist ({os.path.basename(str(diag['design']['annotation.model']))}): "
              f"{diag['celltypist_cluster_agreement'] * 100:.1f}% of cells carry their cluster's majority label", ""]
    panel = list(diag["clusters"][0]["panel"]) if diag["clusters"] else []
    lines += ["| Cluster | cells | CellTypist majority label | agreement | top markers | " + " | ".join(panel) + " |",
              "|---|---|---|---|---|" + "---|" * len(panel)]
    for c in diag["clusters"]:
        lines.append(f"| {c['cluster']} | {c['cells']:,} | {c['celltypist_label']} | {c['celltypist_agreement'] * 100:.0f}% | "
                     + ", ".join(m["gene"] for m in c["top_markers"][:5]) + " | "
                     + " | ".join(f"{c['panel'][g]['mean']:.2f} ({c['panel'][g]['pct_expressing']:.0f}%)" for g in panel) + " |")
    if panel:
        lines.append("Panel cells: mean log-normalised expression (% of cells expressing).")
    if diag.get("markers_panel_missing"):
        lines.append("Panel genes not found in the matrix: " + ", ".join(diag["markers_panel_missing"]))
    return "\n".join(lines)


def main(argv):
    if len(argv) >= 3 and argv[1] == "inspect":
        inspect(argv[2])
    elif len(argv) >= 5 and argv[1] == "run":
        run(argv[2], argv[3], argv[4])
    elif len(argv) >= 3 and argv[1] == "summary":
        print(summary(json.load(open(argv[2]))))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
