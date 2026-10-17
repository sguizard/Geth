#!/usr/bin/env python3
"""Score a Geth plan (plan_*.{csv,json,txt} in a run dir) against the known truth of a test dataset.

Usage: eval_plan.py <run_dir> <dataset>   -> prints one JSON line with every check and a score.
Datasets: bulk, sc (bench/stage_testdata.sh); airway, pbmc, airway_de (bench/stage_public.sh);
chipseq_spt5, atacseq_osmotic, methylseq_wgbs, ampliseq_16s, nanoseq_barcoded, eager_mammoth, isoseq_brain
(bench/stage_deliveries.sh).
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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "geth", "bin"))
import geth_checks  # noqa: E402


def known_params(pipeline):
    """All parameter names declared in the pinned pipeline's schema (Geth's registry)."""
    return geth_checks.param_names(pipeline)


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


# ---------------------------------------------------------------- deliveries of bench/stage_deliveries.sh

def base(path):
    return os.path.basename(path or "")


def fnum(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def by_library(rows, pattern, column="fastq_1"):
    """{library (from the file name): row}; a library sequenced on several lanes maps to a list of rows."""
    out = {}
    for r in rows:
        m = re.match(pattern, base(r.get(column)))
        if m:
            out.setdefault(m.group(1), []).append(r)
    return out


def pairs_ok(rows):
    return bool(rows) and all(base(r.get("fastq_1")).replace("_R1_", "_R2_") == base(r.get("fastq_2"))
                              and "_R1_" in base(r.get("fastq_1")) for r in rows)


def chipseq_spt5(rows, params, pipeline):
    d = f"{ROOT}/chipseq_spt5"
    lib = {k: v[0] for k, v in by_library(rows, r"(CHIP0\d|INPUT0\d)_").items()}
    get = lambda l, col: (lib.get(l) or {}).get(col, "")
    chips, inputs = ("CHIP01", "CHIP02", "CHIP03", "CHIP04"), ("INPUT01", "INPUT02")
    culture = {"CHIP01": "1", "CHIP02": "2", "CHIP03": "1", "CHIP04": "2", "INPUT01": "1", "INPUT02": "2"}
    p = params if isinstance(params, dict) else {}
    # Each IP's control (sample, replicate) must be the input library of the same culture; the inputs may be
    # one sample with two replicates or two samples (both encodings pair the same libraries).
    input_of = {"1": "INPUT01", "2": "INPUT02"}
    c = {"pipeline": pipeline == "chipseq", "n_rows_6": len(rows) == 6,
         "all_libraries": set(lib) == set(chips + inputs), "r1_r2_pairs": pairs_ok(rows),
         "time_points_grouped": bool(get("CHIP01", "sample")) and get("CHIP01", "sample") == get("CHIP02", "sample")
         != get("CHIP03", "sample") == get("CHIP04", "sample"),
         "ip_replicates": all(get(l, "replicate") == culture[l] for l in chips),
         "inputs_distinct": len({(get(l, "sample"), get(l, "replicate")) for l in inputs}) == 2
         and not {get(l, "sample") for l in inputs} & {get(l, "sample") for l in chips},
         "controls_same_culture": all((get(l, "control"), get(l, "control_replicate"))
                                      == (get(input_of[culture[l]], "sample"), get(input_of[culture[l]], "replicate")) != ("", "")
                                      for l in chips),
         "antibody": all(get(l, "antibody").lower() == "spt5" for l in chips)
         and all(not get(l, "antibody") and not get(l, "control") for l in inputs),
         "fasta_gtf": p.get("fasta") == f"{d}/reference/genome.fa" and p.get("gtf") == f"{d}/reference/genes.gtf",
         "read_length_50": str(p.get("read_length")) == "50",
         "macs_gsize_yeast": 1.0e7 <= fnum(p.get("macs_gsize")) <= 1.3e7}
    return c


def atacseq_osmotic(rows, params, pipeline):
    d = f"{ROOT}/atacseq_osmotic"
    libs = by_library(rows, r"(ATAC0\d)_")
    one = lambda l, col: ((libs.get(l) or [{}])[0]).get(col, "")
    lanes = libs.get("ATAC01", [])
    p = params if isinstance(params, dict) else {}
    c = {"pipeline": pipeline == "atacseq", "n_rows_5": len(rows) == 5, "r1_r2_pairs": pairs_ok(rows),
         "lanes_one_library": len(lanes) == 2 and len({(r.get("sample"), r.get("replicate")) for r in lanes}) == 1,
         "conditions_grouped": bool(one("ATAC01", "sample")) and one("ATAC01", "sample") == one("ATAC02", "sample")
         != one("ATAC03", "sample") == one("ATAC04", "sample"),
         "replicates": [one(l, "replicate") for l in ("ATAC01", "ATAC02", "ATAC03", "ATAC04")] == ["1", "2", "1", "2"],
         "no_controls": not any(r.get("control") for r in rows),
         "fasta_gtf": p.get("fasta") == f"{d}/reference/genome.fa" and p.get("gtf") == f"{d}/reference/genes.gtf",
         "read_length_50": str(p.get("read_length")) == "50",
         "narrow_peak": p.get("narrow_peak") in (True, "true"),
         "mito_name_MT": p.get("mito_name") == "MT",
         "macs_gsize_yeast": 1.0e7 <= fnum(p.get("macs_gsize")) <= 1.3e7}
    return c


def methylseq_wgbs(rows, params, pipeline):
    d = f"{ROOT}/methylseq_wgbs"
    p = params if isinstance(params, dict) else {}
    presets = ("rrbs", "pbat", "em_seq", "single_cell", "zymo", "accel", "cegx", "epignome", "swift", "taps",
               "non_directional")
    return {"pipeline": pipeline == "methylseq", "n_rows_3": len(rows) == 3,
            "lanes_one_sample": len({r.get("sample") for r in rows}) == 1,
            "all_lanes": sorted(base(r.get("fastq_1")) for r in rows) == [f"WGBS-07_S7_L00{i}_R1_001.fastq.gz" for i in (1, 2, 3)],
            "single_end": bool(rows) and all(not r.get("fastq_2") for r in rows),
            "fasta": p.get("fasta") == f"{d}/reference/genome.fa.gz",
            "no_library_preset": not any(p.get(k) in (True, "true") for k in presets),
            "aligner_bisulfite": p.get("aligner", "bismark") in ("bismark", "bismark_hisat", "bwameth")}


def ampliseq_16s(rows, params, pipeline):
    d = f"{ROOT}/ampliseq_16s"
    lib = {k: v[0] for k, v in by_library(rows, r"(\d+a?)_S\d+_").items()}
    run = lambda l: (lib.get(l) or {}).get("run", "")
    p = params if isinstance(params, dict) else {}
    names = [r.get("sample", "") for r in rows]
    c = {"pipeline": pipeline == "ampliseq", "n_rows_4": len(rows) == 4, "all_samples": set(lib) == {"1", "2", "1a", "2a"},
         "valid_names": bool(names) and all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", n) for n in names),
         "distinct_names": len(set(names)) == 4, "r1_r2_pairs": pairs_ok(rows),
         "runs": bool(run("1")) and run("1") == run("2") != run("1a") == run("2a"),
         "primers": p.get("primer_fwd") == "GTGYCAGCMGCCGCGGTAA" and p.get("primer_rev") == "GGACTACNVGGGTWTCTAAT",
         "taxonomy_16s": str(p.get("dada_ref_taxonomy", "sbdi-gtdb")).split("=")[0]
         in ("silva", "gtdb", "sbdi-gtdb", "greengenes", "greengenes2", "rdp")}
    meta = p.get("metadata")
    if meta:  # ampliseq matches metadata IDs (first column) to sample names
        ids = [line.split("\t")[0] for line in open(meta).read().splitlines()[1:]] if os.path.isfile(str(meta)) else []
        c["metadata_matches_samples"] = sorted(ids) == sorted(names)
    return c


def nanoseq_barcoded(rows, params, pipeline):
    d = f"{ROOT}/nanoseq_barcoded"
    p = params if isinstance(params, dict) else {}
    rep_of = {str(int(fnum(r.get("barcode"), -1))): r.get("replicate") for r in rows}
    return {"pipeline": pipeline == "nanoseq", "n_rows_2": len(rows) == 2,
            "barcodes_6_12": sorted(rep_of) == ["12", "6"],
            "replicates": rep_of.get("6") == "1" and rep_of.get("12") == "2",
            "one_group": len({r.get("group") for r in rows}) == 1,
            "input_file_empty": bool(rows) and all(not r.get("input_file") for r in rows),
            "fasta_in_sheet": bool(rows) and all(r.get("fasta") == f"{d}/reference/hg19_KCMF1.fa" for r in rows),
            "protocol_DNA": p.get("protocol") == "DNA",
            "input_path": p.get("input_path") == f"{d}/fastq_pass/FAQ91234_pass_0.fastq.gz",
            "barcode_kit": p.get("barcode_kit") == "NBD103/NBD104",
            "demultiplexing_on": p.get("skip_demultiplexing") not in (True, "true")}


def eager_mammoth(rows, params, pipeline):
    d = f"{ROOT}/eager_mammoth"
    s = {r.get("Sample_Name"): r for r in rows}
    a, b = s.get("JK2782", {}), s.get("JK2802", {})
    p = params if isinstance(params, dict) else {}
    return {"pipeline": pipeline == "eager", "n_rows_2": len(rows) == 2, "sample_names": set(s) == {"JK2782", "JK2802"},
            "library_ids_unique": len({r.get("Library_ID") for r in rows}) == 2,
            "seqtype": a.get("SeqType") == "PE" and b.get("SeqType") == "SE",
            "colour_chemistry": a.get("Colour_Chemistry") == "4" and b.get("Colour_Chemistry") == "2",
            "udg": a.get("UDG_Treatment") == "none" and b.get("UDG_Treatment") == "full",
            "double_stranded": bool(rows) and all(r.get("Strandedness") == "double" for r in rows),
            "files": base(a.get("R1")) == "JK2782_TGGCCGATCAACGA_L008_R1_001.fastq.gz"
            and base(a.get("R2")) == "JK2782_TGGCCGATCAACGA_L008_R2_001.fastq.gz"
            and base(b.get("R1")) == "JK2802_AGAATAACCTACCA_L008_R1_001.fastq.gz" and b.get("R2") == "NA",
            "no_bam": bool(rows) and all(r.get("BAM") == "NA" for r in rows),
            "lane_8": bool(rows) and all(r.get("Lane") == "8" for r in rows),
            "fasta": p.get("fasta") == f"{d}/reference/Mammoth_MT_Krause.fasta"}


def isoseq_brain(rows, params, pipeline):
    d = f"{ROOT}/isoseq_brain"
    r = rows[0] if rows else {}
    p = params if isinstance(params, dict) else {}
    gtf = f"{d}/reference/Homo_sapiens.GRCh38.104.chr.13_18_19.gtf"
    return {"pipeline": pipeline == "isoseq", "n_rows_1": len(rows) == 1,
            "subreads": r.get("seq_data") == f"{d}/raw/alz_brain.subreads.bam",
            "pbi": r.get("pbi") == f"{d}/raw/alz_brain.subreads.bam.pbi",
            "start_from_ccs": r.get("start_from") == "ccs",
            "fasta": p.get("fasta") == f"{d}/reference/Homo_sapiens.GRCh38.dna.chromosome.19.fasta",
            "primers": p.get("primers") == f"{d}/primers.fasta",
            "aligner_ok": p.get("aligner") in ("minimap2", "ultra") and (p.get("aligner") != "ultra" or p.get("gtf") == gtf),
            "gtf_correct_if_set": "gtf" not in p or p.get("gtf") == gtf}


SCORERS = {"bulk": bulk, "sc": sc, "airway": airway, "pbmc": pbmc, "airway_de": airway_de,
           "chipseq_spt5": chipseq_spt5, "atacseq_osmotic": atacseq_osmotic, "methylseq_wgbs": methylseq_wgbs,
           "ampliseq_16s": ampliseq_16s, "nanoseq_barcoded": nanoseq_barcoded, "eager_mammoth": eager_mammoth,
           "isoseq_brain": isoseq_brain}
PIPELINE = {"bulk": "rnaseq", "airway": "rnaseq", "sc": "scrnaseq", "pbmc": "scrnaseq", "airway_de": "differentialabundance",
            **{k: k.split("_")[0] for k in ("chipseq_spt5", "atacseq_osmotic", "methylseq_wgbs", "ampliseq_16s",
                                            "nanoseq_barcoded", "eager_mammoth", "isoseq_brain")}}
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
