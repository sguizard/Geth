#!/usr/bin/env python3
"""Score a Geth plan (plan_*.{csv,json,txt} in a run dir) against the known truth of a test dataset.

Usage: eval_plan.py <run_dir> <bulk|sc>   -> prints one JSON line with every check and a score.
"""
import csv
import io
import json
import os
import re
import sys

ROOT = "/exports/eddie/scratch/sguizard/Perseus_Veil/testdata"
SCHEMAS = {"rnaseq": "rnaseq-3.27.0.json", "scrnaseq": "scrnaseq-4.2.0.json"}


def known_params(pipeline):
    """All parameter names declared in the pinned pipeline's nextflow_schema.json."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schemas", SCHEMAS[pipeline])
    schema = json.load(open(path))
    groups = (schema.get("$defs") or schema.get("definitions") or {}).values()
    return {k for g in groups for k in g.get("properties", {})}


def load(run_dir):
    rd = lambda f: open(os.path.join(run_dir, f)).read() if os.path.exists(os.path.join(run_dir, f)) else ""
    rows = list(csv.DictReader(io.StringIO(rd("plan_samplesheet.csv").strip())))
    try:
        params = json.loads(rd("plan_params.json") or "null")
    except ValueError:
        params = None
    m = re.search(r"pipeline:\s*(\S+)", rd("plan_rationale.txt"))
    return rows, params, (m.group(1) if m else "").replace("nf-core/", "")


def run_of(path):
    m = re.search(r"(SRR\d+|Sample_[XY]_S1_L00\d)", path or "")
    return m.group(1) if m else None


def bulk(rows, params, pipeline):
    d = f"{ROOT}/bulk_yeast"
    c = {"pipeline": pipeline == "rnaseq",
         "columns": bool(rows) and {"sample", "fastq_1", "fastq_2", "strandedness"} <= set(rows[0].keys()),
         "n_rows_7": len(rows) == 7}
    name = {run_of(r.get("fastq_1")): r.get("sample") for r in rows}
    c["n_samples_5"] = len({r.get("sample") for r in rows}) == 5
    c["tech_reps_merged"] = (name.get("SRR6357070") == name.get("SRR6357071") is not None
                             and name.get("SRR6357074") == name.get("SRR6357075") is not None)
    c["bio_reps_distinct"] = len({name.get(s) for s in ("SRR6357070", "SRR6357072", "SRR6357073",
                                                        "SRR6357074", "SRR6357076")}) == 5
    se = {"SRR6357073", "SRR6357074", "SRR6357075"}
    c["layout_ok"] = bool(rows) and all(
        (not r.get("fastq_2")) if run_of(r.get("fastq_1")) in se
        else (r.get("fastq_2") or "").endswith(f"{run_of(r.get('fastq_1'))}_2.fastq.gz") for r in rows)
    c["strandedness_auto"] = bool(rows) and all(r.get("strandedness") == "auto" for r in rows)
    c["paths_exist"] = bool(rows) and all(os.path.isfile(r[k]) for r in rows for k in ("fastq_1", "fastq_2")
                                          if r.get(k))
    p = params if isinstance(params, dict) else {}
    c["params_json_object"] = isinstance(params, dict)
    c["fasta_gtf"] = p.get("fasta") == f"{d}/reference/genome.fasta" and p.get("gtf") == f"{d}/reference/genes.gtf.gz"
    c["no_genome_key"] = "genome" not in p
    return c


def sc(rows, params, pipeline):
    d = f"{ROOT}/sc_mouse_chr19"
    c = {"pipeline": pipeline == "scrnaseq",
         "columns": bool(rows) and {"sample", "fastq_1", "fastq_2"} <= set(rows[0].keys()),
         "n_rows_3": len(rows) == 3}
    samples = [r.get("sample") for r in rows]
    c["lanes_merged"] = len(set(samples)) == 2 and sorted(samples.count(s) for s in set(samples)) == [1, 2]
    c["r1_r2_order"] = bool(rows) and all("_R1_" in (r.get("fastq_1") or "") and "_R2_" in (r.get("fastq_2") or "")
                                          for r in rows)
    c["paths_exist"] = bool(rows) and all(os.path.isfile(r.get(k) or "") for r in rows for k in ("fastq_1", "fastq_2"))
    p = params if isinstance(params, dict) else {}
    c["params_json_object"] = isinstance(params, dict)
    c["protocol_10XV2"] = str(p.get("protocol", "")).upper() == "10XV2"
    c["fasta_gtf"] = (p.get("fasta") == f"{d}/reference/GRCm38.p6.genome.chr19.fa"
                      and p.get("gtf") == f"{d}/reference/gencode.vM19.annotation.chr19.gtf")
    c["aligner_valid"] = p.get("aligner", "simpleaf") in ("star", "simpleaf", "kallisto", "cellranger")
    c["skip_cellbender"] = p.get("skip_cellbender") in (True, "true")
    return c


def main():
    run_dir, kind = sys.argv[1], sys.argv[2]
    rows, params, pipeline = load(run_dir)
    checks = (bulk if kind == "bulk" else sc)(rows, params, pipeline)
    expected = "rnaseq" if kind == "bulk" else "scrnaseq"
    unknown = sorted(set(params or {}) - known_params(expected)) if isinstance(params, dict) else []
    checks["params_known"] = not unknown
    print(json.dumps({"run": os.path.basename(run_dir), "score": f"{sum(checks.values())}/{len(checks)}",
                      "all_pass": all(checks.values()), "failed": [k for k, v in checks.items() if not v],
                      **({"unknown_params": unknown} if unknown else {})}))


if __name__ == "__main__":
    main()
