#!/usr/bin/env python3
"""Score an EXPERIMENTAL lab design (arm A) against what a coherent analysis of the benchmark must do.

Usage: eval_design.py <lab_run_dir> <kang2018|pbmc1k>   -> one JSON line with every check and a score.

kang2018: PBMCs of 8 donors, control vs IFN-beta (Kang et al. 2018). The matrix was filtered by the authors
(median 533 genes per cell) and has no mitochondrial reads; demuxlet called singlets and doublets. A coherent
analysis keeps the cells, uses the demuxlet calls, integrates across conditions for clustering, annotates cell
types, and tests the stimulation per cell type with donors as replicates (pseudobulk, paired design).
pbmc1k: one healthy donor, about 1,000 cells after CellBender: QC, doublet detection, no integration, clustering,
annotation with markers and a reference model, markers per cluster.
"""
import json
import os
import re
import sys

STEPS = ("qc", "doublets", "normalisation", "feature_selection", "dimensionality_reduction", "integration",
         "clustering", "annotation", "differential_expression")
ISGS = ("ISG15", "IFI6", "MX1", "IFIT1", "IFIT2", "IFIT3", "OAS1", "IFI44L", "ISG20", "LY6E", "IFITM3", "RSAD2", "STAT1")



def cell_unit(unit):
    """Does a statistics line's unit of replication say cells (not donors, samples or pseudobulks)?"""
    import re as _re
    u = unit.lower()
    return bool(_re.search(r"\bcells?\b", u)) and not _re.search(r"donor|sample|individual|patient|pseudobulk|subject", u)

def read(run_dir, name):
    path = os.path.join(run_dir, name)
    if not os.path.isfile(path):
        return []
    return [l.strip() for l in open(path) if l.strip() and not l.startswith("#")]


def has(text, *patterns):
    return any(re.search(p, text, re.I) for p in patterns)


def numbers_after(text, label):
    return [int(n) for n in re.findall(rf"{label}[^0-9|]{{0,20}}(\d+)", text, re.I)]


def score(run_dir, dataset):
    steps, settings = {}, {}  # settings: the 4th field only, so numbers quoted in the reason are not cut-offs
    for line in read(run_dir, "lab_design_steps.txt"):
        fields = [f.strip() for f in line.split("|")]
        if len(fields) == 5:
            steps[fields[0]] = steps.get(fields[0], "") + " " + " | ".join(fields[1:])
            settings[fields[0]] = settings.get(fields[0], "") + " " + fields[3]
    stats = read(run_dir, "lab_design_statistics.txt")
    expected = " ".join(read(run_dir, "lab_design_expected.txt"))
    rationale = " ".join(read(run_dir, "lab_design_rationale.txt"))
    check = " ".join(read(run_dir, "lab_design_check.txt"))
    s = lambda k: steps.get(k, "")
    stats_text = " ".join(stats)
    de_text = s("differential_expression") + " " + stats_text

    c = {"format_ok": "DESIGN CHECK: OK" in check, "all_steps": all(k in steps for k in STEPS),
         "log_normalisation": has(s("normalisation"), r"log", r"sctransform", r"pearson"),
         "hvg_1000_5000": any(1000 <= n <= 5000 for n in map(int, re.findall(r"\d+", s("feature_selection")))),
         "pca": has(s("dimensionality_reduction"), r"(?<![a-z])pca(?![a-z])", r"principal", r"n_pcs"),  # pca_umap counts
         "graph_clustering": has(s("clustering"), r"leiden", r"louvain"),
         "annotation_markers_and_reference": has(s("annotation"), r"marker") and has(s("annotation"), r"celltypist", r"reference", r"azimuth", r"singler")}

    if dataset == "kang2018":
        genes_cut = numbers_after(settings.get("qc", ""), r"genes?")
        c.update({
            "qc_keeps_filtered_cells": not genes_cut or max(genes_cut) <= 350,
            "notices_no_mito_reads": has(s("qc") + " " + rationale, r"mito\w*[^|]{0,80}(\b0 ?%|zero|absent|no reads|not present|removed|pre-?filtered|none|not available)",
                                         r"(no|zero|absent)\s+mitochondrial"),
            "doublets_from_demuxlet": has(s("doublets"), r"demuxlet", r"singlet", r"genotyp"),
            "integration_across_conditions": not has(s("integration"), r"^\s*none\b") and has(s("integration"), r"harmony", r"scvi", r"bbknn", r"scanorama", r"\bcca\b", r"seurat", r"combat"),
            "de_pseudobulk": has(de_text, r"pseudo-?bulk", r"aggregat", r"sum(med)? (raw )?counts"),
            "de_bulk_method": has(de_text, r"deseq2", r"edger", r"limma", r"pydeseq2", r"glmm"),
            "de_replicate_is_donor": any(has(l.split("|")[1], r"donor", r"individual", r"patient", r"sample") for l in stats if l.count("|") == 4),
            "de_paired_by_donor": any(has(l.split("|")[3], r"donor", r"individual", r"patient") for l in stats if l.count("|") == 4),
            "de_per_cell_type": has(de_text, r"cell[ _-]?type", r"per cluster", r"each cluster"),
            "multiple_testing": has(stats_text, r"\bbh\b", r"benjamini", r"\bfdr\b", r"padj", r"adjusted"),
            # cells as the unit of replication; a minimum number of cells per donor is not that
            "no_cell_level_condition_test": not any(has(l, r"stim|ifn|interferon|condition|ctrl") and cell_unit(l.split("|")[1])
                                                    for l in stats if l.count("|") == 4),
            "expects_interferon_genes": has(expected, r"interferon[- ]stimulated", r"\bISGs?\b") or sum(g in expected.upper() for g in ISGS) >= 2,
            "expects_cell_types": sum(has(expected, p) for p in (r"monocyte", r"\bT cells?\b|\bCD4\b|\bCD8\b", r"\bB cells?\b", r"\bNK\b")) >= 3,
        })
    elif dataset == "pbmc1k":
        genes_cut = numbers_after(settings.get("qc", ""), r"genes?")
        mito_cut = numbers_after(settings.get("qc", ""), r"(?:mito\w*|pct_mt|mt ?%|% ?mt)")
        c.update({
            "qc_sane": (not genes_cut or max(genes_cut) <= 500) and (not mito_cut or 5 <= max(mito_cut) <= 25),
            "doublet_detector": has(s("doublets"), r"scrublet", r"scdblfinder", r"doubletfinder", r"solo"),
            "no_integration_single_sample": has(s("integration"), r"none", r"not needed", r"single sample", r"one sample", r"skip"),
            "markers_per_cluster": has(de_text, r"marker", r"wilcoxon", r"rank_genes", r"t-test", r"logreg"),
            "expects_populations": sum(has(expected, p) for p in (r"\bCD4\b", r"\bCD8\b", r"\bNK\b", r"\bB cells?\b|MS4A1",
                                                                  r"CD14", r"FCGR3A|CD16", r"dendritic|\bDCs?\b")) >= 5,
        })
    else:
        sys.exit(f"unknown dataset {dataset}")
    return c


def main():
    run_dir, dataset = sys.argv[1], sys.argv[2]
    c = score(run_dir, dataset)
    arm = " ".join(read(run_dir, "lab_arm.txt"))
    print(json.dumps({"run": os.path.basename(run_dir), "dataset": dataset, "arm": arm,
                      "score": f"{sum(c.values())}/{len(c)}", "failed": [k for k, v in c.items() if not v]}))


if __name__ == "__main__":
    main()
