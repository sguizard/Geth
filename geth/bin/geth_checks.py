#!/usr/bin/env python3
"""Deterministic checks that keep Geth's agents honest.

A plan has parts: pipeline, samplesheet (or observations sheet), params, and for downstream
analyses a contrasts table, an analysis profile and the upstream run it builds on.
Optional parts are given with  --contrasts <file>  --profile <name>  --upstream <run_dir>.

  geth_checks.py check-plan <pipeline> <samplesheet.csv> <params> [<normalised_params_out>] [parts] [--save-checked <run_dir>]
      Validate a plan against the pinned pipeline's schemas (params as a JSON object or key=value lines).
  geth_checks.py save-plan <run_dir> <pipeline> <samplesheet.csv> <params> <rationale.txt> [parts]
      Write the planner's proposal as plan_* files (falling back to the last checked version).
  geth_checks.py approve <run_dir> <approver>
      Record approval of the plan files in <run_dir> (hashes them into APPROVED).
  geth_checks.py gate <run_dir> <pipeline> <samplesheet.csv> <params> [parts]
      Refuse an operator attempt that departs from the approved plan without a reason
      given by the previous error.
  geth_checks.py record <run_dir> <ok|check|nextflow> <samplesheet.csv> <params.json> [<error.txt>]
      Store an accepted attempt as the new baseline, with the error that may justify the next change.
  geth_checks.py revision <pipeline>
      Print the pinned revision of a pipeline (exit 1 if Geth does not run it).

Exit status 0 = OK, 1 = problems (described on stdout).
"""
import csv
import difflib
import getpass
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HERE, "..", "schemas")
OWNED = ("input", "outdir", "contrasts", "custom_config_base", "custom_config_version")  # set by Geth only

# Pipelines Geth runs. "design" = samplesheet columns that define the experiment and may never change
# after approval (None = every column). Downstream pipelines also need contrasts and an analysis profile.
REGISTRY = {
    "rnaseq": {"revision": "3.27.0", "design": ("sample", "fastq_1", "fastq_2"), "key": "fastq_1"},
    "scrnaseq": {"revision": "4.2.0", "design": ("sample", "fastq_1", "fastq_2"), "key": "fastq_1"},
    "sarek": {"revision": "3.10.0", "design": ("patient", "sample", "status", "lane", "fastq_1", "fastq_2", "bam", "cram"),
              "key": ("fastq_1", "bam", "cram", "spring_1", "vcf")},
    "isoseq": {"revision": "3.0.1", "design": ("sample", "seq_data", "start_from"), "key": "seq_data",
               "required_params": ("aligner", "fasta")},
    "taxprofiler": {"revision": "2.0.1", "design": ("sample", "run_accession", "fastq_1", "fastq_2", "fasta"),
                    "key": ("fastq_1", "fasta"), "required_params": ("databases",)},
    "mag": {"revision": "5.5.0", "design": ("sample", "run", "group", "short_reads_1", "short_reads_2", "long_reads"),
            "key": ("short_reads_1", "long_reads")},
    "ampliseq": {"revision": "3.0.0", "design": ("sample", "run", "fastq_1", "fastq_2"), "key": "fastq_1"},
    "chipseq": {"revision": "2.1.0", "key": "fastq_1",
                "design": ("sample", "replicate", "antibody", "control", "control_replicate", "fastq_1", "fastq_2")},
    "atacseq": {"revision": "2.1.2", "key": "fastq_1",
                "design": ("sample", "replicate", "control", "control_replicate", "fastq_1", "fastq_2")},
    "nanoseq": {"revision": "3.1.0", "design": ("group", "replicate", "barcode", "input_file"),
                "key": ("input_file", "barcode"), "required_params": ("protocol",)},
    "methylseq": {"revision": "4.2.0", "design": ("sample", "fastq_1", "fastq_2"), "key": "fastq_1"},
    # eager 2.5.3 is DSL1: run with an older Nextflow (and Java 17), TSV input, max_* resource params.
    "eager": {"revision": "2.5.3", "key": ("R1", "BAM"), "nextflow": "22.10.8",
              "java_home": "/usr/lib/jvm/java-17-openjdk", "input_format": "tsv", "legacy_limits": True,
              "design": ("Sample_Name", "Library_ID", "Lane", "SeqType", "Strandedness", "UDG_Treatment", "R1", "R2", "BAM")},
    "differentialabundance": {
        "revision": "2.0.0", "design": None, "key": "sample", "downstream": True,
        "profiles": ("rnaseq", "rnaseq_deseq2_gprofiler2", "rnaseq_deseq2_gsea", "rnaseq_limma"),
    },
}
BASE_FILES = ("plan_pipeline.txt", "plan_samplesheet.csv", "plan_params.json")
PART_FILES = {"contrasts": "plan_contrasts.csv", "profile": "plan_profile.txt", "upstream": "plan_upstream.txt"}


# ---------------------------------------------------------------- parsing

def pipeline_name(name):
    return name.strip().replace("nf-core/", "")


# Samplesheet rules for pipelines whose release has no (or an outdated) assets/schema_input.json.
NA = ("", "NA")
INPUT_SPECS = {
    "nanoseq": {"required": ["group", "replicate"], "properties": {
        "group": {"type": "string", "pattern": r"^\S+$"},
        "replicate": {"type": "integer"},
        "barcode": {"type": "integer"},
        "input_file": {"type": "string", "format": "path", "pattern": r"^\S+(\.f(ast)?q\.gz|\.bam|/?)$"},
        "fasta": {"type": "string", "pattern": r"^\S+$"},
        "gtf": {"type": "string", "format": "file-path", "pattern": r"^\S+\.gtf(\.gz)?$"}}},
    "eager": {"required": ["Sample_Name", "Library_ID", "Lane", "Colour_Chemistry", "SeqType", "Organism",
                           "Strandedness", "UDG_Treatment", "R1", "R2", "BAM"], "properties": {
        "Sample_Name": {"type": "string", "pattern": r"^[^\s.]+$"},
        "Library_ID": {"type": "string", "pattern": r"^[^\s.]+$"},
        "Lane": {"type": "integer"},
        "Colour_Chemistry": {"type": "string", "enum": ["2", "4"]},
        "SeqType": {"type": "string", "enum": ["PE", "SE"]},
        "Organism": {"type": "string"},
        "Strandedness": {"type": "string", "enum": ["single", "double"]},
        "UDG_Treatment": {"type": "string", "enum": ["none", "half", "full"]},
        "R1": {"type": "string", "format": "file-path", "pattern": r"^(NA|\S+\.f(ast)?q(\.gz)?)$"},
        "R2": {"type": "string", "format": "file-path", "pattern": r"^(NA|\S+\.f(ast)?q(\.gz)?)$"},
        "BAM": {"type": "string", "format": "file-path", "pattern": r"^(NA|\S+\.bam)$"}}},
}


def load_schema(pipeline, kind):
    if kind == "input" and pipeline in INPUT_SPECS:
        return {"items": INPUT_SPECS[pipeline]}
    return json.load(open(os.path.join(SCHEMAS, f"{pipeline}-{REGISTRY[pipeline]['revision']}.{kind}.json")))


def param_names(pipeline):
    schema = load_schema(pipeline, "params")
    groups = (schema.get("$defs") or schema.get("definitions") or {}).values()
    return {k for g in groups for k in g.get("properties", {})}


def typed(value):
    value = value.strip().strip('"').strip("'")
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def parse_params(text):
    """Params as a JSON object, or as key=value lines (how agents hand them over most reliably)."""
    text = text.strip()
    if not text:
        return {}
    if text.startswith("{"):
        params = json.loads(text)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
    else:
        params = {}
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            if "=" not in line:
                raise ValueError(f"params line '{line}' is not key=value")
            key, value = line.split("=", 1)
            params[key.strip()] = typed(value)
    return {k: v for k, v in params.items() if k not in OWNED}


def parse_sheet(text):
    reader = csv.DictReader(io.StringIO(text.strip()))
    header = [h.strip() for h in (reader.fieldnames or [])]
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return header, rows


def row_key(pipeline, row):
    """The file that identifies a samplesheet row (first non-empty of the pipeline's key columns)."""
    keys = REGISTRY[pipeline]["key"]
    for k in (keys if isinstance(keys, tuple) else (keys,)):
        if row.get(k):
            return row[k]
    return ""


def param_specs(pipeline):
    schema = load_schema(pipeline, "params")
    groups = (schema.get("$defs") or schema.get("definitions") or {}).values()
    specs = {k: v for g in groups for k, v in g.get("properties", {}).items()}
    required = {k for g in groups for k in g.get("required", [])}
    return specs, required


def is_remote(value):
    return isinstance(value, str) and value.startswith(("http://", "https://", "s3://", "gs://", "az://"))


def design_of(pipeline, rows):
    cols = REGISTRY[pipeline]["design"]
    return sorted(tuple(sorted(r.items())) if cols is None else tuple(r.get(c, "") for c in cols) for r in rows)


def normalised_csv(text):
    header, rows = parse_sheet(text or "")
    return header, sorted(tuple(r.get(h, "") for h in header) for r in rows)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def read_text(path):
    return open(path).read() if path and os.path.isfile(path) else ""


# ---------------------------------------------------------------- plan validation

def check_params(pipeline, params_text):
    problems = []
    try:
        params = parse_params(params_text)
    except ValueError as e:
        return [f"params_json is not a valid JSON object: {e}"], {}
    known = param_names(pipeline)
    for key in sorted(set(params) - known):
        close = difflib.get_close_matches(key, known, n=3)
        problems.append(f"param '{key}' does not exist in nf-core/{pipeline} {REGISTRY[pipeline]['revision']}"
                        + (f" (closest: {', '.join(close)})" if close else ""))
    if REGISTRY[pipeline].get("toolbox"):
        return problems, params
    specs, _ = param_specs(pipeline)
    # Schema "required" flags include params filled by defaults or profiles: Geth lists the real ones.
    for key in REGISTRY[pipeline].get("required_params", ()):
        if params.get(key) in (None, ""):
            problems.append(f"param '{key}' is required by nf-core/{pipeline}")
    for key, value in params.items():
        spec = specs.get(key, {})
        if value is None or isinstance(value, bool):
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"param '{key}' must be one of {spec['enum']} (got {value!r})")
        if "pattern" in spec and isinstance(value, str):
            try:
                if not re.search(spec["pattern"], value):
                    problems.append(f"param '{key}' value {value!r} is not valid for nf-core/{pipeline}")
            except re.error:
                pass
        if spec.get("format") in ("file-path", "directory-path", "path") and isinstance(value, str) and value \
                and not is_remote(value) and not os.path.exists(value):
            problems.append(f"param '{key}' points to a file that does not exist: {value}")
    return problems, params


def check_fastq_sheet(pipeline, sheet_text, params):
    problems = []
    if pipeline in ("rnaseq", "scrnaseq") and "genome" in params and ("fasta" in params or "gtf" in params):
        problems.append("set either 'genome' or 'fasta'/'gtf', not both")

    schema = load_schema(pipeline, "input")["items"]
    props, required = schema["properties"], schema.get("required", [])
    header, rows = parse_sheet(sheet_text)
    for col in required:
        if col not in header:
            problems.append(f"samplesheet: required column '{col}' is missing (header is: {','.join(header)})")
    for col in header:
        if col not in props:
            problems.append(f"samplesheet: column '{col}' is not used by nf-core/{pipeline}")
    if not rows:
        problems.append("samplesheet has no rows")
    seen = {}
    for i, row in enumerate(rows, start=2):
        for col, spec in props.items():
            value = row.get(col, "")
            if pipeline == "eager" and value == "NA" and col not in ("Sample_Name", "Library_ID"):
                continue  # eager's TSV writes NA for unused fields
            if not value or (pipeline == "isoseq" and col == "pbi" and value == "none"):
                if col in required and not (col == "fastq_2" and pipeline == "rnaseq"):
                    problems.append(f"samplesheet line {i}: '{col}' is empty")
                continue
            if "enum" in spec and value not in [str(e) for e in spec["enum"]]:  # CSV values are text
                problems.append(f"samplesheet line {i}: '{col}' must be one of {spec['enum']} (got '{value}')")
            if "pattern" in spec and not re.search(spec["pattern"], value):
                problems.append(f"samplesheet line {i}: '{col}' value '{value}' is not valid ({spec.get('errorMessage', 'pattern ' + spec['pattern'])})")
            if spec.get("type") == "integer" and not value.isdigit():
                problems.append(f"samplesheet line {i}: '{col}' must be an integer (got '{value}')")
            if spec.get("format") == "path" and not (value.startswith("/") and os.path.exists(value)):
                problems.append(f"samplesheet line {i}: '{col}' must be an existing absolute path (got '{value}')")
            if spec.get("format") == "file-path":
                if not value.startswith("/"):
                    problems.append(f"samplesheet line {i}: '{col}' must be an absolute path (got '{value}')")
                elif not os.path.isfile(value):
                    problems.append(f"samplesheet line {i}: '{col}' file does not exist: {value}")
                elif value.endswith(".gz") and open(value, "rb").read(2) != b"\x1f\x8b":
                    problems.append(f"samplesheet line {i}: '{col}' is named .gz but is not gzip-compressed: {value}")
        key = row_key(pipeline, row)
        if key and key in seen:
            problems.append(f"samplesheet line {i}: {os.path.basename(key)} already used on line {seen[key]}")
        seen[key] = i
    if pipeline == "rnaseq":
        layout = {}
        for row in rows:
            layout.setdefault(row.get("sample"), set()).add(bool(row.get("fastq_2")))
        for sample, kinds in layout.items():
            if len(kinds) > 1:
                problems.append(f"samplesheet: sample '{sample}' mixes single-end and paired-end rows")
    problems += EXTRA_CHECKS.get(pipeline, lambda r, p: [])(rows, params)
    return problems


def check_sarek(rows, params):
    problems = []
    step = params.get("step", "mapping")
    if step == "mapping":
        for i, r in enumerate(rows, start=2):
            if not r.get("lane"):
                problems.append(f"samplesheet line {i}: 'lane' is required to start from FASTQ (step=mapping)")
        lanes = [(r.get("patient"), r.get("sample"), r.get("lane")) for r in rows]
        for dup in sorted({l for l in lanes if lanes.count(l) > 1}):
            problems.append(f"samplesheet: lane '{dup[2]}' of sample '{dup[1]}' appears more than once")
    tools = set(filter(None, str(params.get("tools", "")).split(",")))
    tumours = {r.get("patient") for r in rows if str(r.get("status")) == "1"}
    normals = {r.get("patient") for r in rows if str(r.get("status", "0")) in ("0", "")}
    paired_only = tools & {"ascat", "muse", "msisensorpro", "controlfreec"}
    if tools & {"mutect2", "ascat", "muse", "msisensorpro", "controlfreec", "lofreq", "msisensor2"} and not tumours:
        problems.append("somatic callers were requested but no sample has status 1 (tumour)")
    for patient in sorted(tumours - normals) if paired_only else []:
        problems.append(f"patient '{patient}' has a tumour but no normal sample; {', '.join(sorted(paired_only))} need tumour/normal pairs")
    if "fasta" not in params and "genome" not in params:
        problems.append("set 'fasta' (a reference from the catalogue) or 'genome'")
    return problems


def check_isoseq(rows, params):
    problems = []
    for i, r in enumerate(rows, start=2):
        pbi, start = r.get("pbi", ""), r.get("start_from", "")
        if start == "ccs" and not (pbi and pbi != "none" and os.path.isfile(pbi)):
            problems.append(f"samplesheet line {i}: a subreads BAM (start_from=ccs) needs its .pbi index file in 'pbi'")
        if start != "ccs" and pbi not in ("", "none"):
            problems.append(f"samplesheet line {i}: 'pbi' must be 'none' unless start_from is ccs")
    if params.get("aligner") == "ultra" and not params.get("gtf"):
        problems.append("aligner 'ultra' needs a 'gtf' annotation")
    if any(r.get("start_from") in ("ccs", "lima", "refine") for r in rows) and not params.get("primers"):
        problems.append("'primers' (FASTA of the Iso-Seq primers) is required unless every row starts from mapping")
    return problems


def check_taxprofiler(rows, params):
    problems = []
    runs = [(r.get("sample"), r.get("run_accession")) for r in rows]
    for dup in sorted({x for x in runs if runs.count(x) > 1}):
        problems.append(f"samplesheet: run_accession '{dup[1]}' is used twice for sample '{dup[0]}'")
    for i, r in enumerate(rows, start=2):
        if r.get("fasta") and (r.get("fastq_1") or r.get("fastq_2")):
            problems.append(f"samplesheet line {i}: a row has either FASTQ files or a FASTA file, not both")
    db = params.get("databases")
    if isinstance(db, str) and os.path.isfile(db):
        with open(db) as fh:
            tools = {row.get("tool", "").strip() for row in csv.DictReader(fh)}
        for key, value in params.items():
            if key.startswith("run_") and value is True and key not in ("run_profile_standardisation", "run_krona", "run_merging"):
                tool = key[4:]
                if tool not in tools and not (tool == "bracken" and "kraken2" in tools and "bracken" in tools):
                    problems.append(f"'{key}' is on but the databases sheet has no '{tool}' database")
        if "bracken" in tools and params.get("run_bracken") is True and params.get("run_kraken2") is not True:
            problems.append("'run_bracken' needs 'run_kraken2' too")
    if not any(k.startswith("run_") and v is True and k not in ("run_profile_standardisation", "run_krona")
               for k, v in params.items()):
        problems.append("no profiler enabled: set at least one run_<tool>=true matching the databases sheet")
    return problems


def check_mag(rows, params):
    problems = []
    for i, r in enumerate(rows, start=2):
        if r.get("short_reads_1") and not r.get("short_reads_platform"):
            problems.append(f"samplesheet line {i}: 'short_reads_platform' is required with short reads")
        if r.get("long_reads") and not r.get("long_reads_platform"):
            problems.append(f"samplesheet line {i}: 'long_reads_platform' is required with long reads")
        if not r.get("group"):
            problems.append(f"samplesheet line {i}: 'group' is empty")
    short = [bool(r.get("short_reads_2")) for r in rows if r.get("short_reads_1")]
    if short and len(set(short)) > 1:
        problems.append("samplesheet mixes single-end and paired-end short reads (not supported by nf-core/mag)")
    if short and not any(short) and params.get("single_end") is not True:
        problems.append("short reads are single-end: set 'single_end=true'")
    if params.get("coassemble_group") is True and params.get("binning_map_mode") != "group":
        problems.append("'coassemble_group' needs 'binning_map_mode=group'")
    return problems


def check_replicates(rows, name):
    """Replicates of each sample must be numbered 1..N without gaps."""
    problems = []
    reps = {}
    for r in rows:
        if str(r.get("replicate", "")).isdigit():
            reps.setdefault(r.get("sample"), set()).add(int(r["replicate"]))
    for sample, numbers in sorted(reps.items()):
        if sorted(numbers) != list(range(1, len(numbers) + 1)):
            problems.append(f"{name}: replicates of '{sample}' must be numbered 1..N without gaps (got {sorted(numbers)})")
    return problems


def check_controls(rows, name, need_antibody):
    problems = []
    known = {(r.get("sample"), r.get("replicate")) for r in rows}
    for i, r in enumerate(rows, start=2):
        ctrl, crep = r.get("control", ""), r.get("control_replicate", "")
        if ctrl and (ctrl, crep) not in known:
            problems.append(f"{name} line {i}: control '{ctrl}' replicate '{crep}' is not a row of the samplesheet")
        if need_antibody and ctrl and not r.get("antibody"):
            problems.append(f"{name} line {i}: an IP sample with a control needs its 'antibody'")
        if need_antibody and not ctrl and r.get("antibody") and any(x.get("control") for x in rows):
            problems.append(f"{name} line {i}: IP sample '{r.get('sample')}' has no control while others do")
    controls = {r.get("control") for r in rows if r.get("control")}
    for i, r in enumerate(rows, start=2):
        if r.get("sample") in controls and (r.get("antibody") or r.get("control")):
            problems.append(f"{name} line {i}: control sample '{r.get('sample')}' must have empty antibody and control")
    return problems


def check_chipseq(rows, params):
    problems = check_replicates(rows, "samplesheet") + check_controls(rows, "samplesheet", True)
    if not params.get("genome") and not params.get("macs_gsize"):
        problems.append("'macs_gsize' (effective genome size) is required with a custom genome")
    return problems


def check_atacseq(rows, params):
    problems = check_replicates(rows, "samplesheet")
    if params.get("with_control") is True:
        problems += check_controls(rows, "samplesheet", False)
    elif any(r.get("control") for r in rows):
        problems.append("control columns are filled: set 'with_control=true' (or empty them)")
    if not params.get("genome") and not params.get("macs_gsize"):
        problems.append("'macs_gsize' (effective genome size) is required with a custom genome")
    return problems


def check_ampliseq(rows, params):
    problems = []
    for i, r in enumerate(rows, start=2):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", r.get("sample", "")):
            problems.append(f"samplesheet line {i}: sample '{r.get('sample')}' must start with a letter and use only letters, digits and '_'")
    if params.get("skip_cutadapt") is not True and not (params.get("primer_fwd") and params.get("primer_rev")):
        problems.append("'primer_fwd' and 'primer_rev' are required (or skip_cutadapt=true if primers are already removed)")
    paired = {bool(r.get("fastq_2")) for r in rows}
    if paired == {False} and params.get("sequencing_type", "illumina_pe") == "illumina_pe":
        problems.append("single-end reads: set 'sequencing_type' to illumina_se (or the right technology)")
    return problems


def check_nanoseq(rows, params):
    problems = []
    demux = params.get("skip_demultiplexing") is not True
    for i, r in enumerate(rows, start=2):
        if demux and (r.get("input_file") or not r.get("barcode")):
            problems.append(f"samplesheet line {i}: demultiplexing needs 'barcode' and an empty 'input_file' "
                            "(or set skip_demultiplexing=true for per-sample files)")
        if not demux and (not r.get("input_file") or r.get("barcode")):
            problems.append(f"samplesheet line {i}: with skip_demultiplexing=true give 'input_file' and leave 'barcode' empty")
        fasta = r.get("fasta", "")
        if fasta.startswith("/") and not os.path.isfile(fasta):
            problems.append(f"samplesheet line {i}: fasta file does not exist: {fasta}")
    if demux and not (params.get("input_path") and params.get("barcode_kit")):
        problems.append("demultiplexing needs 'input_path' (pooled reads) and 'barcode_kit'")
    if params.get("protocol") not in ("DNA", "cDNA", "directRNA"):
        problems.append("'protocol' must be DNA, cDNA or directRNA")
    return problems


def check_eager(rows, params):
    problems = []
    libs = {}
    lanes = [(r.get("Library_ID"), r.get("Lane")) for r in rows]
    for i, r in enumerate(rows, start=2):
        libs.setdefault(r.get("Library_ID"), set()).add(r.get("Sample_Name"))
        has_fq, has_bam = r.get("R1", "NA") not in NA, r.get("BAM", "NA") not in NA
        if has_fq == has_bam:
            problems.append(f"samplesheet line {i}: give either R1 (FASTQ) or BAM, not both or neither")
        if r.get("SeqType") == "PE" and r.get("R2", "NA") in NA:
            problems.append(f"samplesheet line {i}: SeqType PE needs R2")
        if r.get("SeqType") == "SE" and r.get("R2", "NA") not in NA:
            problems.append(f"samplesheet line {i}: SeqType SE must have R2=NA")
        if has_bam and r.get("SeqType") != "SE":
            problems.append(f"samplesheet line {i}: BAM input must have SeqType SE")
    for lib, samples in libs.items():
        if len(samples) > 1:
            problems.append(f"samplesheet: Library_ID '{lib}' is used by several samples ({', '.join(sorted(samples))})")
    for dup in sorted({x for x in lanes if lanes.count(x) > 1 and x[0]}):
        problems.append(f"samplesheet: lane {dup[1]} of library '{dup[0]}' appears more than once")
    for key in ("single_end", "udg_type", "single_stranded", "colour_chemistry"):
        if key in params:
            problems.append(f"param '{key}' must not be set: the samplesheet (TSV) defines it per library")
    if "fasta" not in params and "genome" not in params:
        problems.append("set 'fasta' (a reference from the catalogue) or 'genome'")
    return problems


def check_methylseq(rows, params):
    problems = []
    presets = [k for k in ("pbat", "rrbs", "em_seq", "single_cell", "zymo", "accel") if params.get(k) is True]
    if len(presets) > 1:
        problems.append(f"set at most one library-prep preset (got {', '.join(presets)})")
    if params.get("taps") is True and params.get("aligner", "bismark") != "bwamem":
        problems.append("TAPS data ('taps=true') needs aligner=bwamem")
    for idx in ("bismark_index", "bwameth_index"):
        if params.get(idx) and not params.get("fasta"):
            problems.append(f"'{idx}' needs the matching 'fasta'")
    return problems


EXTRA_CHECKS = {"sarek": check_sarek, "isoseq": check_isoseq, "taxprofiler": check_taxprofiler, "mag": check_mag,
                "chipseq": check_chipseq, "atacseq": check_atacseq, "ampliseq": check_ampliseq,
                "nanoseq": check_nanoseq, "eager": check_eager, "methylseq": check_methylseq}


def matrix_samples(path):
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
    return [h for h in header if h not in ("gene_id", "gene_name", "transcript_id", "")]


def check_de(sheet_text, params, contrasts_text, profile, upstream):
    entry = REGISTRY["differentialabundance"]
    problems = []
    if profile not in entry["profiles"]:
        problems.append(f"analysis profile must be one of {list(entry['profiles'])} (got '{profile}')")
    for key in ("matrix", "gtf"):
        if not params.get(key):
            problems.append(f"param '{key}' is required")
    for key in ("matrix", "feature_length_matrix", "gtf"):
        value = params.get(key)
        if isinstance(value, str) and value and not os.path.isfile(value):
            problems.append(f"param '{key}' points to a file that does not exist: {value}")

    header, rows = parse_sheet(sheet_text)
    if "sample" not in header:
        problems.append(f"observations sheet: column 'sample' is missing (header is: {','.join(header)})")
    samples = [r.get("sample", "") for r in rows]
    for s in sorted({s for s in samples if samples.count(s) > 1}):
        problems.append(f"observations sheet: sample '{s}' appears more than once")
    for i, r in enumerate(rows, start=2):
        for col in header:
            if not r.get(col):
                problems.append(f"observations sheet line {i}: '{col}' is empty")
    matrix = params.get("matrix")
    if isinstance(matrix, str) and os.path.isfile(matrix):
        in_matrix = matrix_samples(matrix)
        for s in sorted(set(samples) - set(in_matrix)):
            problems.append(f"observations sheet: sample '{s}' is not a column of the count matrix")
        for s in sorted(set(in_matrix) - set(samples)):
            problems.append(f"count matrix column '{s}' has no row in the observations sheet")
        lengths = params.get("feature_length_matrix")
        if isinstance(lengths, str) and os.path.isfile(lengths) and matrix_samples(lengths) != in_matrix:
            problems.append("feature_length_matrix columns differ from the count matrix columns")

    c_header, contrasts = parse_sheet(contrasts_text or "")
    for col in ("id", "variable", "reference", "target"):
        if col not in c_header:
            problems.append(f"contrasts: required column '{col}' is missing (header is: {','.join(c_header)})")
    if not contrasts:
        problems.append("contrasts: at least one contrast is required")
    ids = [c.get("id", "") for c in contrasts]
    for i, c in enumerate(contrasts, start=2):
        cid, var = c.get("id", ""), c.get("variable", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", cid or "") or ids.count(cid) > 1:
            problems.append(f"contrasts line {i}: id '{cid}' must be unique and use only letters, digits, '_', '.', '-'")
        if var not in header or var == "sample":
            problems.append(f"contrasts line {i}: variable '{var}' is not a column of the observations sheet")
            continue
        levels = [r.get(var) for r in rows]
        for side in ("reference", "target"):
            level = c.get(side, "")
            n = levels.count(level)
            if n < 2:
                problems.append(f"contrasts line {i}: {side} level '{level}' of '{var}' has {n} sample(s); at least 2 needed"
                                f" (levels present: {', '.join(sorted(set(levels)))})")
        if c.get("reference") == c.get("target"):
            problems.append(f"contrasts line {i}: reference and target are the same")
        for block in filter(None, (c.get("blocking") or "").split(";")):
            if block not in header:
                problems.append(f"contrasts line {i}: blocking variable '{block}' is not a column of the observations sheet")
            elif block == var:
                problems.append(f"contrasts line {i}: blocking variable '{block}' is the contrast variable itself")

    if upstream:
        try:
            up_params = parse_params(read_text(os.path.join(upstream, "plan_params.json")))
        except ValueError:
            up_params = {}
        if up_params.get("gtf") and params.get("gtf") != up_params["gtf"]:
            problems.append(f"param 'gtf' must be the annotation used by the upstream run: {up_params['gtf']}")
    return problems


def check_plan(pipeline, sheet_text, params_text, contrasts_text=None, profile=None, upstream=None):
    if pipeline not in REGISTRY:
        return [f"pipeline must be one of {sorted(REGISTRY)} (got '{pipeline}')"], {}
    problems, params = check_params(pipeline, params_text)
    if REGISTRY[pipeline].get("downstream"):
        problems += check_de(sheet_text, params, contrasts_text, (profile or "").strip(), upstream)
    else:
        problems += check_fastq_sheet(pipeline, sheet_text, params)
        if (contrasts_text or "").strip():
            problems.append(f"nf-core/{pipeline} takes no contrasts")
    return problems, params


# ---------------------------------------------------------------- plan files, approval and the plan-diff gate

def plan_files(run_dir):
    return list(BASE_FILES) + [f for f in PART_FILES.values() if os.path.isfile(os.path.join(run_dir, f))]


def approve(run_dir, approver):
    missing = [f for f in BASE_FILES if not os.path.isfile(os.path.join(run_dir, f))]
    if missing:
        print(f"Cannot approve: missing plan files {missing}")
        return 1
    record = {"approved_by": approver, "approved_at": time.strftime("%F %T"),
              "sha256": {f: sha256(os.path.join(run_dir, f)) for f in plan_files(run_dir)}}
    json.dump(record, open(os.path.join(run_dir, "APPROVED"), "w"), indent=2)
    state = os.path.join(run_dir, "gate_state.json")
    if os.path.exists(state):
        os.remove(state)  # a new approval restarts the attempt history
    print(f"Plan approved by {approver}.")
    return 0


def approved_plan(run_dir):
    """Return the approved plan as a dict, or raise ValueError."""
    path = os.path.join(run_dir, "APPROVED")
    if not os.path.isfile(path):
        raise ValueError("the plan has not been approved by a person (run `geth approve`)")
    hashes = json.load(open(path))["sha256"]
    for f in set(plan_files(run_dir)) | set(hashes):
        p = os.path.join(run_dir, f)
        if not os.path.isfile(p) or sha256(p) != hashes.get(f):
            raise ValueError(f"{f} changed after approval; it must be approved again")
    read = lambda f: read_text(os.path.join(run_dir, f))
    try:
        params = parse_params(read("plan_params.json"))
    except ValueError as e:
        raise ValueError(f"the approved plan_params.json is not valid ({e}); a person must fix the plan and "
                         f"approve it again. Stop and report this.") from None
    return {"pipeline": pipeline_name(read("plan_pipeline.txt")), "sheet": read("plan_samplesheet.csv"),
            "params": params, "contrasts": read(PART_FILES["contrasts"]), "profile": read(PART_FILES["profile"]).strip()}


def load_state(run_dir, plan):
    path = os.path.join(run_dir, "gate_state.json")
    if os.path.isfile(path):
        return json.load(open(path))
    return {"sheet": plan["sheet"], "params": plan["params"], "error": None}


def mentioned(name, text):
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text or "") is not None


def gate(run_dir, pipeline, sheet_text, params_text, contrasts_text="", profile=""):
    try:
        plan = approved_plan(run_dir)
        params = parse_params(params_text)
    except ValueError as e:
        return [str(e)]
    problems = []
    if pipeline != plan["pipeline"]:
        problems.append(f"pipeline must stay '{plan['pipeline']}' as approved (got '{pipeline}')")
        return problems
    # 1. Experimental design: frozen exactly as approved.
    _, plan_rows = parse_sheet(plan["sheet"])
    _, rows = parse_sheet(sheet_text)
    if design_of(pipeline, rows) != design_of(pipeline, plan_rows):
        cols = REGISTRY[pipeline]["design"]
        before = {row_key(pipeline, r): r for r in plan_rows}
        after = {row_key(pipeline, r): r for r in rows}
        for k in sorted(set(before) | set(after)):
            b, a = before.get(k), after.get(k)
            name = os.path.basename(k or "?")
            if b is None:
                problems.append(f"design change: {name} was added")
            elif a is None:
                problems.append(f"design change: {name} was removed")
            else:
                for col in (cols or sorted(set(a) | set(b))):
                    if b.get(col, "") != a.get(col, ""):
                        problems.append(f"design change: {col} of {name} changed from '{b.get(col, '')}' to '{a.get(col, '')}'")
    if REGISTRY[pipeline].get("downstream"):
        if normalised_csv(contrasts_text) != normalised_csv(plan["contrasts"]):
            problems.append("design change: the contrasts differ from the approved plan")
        if (profile or "").strip() != plan["profile"]:
            problems.append(f"design change: analysis profile must stay '{plan['profile']}' (got '{profile}')")

    state = load_state(run_dir, plan)
    error = state.get("error") or {}
    text = error.get("text", "")

    # 2. Other samplesheet columns may change only if the previous error names them.
    if REGISTRY[pipeline]["design"] is not None:
        _, base_rows = parse_sheet(state["sheet"])
        base = {row_key(pipeline, r): r for r in base_rows}
        for row in rows:
            old = base.get(row_key(pipeline, row), {})
            for col in sorted((set(row) | set(old)) - set(REGISTRY[pipeline]["design"])):
                if row.get(col, "") != old.get(col, "") and not mentioned(col, text):
                    problems.append(f"samplesheet column '{col}' changed for {os.path.basename(row_key(pipeline, row) or '?')} "
                                    f"('{old.get(col, '')}' -> '{row.get(col, '')}') but the previous error does not mention it")

    # 3. Params may change only where the previous error points.
    old = state["params"]
    added = sorted(set(params) - set(old))
    removed = sorted(set(old) - set(params))
    changed = sorted(k for k in set(params) & set(old) if params[k] != old[k])
    if error.get("kind") == "check":
        unknown = set(error.get("unknown", []))
        renames = error.get("suggestions", {})
        for k in removed:
            if k not in unknown and not mentioned(k, text):
                problems.append(f"param '{k}' was removed but the previous error does not mention it")
        for k in added:
            sources = [u for u in removed if k in renames.get(u, []) and old.get(u) == params[k]]
            if not sources:
                problems.append(f"param '{k}' was added; after a plan-check error only a misspelt param may be "
                                f"renamed to a suggested name, keeping its value")
        for k in changed:
            if not mentioned(k, text):
                problems.append(f"param '{k}' changed ({old[k]!r} -> {params[k]!r}) but the previous error does not mention it")
    else:
        for k in added + removed + changed:
            if not mentioned(k, text):
                what = "added" if k in added else "removed" if k in removed else f"changed ({old[k]!r} -> {params[k]!r})"
                problems.append(f"param '{k}' was {what} but the previous error does not mention it"
                                + ("" if text else " (the approved plan must be launched unchanged first)"))
    return problems


def save_plan(run_dir, pipeline, sheet_text, params_text, rationale, contrasts_text="", profile="", upstream=""):
    """Write the planner's proposal as plan_* files. If it fails the plan check but an earlier version
    passed CHECK_PLAN during planning, keep that checked version instead (and say so)."""
    pipeline = pipeline_name(pipeline)
    problems, params = check_plan(pipeline, sheet_text, params_text, contrasts_text, profile, upstream)
    note = ""
    checked = os.path.join(run_dir, ".checked")
    if problems and os.path.isdir(checked):
        read = lambda f: read_text(os.path.join(checked, f))
        c = {"pipeline": pipeline_name(read("plan_pipeline.txt")), "sheet": read("plan_samplesheet.csv"),
             "params": read("plan_params.json"), "contrasts": read(PART_FILES["contrasts"]),
             "profile": read(PART_FILES["profile"]).strip()}
        c_problems, c_parsed = check_plan(c["pipeline"], c["sheet"], c["params"], c["contrasts"], c["profile"], upstream)
        if not c_problems:
            note = ("\n\nNote from Geth: the planner's final answer did not pass the plan check ("
                    + "; ".join(problems) + "). The last version that passed CHECK_PLAN during planning is used.")
            pipeline, sheet_text, params, problems = c["pipeline"], c["sheet"], c_parsed, []
            contrasts_text, profile = c["contrasts"], c["profile"]
    write = lambda f, s: open(os.path.join(run_dir, f), "w").write(s.strip() + "\n")
    write("plan_pipeline.txt", pipeline)
    write("plan_samplesheet.csv", sheet_text)
    write("plan_params.json", json.dumps(params, indent=2) if params or not problems else params_text)
    write("plan_rationale.txt", rationale.strip() + note)
    if REGISTRY.get(pipeline, {}).get("downstream"):
        write(PART_FILES["contrasts"], contrasts_text or "")
        write(PART_FILES["profile"], profile or "")
        if upstream:
            write(PART_FILES["upstream"], upstream)
    result = "PLAN CHECK: OK" if not problems else f"PLAN CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems)
    write("plan_check.txt", result + ("\n(checked version used)" if note else ""))
    return result + ("\n(checked version used)" if note else "")


def save_checked(run_dir, pipeline, sheet_text, params, contrasts_text="", profile=""):
    checked = os.path.join(run_dir, ".checked")
    os.makedirs(checked, exist_ok=True)
    open(os.path.join(checked, "plan_pipeline.txt"), "w").write(pipeline + "\n")
    open(os.path.join(checked, "plan_samplesheet.csv"), "w").write(sheet_text.strip() + "\n")
    json.dump(params, open(os.path.join(checked, "plan_params.json"), "w"), indent=2)
    open(os.path.join(checked, PART_FILES["contrasts"]), "w").write((contrasts_text or "").strip() + "\n")
    open(os.path.join(checked, PART_FILES["profile"]), "w").write((profile or "").strip() + "\n")


def record(run_dir, kind, sheet_text, params_text, error_text=""):
    plan = approved_plan(run_dir)
    state = load_state(run_dir, plan)
    state["sheet"], state["params"] = sheet_text, parse_params(params_text)
    if kind == "ok":
        state["error"] = None
    else:
        err = {"kind": kind, "text": error_text}
        if kind == "check":
            err["unknown"] = re.findall(r"param '([^']+)' does not exist", error_text)
            err["suggestions"] = {m.group(1): [s.strip() for s in m.group(2).split(",")]
                                  for m in re.finditer(r"param '([^']+)' does not exist[^\n]*\(closest: ([^)]*)\)", error_text)}
        state["error"] = err
    json.dump(state, open(os.path.join(run_dir, "gate_state.json"), "w"), indent=2)


# ---------------------------------------------------------------- CLI

def take(argv, flag):
    """Remove `flag value` from argv; return (value or None, argv)."""
    if flag in argv:
        i = argv.index(flag)
        return argv[i + 1], argv[:i] + argv[i + 2:]
    return None, argv


def parts(argv):
    contrasts, argv = take(argv, "--contrasts")
    profile, argv = take(argv, "--profile")
    upstream, argv = take(argv, "--upstream")
    return {"contrasts_text": read_text(contrasts), "profile": profile or "", "upstream": upstream or ""}, argv


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check-plan":
        save_dir, argv = take(argv, "--save-checked")
        extra, argv = parts(argv)
        pipeline = pipeline_name(argv[2])
        sheet_text = open(argv[3]).read()
        problems, params = check_plan(pipeline, sheet_text, open(argv[4]).read(), **extra)
        if problems:
            print(f"PLAN CHECK: {len(problems)} problem(s)")
            print("\n".join(f"- {p}" for p in problems))
            return 1
        if len(argv) > 5:
            json.dump(params, open(argv[5], "w"), indent=2)
        if save_dir:
            save_checked(save_dir, pipeline, sheet_text, params, extra["contrasts_text"], extra["profile"])
        print("PLAN CHECK: OK")
        return 0
    if cmd == "save-plan":
        extra, argv = parts(argv)
        print(save_plan(argv[2], argv[3], open(argv[4]).read(), open(argv[5]).read(), open(argv[6]).read(), **extra))
        return 0
    if cmd == "approve":
        return approve(argv[2], argv[3] if len(argv) > 3 else getpass.getuser())
    if cmd == "gate":
        extra, argv = parts(argv)
        problems = gate(argv[2], pipeline_name(argv[3]), open(argv[4]).read(), open(argv[5]).read(),
                        extra["contrasts_text"], extra["profile"])
        if problems:
            print("\n".join(f"- {p}" for p in problems))
            return 1
        return 0
    if cmd == "record":
        error_text = open(argv[6]).read() if len(argv) > 6 else ""
        record(argv[2], argv[3], open(argv[4]).read(), open(argv[5]).read(), error_text)
        return 0
    if cmd == "runtime":  # shell assignments for run_nfcore.sh
        entry = REGISTRY.get(pipeline_name(argv[2]) if len(argv) > 2 else "", {})
        print(f"pipeline_nxf_ver={entry.get('nextflow', '')}")
        print(f"pipeline_java_home={entry.get('java_home', '')}")
        print(f"pipeline_input_format={entry.get('input_format', 'csv')}")
        print(f"pipeline_legacy_limits={'1' if entry.get('legacy_limits') else ''}")
        return 0
    if cmd == "revision":
        name = pipeline_name(argv[2]) if len(argv) > 2 else ""
        if name not in REGISTRY:
            print(f"pipeline must be one of {sorted(REGISTRY)} (got '{name}')")
            return 1
        print(REGISTRY[name]["revision"])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
