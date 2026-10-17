#!/usr/bin/env python3
"""Score a Geth plan (plan_*.{csv,json,txt} in a run dir) against the known truth of a test dataset.

Usage: eval_plan.py <run_dir> <bulk|sc|airway|pbmc|airway_de>   -> prints one JSON line with every check and a score.
"""
import csv
import io
import json
import os
import re
import sys

# Where the benchmark data lives (see bench/stage_testdata.sh and bench/stage_public.sh): from env.sh.
for _var in ("GETH_DATA_ROOT", "GETH_REFERENCES", "GETH_RUNS_DIR"):
    if not os.environ.get(_var):
        sys.exit(f"{_var} is not set: source env.sh first")
ROOT = os.path.join(os.environ["GETH_DATA_ROOT"], "testdata")
SCHEMAS = {"rnaseq": "rnaseq-3.27.0.params.json", "scrnaseq": "scrnaseq-4.2.0.params.json",
           "differentialabundance": "differentialabundance-2.0.0.params.json"}


def known_params(pipeline):
    """All parameter names declared in the pinned pipeline's nextflow_schema.json."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "geth", "schemas", SCHEMAS[pipeline])
    if not os.path.isfile(path):
        return set()
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
    pipeline = rd("plan_pipeline.txt").strip()
    if not pipeline:  # spike runs kept the pipeline in the rationale file
        m = re.search(r"pipeline:\s*(\S+)", rd("plan_rationale.txt"))
        pipeline = m.group(1) if m else ""
    return rows, params, pipeline.replace("nf-core/", "")


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


GRCH38 = os.path.join(os.environ["GETH_REFERENCES"], "homo_sapiens_GRCh38_ens116")
GRCH38_FASTA = f"{GRCH38}/Homo_sapiens.GRCh38.dna.primary_assembly.fa.gz"
GRCH38_GTF = f"{GRCH38}/Homo_sapiens.GRCh38.116.gtf.gz"
AIRWAY_DEX = {"SRR1039508": False, "SRR1039509": True, "SRR1039512": False, "SRR1039513": True,
              "SRR1039516": False, "SRR1039517": True, "SRR1039520": False, "SRR1039521": True}


def airway(rows, params, pipeline):
    c = {"pipeline": pipeline == "rnaseq",
         "columns": bool(rows) and {"sample", "fastq_1", "fastq_2", "strandedness"} <= set(rows[0].keys()),
         "n_rows_8": len(rows) == 8}
    name = {run_of(r.get("fastq_1")): r.get("sample", "") for r in rows}
    c["one_sample_per_run"] = len(set(name.values())) == 8 and set(name) == set(AIRWAY_DEX)
    c["paired_files_only"] = bool(rows) and all(
        re.search(r"_1\.fastq\.gz$", r.get("fastq_1", "")) and re.search(r"_2\.fastq\.gz$", r.get("fastq_2") or "")
        for r in rows)  # the extra unpaired SRRxxx.fastq.gz files must be left out
    c["treatment_in_names"] = all(("dex" in name.get(run, "").lower()) == dex for run, dex in AIRWAY_DEX.items())
    c["strandedness_ok"] = bool(rows) and all(r.get("strandedness") in ("auto", "unstranded") for r in rows)
    c["paths_exist"] = bool(rows) and all(os.path.isfile(r[k]) for r in rows for k in ("fastq_1", "fastq_2") if r.get(k))
    p = params if isinstance(params, dict) else {}
    c["params_json_object"] = isinstance(params, dict)
    c["fasta_gtf"] = p.get("fasta") == GRCH38_FASTA and p.get("gtf") == GRCH38_GTF
    c["no_genome_key"] = "genome" not in p
    return c


def pbmc(rows, params, pipeline):
    c = {"pipeline": pipeline == "scrnaseq",
         "columns": bool(rows) and {"sample", "fastq_1", "fastq_2"} <= set(rows[0].keys()),
         "n_rows_2": len(rows) == 2,
         "lanes_merged": len({r.get("sample") for r in rows}) == 1,
         "r1_r2_order": bool(rows) and all("_R1_" in (r.get("fastq_1") or "") and "_R2_" in (r.get("fastq_2") or "")
                                           for r in rows),
         "index_reads_excluded": not any("_I1_" in v for r in rows for v in r.values() if v),
         "paths_exist": bool(rows) and all(os.path.isfile(r.get(k) or "") for r in rows for k in ("fastq_1", "fastq_2"))}
    p = params if isinstance(params, dict) else {}
    c["params_json_object"] = isinstance(params, dict)
    c["protocol_10XV3"] = str(p.get("protocol", "")).upper() == "10XV3"
    c["fasta_gtf"] = p.get("fasta") == GRCH38_FASTA and p.get("gtf") == GRCH38_GTF
    c["aligner_valid"] = p.get("aligner", "simpleaf") in ("star", "simpleaf", "kallisto", "cellranger")
    return c


AIRWAY_RUN = os.path.join(os.environ["GETH_RUNS_DIR"], "airway_1")
AIRWAY_SAMPLES = {f"{d}_{t}": (d, t == "Dex") for d in ("N61311", "N052611", "N080611", "N061011") for t in ("untreated", "Dex")}


def airway_de(rows, params, pipeline, run_dir):
    """Differential expression on airway_1: dex vs untreated, blocked on donor."""
    c = {"pipeline": pipeline == "differentialabundance",
         "samples_match_matrix": sorted(r.get("sample", "") for r in rows) == sorted(AIRWAY_SAMPLES)}
    cols = set(rows[0]) - {"sample"} if rows else set()
    # treatment column: the one that splits the samples into dex / untreated
    treat = next((col for col in cols if all((("dex" in r.get(col, "").lower()) and "un" not in r.get(col, "").lower())
                                             == AIRWAY_SAMPLES.get(r.get("sample"), (None, None))[1] for r in rows)), None)
    donor = next((col for col in cols if len({r.get(col) for r in rows}) == 4 and all(
        r.get(col) and r.get(col) in r.get("sample", "") for r in rows)), None)
    c["treatment_column"] = treat is not None
    c["donor_column"] = donor is not None
    contrasts = list(csv.DictReader(io.StringIO(open(os.path.join(run_dir, "plan_contrasts.csv")).read()))) \
        if os.path.isfile(os.path.join(run_dir, "plan_contrasts.csv")) else []
    main = next((x for x in contrasts if x.get("variable") == treat), None)
    c["one_treatment_contrast"] = main is not None and len(contrasts) == 1
    c["direction_untreated_to_dex"] = bool(main) and "un" in main.get("reference", "").lower() and "dex" in main.get("target", "").lower()
    c["donor_blocking"] = bool(main) and donor in (main.get("blocking") or "").split(";")
    p = params if isinstance(params, dict) else {}
    star = f"{AIRWAY_RUN}/results/star_salmon"
    c["raw_counts_matrix"] = p.get("matrix") == f"{star}/salmon.merged.gene_counts.tsv"
    c["length_matrix"] = p.get("feature_length_matrix") == f"{star}/salmon.merged.gene_lengths.tsv"
    c["same_gtf"] = p.get("gtf") == GRCH38_GTF
    profile = open(os.path.join(run_dir, "plan_profile.txt")).read().strip() if os.path.isfile(os.path.join(run_dir, "plan_profile.txt")) else ""
    c["deseq2_profile"] = profile.startswith("rnaseq") and "limma" not in profile
    return c


SCORERS = {"bulk": bulk, "sc": sc, "airway": airway, "pbmc": pbmc, "airway_de": airway_de}
PIPELINE = {"bulk": "rnaseq", "airway": "rnaseq", "sc": "scrnaseq", "pbmc": "scrnaseq", "airway_de": "differentialabundance"}
NEEDS_RUN_DIR = {"airway_de"}


def main():
    run_dir, kind = sys.argv[1], sys.argv[2]
    rows, params, pipeline = load(run_dir)
    checks = SCORERS[kind](rows, params, pipeline, run_dir) if kind in NEEDS_RUN_DIR else SCORERS[kind](rows, params, pipeline)
    expected = PIPELINE[kind]
    unknown = sorted(set(params or {}) - known_params(expected)) if isinstance(params, dict) else []
    checks["params_known"] = not unknown
    print(json.dumps({"run": os.path.basename(run_dir), "score": f"{sum(checks.values())}/{len(checks)}",
                      "all_pass": all(checks.values()), "failed": [k for k, v in checks.items() if not v],
                      **({"unknown_params": unknown} if unknown else {})}))


if __name__ == "__main__":
    main()
