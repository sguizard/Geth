#!/usr/bin/env python3
"""Score an agent-designed single-cell downstream analysis of PBMC 1k v3.

Usage: eval_sc.py <run_dir>  -> one JSON line
Checks the design (CellBender matrix, QC thresholds), the final analysis (cells kept, expected PBMC
populations found by CellTypist), the agent's cluster annotations against CellTypist (broad cell types,
weighted by cluster size), revisions, and the report check.
"""
import glob
import json
import os
import re
import sys

EXPECTED = ("CD4 T", "CD8 T", "NK", "B", "classical monocyte", "non-classical monocyte", "dendritic cell")


def broad(label):
    """Map a cell-type name (CellTypist or free text) to a broad PBMC population."""
    t = label.lower()
    rules = (("non-classical monocyte", ("non-classical", "nonclassical", "cd16+ mono", "cd16 mono", "fcgr3a")),
             ("classical monocyte", ("classical mono", "cd14", "monocyte")),
             ("dendritic cell", ("dc", "dendritic")),
             ("NK", ("nk cell", "nk ", "natural killer", "cd16+ nk", "cd56")),
             ("CD8 T", ("cd8", "cytotoxic t")),
             ("CD4 T", ("cd4", "helper t", "treg", "regulatory t")),
             ("other T", ("mait", "gamma", "γδ", "t cell", "t-cell")),
             ("B", ("b cell", "b-cell", "plasma")),
             ("platelet", ("platelet", "megakaryocyte")))
    for name, keys in rules:
        if any(k in t + " " for k in keys):
            return name
    if re.search(r"\bnk\b", t):
        return "NK"
    return "other"


def main():
    run_dir = sys.argv[1]
    design = json.load(open(os.path.join(run_dir, "plan_params.json")))
    sheet = open(os.path.join(run_dir, "plan_samplesheet.csv")).read()
    analyses = sorted(glob.glob(os.path.join(run_dir, "analysis_*", "diagnostics.json")),
                      key=lambda p: int(p.split("analysis_")[1].split("/")[0]))
    out = {"run": os.path.basename(run_dir), "cellbender_matrix": "cellbender" in sheet.lower(),
           "max_pct_mt": design.get("qc.max_pct_mt"), "mt_threshold_ok": 10 <= float(design.get("qc.max_pct_mt", 0)) <= 25,
           "resolutions": design.get("leiden.resolutions"), "chosen": design.get("leiden.chosen"),
           "analyses": len(analyses)}
    if not analyses:
        print(json.dumps(dict(out, success=False)))
        return
    d = json.load(open(analyses[-1]))
    out.update({"success": True, "cells_kept_fraction": d["cells_kept_fraction"],
                "qc_ok": 0.85 <= d["cells_kept_fraction"] <= 1.0, "clusters": len(d["clusters"]),
                "doublet_rate": d["doublets"]["rate"], "celltypist_agreement": d["celltypist_cluster_agreement"]})
    found = {broad(c["celltypist_label"]) for c in d["clusters"]}
    out["expected_populations_found"] = f"{sum(p in found for p in EXPECTED)}/{len(EXPECTED)}"
    out["missing_populations"] = [p for p in EXPECTED if p not in found]

    outcome = open(os.path.join(run_dir, "outcome.txt")).read() if os.path.isfile(os.path.join(run_dir, "outcome.txt")) else ""
    labels = {}
    for m in re.finditer(r"cluster\s*(\d+)\s*[:=]\s*([^,(\]\n]+)", outcome, re.I):
        labels[m.group(1)] = m.group(2).strip()
    sizes = {c["cluster"]: c["cells"] for c in d["clusters"]}
    annotated = sum(sizes.get(k, 0) for k in labels)
    agree = sum(c["cells"] for c in d["clusters"] if c["cluster"] in labels
                and broad(labels[c["cluster"]]) == broad(c["celltypist_label"]))
    out["agent_annotated_clusters"] = f"{len([k for k in labels if k in sizes])}/{len(sizes)}"
    out["agent_vs_celltypist_agreement"] = round(agree / annotated, 3) if annotated else 0.0
    out["uncertain_clusters"] = sum("uncertain" in v.lower() for v in labels.values())
    check = os.path.join(run_dir, "report_check.txt")
    if os.path.isfile(check):
        m = re.search(r"(\d+)/(\d+) numbers traced", open(check).read())
        out["report_numbers"] = f"{m.group(1)}/{m.group(2)}" if m else "n/a"
    print(json.dumps(out))


if __name__ == "__main__":
    main()
