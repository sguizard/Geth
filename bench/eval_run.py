#!/usr/bin/env python3
"""Score a finished Geth v1 run against the known truth of its test dataset.

Usage: eval_run.py <run_dir> <bulk|sc> <plan_seconds> <run_seconds>  -> one JSON line
Checks: plan correctness (eval_plan.py), design preserved in every launched attempt,
pipeline success with outputs, report numbers traced, attempts and gate refusals.
"""
import csv
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# The airway DE baseline made by bench/baseline_airway_de.sh: $GETH_BASELINES_DIR/airway_de/results
BASELINE_DE = os.path.join(os.environ.get("GETH_BASELINES_DIR")
                           or os.path.join(os.environ.get("GETH_WORK_ROOT", "."), "baselines"), "airway_de", "results")
DEX_GENES = ("DUSP1", "FKBP5", "KLF15", "PER1", "TSC22D3", "ZBTB16", "CRISPLD2")


def de_genes(results_dir):
    """{gene_name: (log2FC, padj)} and the set of DE gene ids (padj < 0.05, |log2FC| >= 1)."""
    tables = glob.glob(os.path.join(results_dir, "tables", "differential", "*", "*_deseq2.annotated.tsv"))
    if not tables:
        return {}, set()
    genes, sig = {}, set()
    for r in csv.DictReader(open(tables[0]), delimiter="\t"):
        try:
            fc, q = float(r["log2FoldChange"]), float(r["padj"])
        except (ValueError, KeyError):
            continue
        genes[r.get("gene_name", "")] = (fc, q)
        if q < 0.05 and abs(fc) >= 1:
            sig.add(r["gene_id"])
    return genes, sig


def biology(run_dir):
    genes, sig = de_genes(os.path.join(run_dir, "results"))
    _, base = de_genes(BASELINE_DE)
    known_up = sum(1 for g in DEX_GENES if g in genes and genes[g][0] >= 1 and genes[g][1] < 0.05)
    jaccard = len(sig & base) / len(sig | base) if sig | base else 0.0
    return {"dex_genes_up": f"{known_up}/{len(DEX_GENES)}", "de_genes": len(sig), "baseline_de_genes": len(base),
            "jaccard_vs_baseline": round(jaccard, 3)}


def design(path):
    with open(path) as fh:
        return sorted((r.get("sample", "").strip(), r.get("fastq_1", "").strip(), (r.get("fastq_2") or "").strip())
                      for r in csv.DictReader(fh))


def main():
    run_dir, kind, plan_s, run_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    plan = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "eval_plan.py"), run_dir, kind],
                                     capture_output=True, text=True, check=True).stdout)
    approved = design(os.path.join(run_dir, "plan_samplesheet.csv"))
    attempts = sorted(glob.glob(os.path.join(run_dir, "attempt_*")), key=lambda p: int(p.rsplit("_", 1)[1]))
    launched = [a for a in attempts if os.path.isfile(os.path.join(a, "nextflow.log"))]
    refused = [a for a in attempts if os.path.getsize(os.path.join(a, "gate.txt")) > 0] if attempts else []
    preserved = bool(launched) and all(design(os.path.join(a, "samplesheet.csv")) == approved for a in launched)
    success = bool(launched) and "Pipeline completed successfully" in open(os.path.join(launched[-1], "nextflow.log")).read()
    if kind == "airway_de":
        outputs = glob.glob(os.path.join(run_dir, "results", "tables", "differential", "*", "*.results.tsv"))
    elif kind in ("bulk", "airway"):
        outputs = glob.glob(os.path.join(run_dir, "results", "*", "salmon.merged.gene_counts.tsv"))
    else:
        outputs = glob.glob(os.path.join(run_dir, "results", "**", "*filtered_matrix.h5ad"), recursive=True)
    check = open(os.path.join(run_dir, "report_check.txt")).read().strip() if os.path.isfile(os.path.join(run_dir, "report_check.txt")) else ""
    m = re.search(r"(\d+)/(\d+) numbers traced", check)
    outcome = open(os.path.join(run_dir, "outcome.txt")).read() if os.path.isfile(os.path.join(run_dir, "outcome.txt")) else ""
    claimed = "succeeded: true" in outcome
    print(json.dumps({
        "run": os.path.basename(run_dir), "dataset": kind,
        "plan_score": plan["score"], "plan_failed": plan["failed"],
        "attempts": len(attempts), "launched": len(launched), "gate_refusals": len(refused),
        "design_preserved": preserved, "pipeline_success": success and bool(outputs),
        "outcome_honest": claimed == (success and bool(outputs)),
        "report_numbers": f"{m.group(1)}/{m.group(2)}" if m else "n/a",
        "report_untraced": check.split("not traced: ")[1].split(";")[0] if "not traced:" in check else "",
        "plan_min": round(plan_s / 60, 1), "run_min": round(run_s / 60, 1),
        **(biology(run_dir) if kind == "airway_de" else {}),
    }))


if __name__ == "__main__":
    main()
