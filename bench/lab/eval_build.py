"""Score an arm B build (EXPERIMENTAL lab): did the agent-written pipeline run, and is the biology right?

Runs inside the lab image (it needs anndata), through bench/lab/score_build.sh:
  eval_build.py <build run dir> <kang2018|pbmc1k> <truth dir> <input.h5ad>   -> one JSON line
Kang 2018: cell types against the published labels; interferon-stimulated genes up in each cell type
(pseudobulk results). PBMC 1k: the expected populations and their canonical markers, cells kept.
"""
import glob
import json
import os
import re
import sys

import anndata as ad
import pandas as pd

ISGS = ["ISG15", "IFIT1", "IFIT2", "IFIT3", "IFI6", "MX1", "OAS1", "RSAD2", "ISG20", "IFITM3", "LY6E", "IFI44L"]
# agent label -> broad class, first match wins (CellTypist calls IFN-stimulated monocytes macrophages)
CLASSES = [(r"megakaryocyte|platelet", "Megakaryocytes"), (r"dendritic|\bp?dc\d?\b|\bcdc", "Dendritic cells"),
           (r"non-classical|cd16\+ mono|fcgr3a", "FCGR3A+ Monocytes"), (r"monocyte|macrophage|\bmono", "CD14+ Monocytes"),
           (r"\bnk\b|natural killer|nk cell|\bilc", "NK cells"), (r"cd8|cytotoxic t|mait|gamma|γδ", "CD8 T cells"),
           (r"\bb cell|plasma|naive b|memory b|\bb\b", "B cells"), (r"t cell|helper|treg|cd4|tcm|tem|regulatory t", "CD4 T cells")]
PBMC_MARKERS = {"B cells": ["MS4A1", "CD79A"], "CD14+ Monocytes": ["CD14", "LYZ"], "NK cells": ["NKG7", "GNLY"],
                "CD4 T cells": ["CD3E", "IL7R"], "CD8 T cells": ["CD8A", "CD3E"], "FCGR3A+ Monocytes": ["FCGR3A", "MS4A7"],
                "Dendritic cells": ["FCER1A", "CST3"]}


def broad(label):
    for pattern, name in CLASSES:
        if re.search(pattern, str(label), re.I):
            return name
    return "other"


def read(path, default=""):
    return open(path).read() if os.path.isfile(path) else default


def table(results, name):
    paths = sorted(glob.glob(os.path.join(results, "*", name)))
    return pd.read_csv(paths[-1], sep="\t") if paths else None


def score(run, dataset, truth_dir, input_h5ad):
    results = os.path.join(run, "results")
    spec = [l.split("|")[0].strip() for l in read(os.path.join(run, "build_spec.txt")).splitlines() if l.strip()]
    log = [l.rstrip("\n").split("\t") for l in read(os.path.join(run, "build_log.tsv")).splitlines() if l.strip()]
    reviews = sorted(glob.glob(os.path.join(run, "review_*.txt")))
    s = {"run": os.path.basename(run), "dataset": dataset, "arm": read(os.path.join(run, "lab_arm.txt")).split(",")[0].strip(),
         "state": read(os.path.join(run, "build_state.txt")).strip(),
         "steps": len(spec), "rounds": len(reviews),
         "review": re.sub(r"^VERDICT: ", "", read(reviews[-1]).splitlines()[0]) if reviews else "none",
         "review_issues": sum(len(read(r).splitlines()) - 1 for r in reviews),
         "subset_tests": sum(1 for l in log if len(l) > 1 and l[1] == "test"),
         "subset_tests_failed": sum(1 for l in log if len(l) > 4 and l[1] == "test" and l[4] != "0"),
         "step_check_refusals": sum(1 for l in log if len(l) > 3 and l[1] == "write" and l[3] == "refused"),
         "spec_refusals": sum(1 for l in log if len(l) > 2 and l[1] == "spec" and l[2] == "refused")}
    final = os.path.join(results, f"{len(spec):02d}_{spec[-1]}", "output.h5ad") if spec else ""
    s["pipeline_ran"] = bool(spec) and os.path.isfile(final)
    if not s["pipeline_ran"]:
        return s
    obs = ad.read_h5ad(final, backed="r").obs
    s["has_cell_type"] = "cell_type" in obs
    if not s["has_cell_type"]:
        return s
    n_input = ad.read_h5ad(input_h5ad, backed="r").n_obs
    labels = obs["cell_type"].astype(str).map(broad)
    s["cells_kept_pct"] = round(100 * len(obs) / n_input, 1)
    s["labels"] = int(obs["cell_type"].nunique())
    if dataset == "kang2018":
        truth = pd.read_csv(os.path.join(truth_dir, "cells.tsv"), sep="\t", index_col=0)["published_cell_type"]
        common = labels.index.intersection(truth.dropna().index)
        s["annotation_agreement_pct"] = round(100 * float((labels[common] == truth[common]).mean()), 1)
        de = table(results, "de_results.tsv")
        s["de_table"] = de is not None and {"cell_type", "gene", "log2fc", "padj"} <= set(de.columns)
        if s["de_table"]:
            de = de[de["gene"].isin(ISGS)]
            up = de[(de["log2fc"] > 1) & (de["padj"] < 0.05)].groupby("cell_type")["gene"].nunique()
            tested = sorted(de["cell_type"].unique())
            s["cell_types_tested"] = len(tested)
            s["cell_types_with_isg_response"] = int((up >= 5).sum())
            s["monocytes_respond"] = any(broad(t) == "CD14+ Monocytes" and up.get(t, 0) >= 5 for t in tested)
            s["isg_direction_up"] = bool(len(de)) and float(de["log2fc"].median()) > 0
        code = " ".join(read(p) for p in glob.glob(os.path.join(run, "pipeline", "steps", "*.py")))
        s["pseudobulk_deseq2"] = bool(re.search(r"DeseqDataSet", code)) and bool(re.search(r"\.sum\(", code))
    else:
        found = labels.value_counts(normalize=True)
        s["populations_found"] = sorted(k for k, v in found.items() if k != "other" and v >= 0.01)
        s["n_populations"] = len(s["populations_found"])
        mk = table(results, "markers.tsv")
        s["markers_table"] = mk is not None and {"cell_type", "gene", "log2fc", "padj"} <= set(mk.columns)
        if s["markers_table"]:
            mk = mk[(mk["padj"] < 0.05) & (mk["log2fc"] > 0)].copy()
            mk["broad"] = mk["cell_type"].astype(str).map(broad)
            top = mk.sort_values("log2fc", ascending=False).groupby("cell_type").head(50)
            hits = {c: any(g in set(top[top["broad"] == c]["gene"]) for g in genes) for c, genes in PBMC_MARKERS.items()
                    if c in s["populations_found"]}
            s["canonical_markers_found"] = f"{sum(hits.values())}/{len(hits)}"
    return s


if __name__ == "__main__":
    print(json.dumps(score(*sys.argv[1:5])))
