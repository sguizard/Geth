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
  geth_checks.py record <run_dir> <ok|check|nextflow|analysis> <samplesheet.csv> <params.json> [<error.txt>]
      Store an accepted attempt as the new baseline, with the error that may justify the next change.
  geth_checks.py revision <pipeline>
      Print the pinned revision of a pipeline (exit 1 if Geth does not run it).
  geth_checks.py normalise-sheet <in.csv> <out.csv>
      Rewrite a samplesheet with every column on every row.
  geth_checks.py runtime <pipeline>
      Print shell assignments for the pipeline's runtime (pinned Nextflow, Java, input format, extra config).

Exit status 0 = OK, 1 = problems (described on stdout).
"""
import csv
import difflib
import getpass
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMAS = os.path.join(HERE, "..", "schemas")
OWNED = ("input", "outdir", "contrasts", "cellranger_multi_barcodes", "custom_config_base",
         "custom_config_version", "config_profile_name")  # set by Geth only

# Pipelines Geth runs. "design" = samplesheet columns that define the experiment and may never change
# after approval (None = every column); "design_params" = parameters that describe the data, frozen the same
# way. Downstream pipelines also need contrasts and an analysis profile. "fixed_params" are added at launch.
REGISTRY = {
    # "star": the STAR version the release uses; a reused star_index must have been built with it.
    "rnaseq": {"revision": "3.27.0", "design": ("sample", "fastq_1", "fastq_2"), "key": "fastq_1", "star": "2.7.11b"},
    # Multiplexed 10x libraries (OCM, CellPlex/CMO, Flex) need Cell Ranger multi and a second sheet that lists
    # each library's samples by barcode: part of the design, frozen like the samplesheet.
    "scrnaseq": {"revision": "4.2.0", "design": ("sample", "fastq_1", "fastq_2", "feature_type"), "key": "fastq_1",
                 "star": "2.7.11b", "design_params": ("protocol", "aligner"),
                 "second_sheet": {"file": "plan_barcodes.csv", "param": "cellranger_multi_barcodes",
                                  "what": "the multiplexed samples sheet"}},
    "sarek": {"revision": "3.10.0", "design": ("patient", "sample", "status", "lane", "fastq_1", "fastq_2", "bam", "cram"),
              "key": ("fastq_1", "bam", "cram", "spring_1", "vcf")},
    "isoseq": {"revision": "3.0.1", "design": ("sample", "seq_data", "start_from"), "key": "seq_data",
               "required_params": ("aligner", "fasta")},
    "taxprofiler": {"revision": "2.0.1", "design": ("sample", "run_accession", "fastq_1", "fastq_2", "fasta"),
                    "key": ("fastq_1", "fasta"), "required_params": ("databases",)},
    "mag": {"revision": "5.5.0", "design": ("sample", "run", "group", "short_reads_1", "short_reads_2", "long_reads"),
            "key": ("short_reads_1", "long_reads")},
    # ampliseq 3.0.0 declares config_profile_name as a non-optional String: nf-core's test profile sets it.
    "ampliseq": {"revision": "3.0.0", "design": ("sample", "run", "fastq_1", "fastq_2"), "key": "fastq_1",
                 "design_params": ("primer_fwd", "primer_rev"), "fixed_params": {"config_profile_name": "Geth"}},
    # Older templates define functions in nextflow.config, which Nextflow 26's strict config parser rejects.
    "chipseq": {"revision": "2.1.0", "key": "fastq_1", "nxf_env": {"NXF_SYNTAX_PARSER": "v1"},
                "design": ("sample", "replicate", "antibody", "control", "control_replicate", "fastq_1", "fastq_2")},
    "atacseq": {"revision": "2.1.2", "key": "fastq_1", "nxf_env": {"NXF_SYNTAX_PARSER": "v1"},
                "design": ("sample", "replicate", "control", "control_replicate", "fastq_1", "fastq_2")},
    # nanoseq uses the `echo` process directive, removed from recent Nextflow.
    "nanoseq": {"revision": "3.1.0", "design": ("group", "replicate", "barcode", "input_file"), "nextflow": "23.10.4",
                "extra_config": "legacy_singularity.config",
                "key": ("input_file", "barcode"), "required_params": ("protocol",), "design_params": ("protocol",)},
    "methylseq": {"revision": "4.2.0", "design": ("sample", "fastq_1", "fastq_2"), "key": "fastq_1",
                  "nxf_env": {"NXF_SYNTAX_PARSER": "v1"},
                  "design_params": ("rrbs", "pbat", "em_seq", "single_cell", "zymo", "accel", "cegx", "epignome",
                                    "swift", "taps", "non_directional")},
    # eager 2.5.3 is DSL1: run with an older Nextflow (and Java 17, from GETH_JAVA17_HOME), TSV input,
    # max_* resource params.
    "eager": {"revision": "2.5.3", "key": ("R1", "BAM"), "nextflow": "22.10.8",
              "java": 17, "input_format": "tsv", "legacy_limits": True,
              "extra_config": "legacy_singularity.config",
              "design": ("Sample_Name", "Library_ID", "Lane", "SeqType", "Strandedness", "UDG_Treatment", "R1", "R2", "BAM")},
    "differentialabundance": {
        "revision": "2.0.0", "design": None, "key": "sample", "downstream": True, "follows": "rnaseq",
        "second_sheet": {"file": "plan_contrasts.csv", "param": "contrasts", "what": "the contrasts"},
        "profiles": ("rnaseq", "rnaseq_deseq2_gprofiler2", "rnaseq_deseq2_gsea", "rnaseq_limma"),
    },
    # Geth's own single-cell toolbox (bin/sc_downstream.py): the agents design, the toolbox executes.
    "sc_downstream": {"revision": "1.0.0", "design": ("sample", "h5ad"), "key": "sample", "toolbox": True,
                      "follows": "scrnaseq"},
}

# The single-cell design menu: key -> (type, low or choices, high, required).
SC_MENU = {
    "qc.min_genes": ("int", 0, 5000, True),
    "qc.max_genes": ("int", 0, 50000, False),
    "qc.min_counts": ("int", 0, 100000, False),
    "qc.max_counts": ("int", 0, 1000000, False),
    "qc.max_pct_mt": ("float", 1, 100, True),
    "qc.min_cells_per_gene": ("int", 0, 100, False),
    "doublets.method": ("choice", ("scrublet", "none"), None, True),
    "doublets.expected_rate": ("float", 0.0, 0.3, False),
    "doublets.threshold": ("float_or_auto", 0.01, 0.95, False),
    "normalize.target_sum": ("int", 1000, 1000000, False),
    "hvg.n_top_genes": ("int", 200, 10000, False),
    "hvg.flavor": ("choice", ("seurat", "cell_ranger"), None, False),
    "scale": ("bool", None, None, False),
    "pca.n_comps": ("int", 5, 100, False),
    "neighbors.n_neighbors": ("int", 3, 100, False),
    "neighbors.n_pcs": ("int", 3, 100, False),
    "leiden.resolutions": ("list_float", 0.05, 3.0, True),
    "leiden.chosen": ("float", 0.05, 3.0, True),
    "markers.method": ("choice", ("wilcoxon", "t-test", "logreg"), None, False),
    "markers.n_genes": ("int", 3, 50, False),
    "markers.panel": ("list_str", 1, 40, True),
    "annotation.model": ("model", None, None, True),
    "annotation.majority_voting": ("bool", None, None, False),
    "justification": ("str", None, None, False),
}
# What the analyst may revise after seeing the diagnostics (once). Input matrix, normalisation,
# annotation model and marker panel stay as approved.
SC_TUNABLE = {"qc.min_genes", "qc.max_genes", "qc.min_counts", "qc.max_counts", "qc.max_pct_mt",
              "qc.min_cells_per_gene", "doublets.expected_rate", "doublets.threshold", "hvg.n_top_genes",
              "neighbors.n_neighbors", "neighbors.n_pcs", "leiden.resolutions", "leiden.chosen", "justification"}
SC_DIAGNOSTIC_TERMS = ("cells kept", "removed", "doublet", "cluster", "smallest", "agreement", "celltypist",
                       "pct_counts_mt", "n_genes", "total_counts", "marker", "resolution")
# Reference catalogue (genomes, CellTypist models), from the site configuration (env.sh sets it).
REFERENCES = os.environ.get("GETH_REFERENCES", "").rstrip("/")
BASE_FILES = ("plan_pipeline.txt", "plan_samplesheet.csv", "plan_params.json")
PART_FILES = {"contrasts": "plan_contrasts.csv", "barcodes": "plan_barcodes.csv", "profile": "plan_profile.txt",
              "upstream": "plan_upstream.txt"}


def sheet2_file(pipeline):
    """The plan file of a pipeline's second sheet (contrasts, multiplexed samples); internally "contrasts"."""
    return REGISTRY.get(pipeline, {}).get("second_sheet", {}).get("file", PART_FILES["contrasts"])


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
    if REGISTRY[pipeline].get("toolbox"):
        return set(SC_MENU)
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
    params, rest = {}, text
    if text.startswith("{"):  # a JSON object, possibly followed by key=value lines (e.g. justification=...)
        params, end = json.JSONDecoder().raw_decode(text)
        if not isinstance(params, dict):
            raise ValueError("params must be a JSON object")
        rest = text[end:]
    if rest.strip():
        for line in rest.splitlines():
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


def normalise_sheet(text):
    """The samplesheet as CSV with every header column on every row (trailing empty fields kept)."""
    header, rows = parse_sheet(text)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for r in rows:
        writer.writerow([r.get(h, "") for h in header])
    return out.getvalue()


def launch_params(pipeline, params):
    """The parameters given to the pipeline: the plan's plus the ones Geth always sets."""
    return dict(params, **REGISTRY.get(pipeline, {}).get("fixed_params", {}))


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
    problems += check_star_index(pipeline, params)
    return problems, params


def check_star_index(pipeline, params):
    """A reused STAR index must come from the reference catalogue (geth_index.json, written by
    references/register_star_index.sh) and match the release's STAR version and the plan's FASTA and GTF."""
    index, star = params.get("star_index"), REGISTRY[pipeline].get("star")
    if not index or not star:
        return []
    aligner = str(params.get("aligner", "star_salmon" if pipeline == "rnaseq" else "simpleaf"))
    if not aligner.startswith("star"):
        return [f"param 'star_index' is only used with a STAR aligner (aligner is '{aligner}')"]
    info_path = os.path.join(str(index), "geth_index.json")
    if not os.path.isfile(info_path):
        return [f"param 'star_index' must be an index registered in the reference catalogue (no geth_index.json in "
                f"{index}); use one listed by LIST_REFERENCES, or leave star_index unset to build one"]
    with open(info_path) as fh:
        info = json.load(fh)
    problems = []
    if info.get("version") != star:
        problems.append(f"param 'star_index' was built with STAR {info.get('version')}, but nf-core/{pipeline} "
                        f"{REGISTRY[pipeline]['revision']} uses STAR {star}: leave star_index unset to build a matching index")
    for key in ("fasta", "gtf"):
        if params.get(key) != info.get(key):
            problems.append(f"param 'star_index' was built from {key} {info.get(key)}: set '{key}' to that file "
                            f"(got {params.get(key)!r}), or leave star_index unset")
    return problems


# Pipelines that cannot run without a reference: what they accept instead of fasta+gtf (a planner once left
# rnaseq without any reference, judging the delivery's test genome too small: the run would fail at launch).
NEEDS_REFERENCE = {"rnaseq": ("fasta", "gtf"), "scrnaseq": ("fasta", "gtf"), "chipseq": ("fasta",),
                   "atacseq": ("fasta",), "methylseq": ("fasta",), "sarek": ("fasta",)}


def mate_of(name):
    """The expected second-read file name of a first-read file, for the usual naming patterns (else None)."""
    for one, two in (("_R1_", "_R2_"), ("_R1.", "_R2."), ("_1.f", "_2.f"), (".R1.", ".R2."), ("_r1.", "_r2.")):
        if one in name:
            i = name.rindex(one)
            return name[:i] + two + name[i + len(one):]
    return None


def check_fastq_sheet(pipeline, sheet_text, params):
    problems = []
    if pipeline in ("rnaseq", "scrnaseq") and "genome" in params and ("fasta" in params or "gtf" in params):
        problems.append("set either 'genome' or 'fasta'/'gtf', not both")
    needed = NEEDS_REFERENCE.get(pipeline)
    if needed and not params.get("genome") and not all(params.get(k) for k in needed) \
            and not any(k.endswith("_index") and params.get(k) for k in params):
        problems.append(f"nf-core/{pipeline} needs a reference: set 'genome', or {' and '.join(repr(k) for k in needed)} "
                        "(from the delivery or the reference catalogue). If none fits, say so in the rationale and "
                        "ask the scientist")

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
    for i, row in enumerate(rows, start=2):
        f1, f2 = os.path.basename(row.get("fastq_1") or ""), os.path.basename(row.get("fastq_2") or "")
        mate = mate_of(f1) if f1 and f2 else None
        if mate and f2 != mate:
            problems.append(f"samplesheet line {i}: fastq_2 '{f2}' is not the mate of fastq_1 '{f1}' "
                            f"(expected '{mate}'): a pair must come from the same library and lane")
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
    fasta = params.get("fasta")
    if isinstance(fasta, str) and fasta.endswith(".gz") and os.path.isfile(fasta) and not is_bgzip(fasta):
        problems.append("sarek cannot index a gzip-compressed 'fasta': use the uncompressed FASTA of the catalogue entry")
    sites = [params.get(k) for k in ("dbsnp", "known_indels", "known_snps") if params.get(k)]
    if len(sites) != len(set(sites)):
        problems.append("'dbsnp', 'known_indels' and 'known_snps' must be different files: sarek stages them together "
                        "and the same file twice collides. Give a single known-variants VCF as 'dbsnp' only")
    custom = not params.get("genome") or params.get("igenomes_ignore") is True
    skipped = set(filter(None, str(params.get("skip_tools", "")).split(",")))
    if step == "mapping" and custom and "baserecalibrator" not in skipped and not params.get("dbsnp") \
            and not params.get("known_indels"):
        problems.append("base recalibration needs known sites with a custom genome: set 'dbsnp' (and "
                        "'known_indels') from the catalogue, or skip_tools=baserecalibrator")
    if "vep" in tools and custom:
        keys = ("vep_cache", "vep_species", "vep_genome", "vep_cache_version")
        missing = [k for k in keys if not params.get(k)]
        if missing:
            problems.append(f"'vep' with a custom genome needs {', '.join(missing)} (from the catalogue entry's VEP cache)")
        else:
            folder = os.path.join(str(params["vep_cache"]), str(params["vep_species"]),
                                  f"{params['vep_cache_version']}_{params['vep_genome']}")
            if not os.path.isdir(folder):
                problems.append(f"VEP cache folder not found: {folder} (check vep_species, vep_genome, vep_cache_version)")
    return problems


def is_bgzip(path):
    """True for a BGZF (block-gzip) file, which samtools and GATK can index; plain gzip they cannot."""
    with open(path, "rb") as fh:
        head = fh.read(18)
    return len(head) == 18 and head[:2] == b"\x1f\x8b" and bool(head[3] & 4) and head[12:14] == b"BC"


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
    size = sum(os.path.getsize(r["seq_data"]) for r in rows if os.path.isfile(r.get("seq_data", "")))
    if any(r.get("start_from") == "ccs" for r in rows) and size < 2e9 and int(params.get("chunk_ccs", 40)) > 5:
        problems.append(f"small input ({size / 1e6:.0f} MB of subreads): set 'chunk_ccs' to 5 or fewer; with the "
                        "default 40 chunks most chunks are empty and the TAMA merge step fails")
    return problems


def db_rows(params):
    """Rows of the taxprofiler databases sheet (empty when there is none)."""
    db = params.get("databases")
    if not (isinstance(db, str) and os.path.isfile(db)):
        return []
    with open(db) as fh:
        return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(fh)]


def kraken2_index_bytes(params):
    """Size of the largest Kraken2 index of the databases sheet: Kraken2 loads it in RAM."""
    sizes = [os.path.getsize(os.path.join(r["db_path"], "hash.k2d")) for r in db_rows(params)
             if r.get("tool") in ("kraken2", "bracken") and os.path.isfile(os.path.join(r.get("db_path", ""), "hash.k2d"))]
    return max(sizes, default=0)


def reference_bytes(pipeline, params):
    """How large the reference data of a plan is (decides the resource caps): genome, prebuilt index, databases."""
    if params.get("genome") or params.get("star_index"):
        return 10 ** 10  # an iGenomes genome or a prebuilt index: assume a large genome
    fasta = params.get("fasta") or ""
    size = os.path.getsize(fasta) * (3 if fasta.endswith(".gz") else 1) if fasta.startswith("/") and os.path.isfile(fasta) else 0
    return max(size, kraken2_index_bytes(params))


def extra_resources(pipeline, params):
    """Nextflow config for jobs whose memory depends on the data, e.g. Kraken2 loads its whole index in RAM."""
    index = kraken2_index_bytes(params) if pipeline == "taxprofiler" else 0
    if not index:
        return ""
    return "process {\n    withName: '.*KRAKEN2_KRAKEN2.*' {\n        memory = %d.GB\n    }\n}\n" % (index / 1e9 * 1.15 + 8)


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
    merge_pairs = params.get("perform_shortread_qc") is True and params.get("shortread_qc_mergepairs") is True
    if params.get("perform_runmerging") is True and not merge_pairs:
        layouts = {}  # single_end as taxprofiler defines it: one short-read file
        for r in rows:
            single = bool(r.get("fastq_1")) and not r.get("fastq_2") \
                and r.get("instrument_platform") not in ("OXFORD_NANOPORE", "PACBIO_SMRT")
            layouts.setdefault(r.get("sample"), set()).add(single)
        for sample in sorted(s for s, l in layouts.items() if len(l) > 1):
            problems.append(f"sample '{sample}' mixes single-end short-read runs with other runs: merging its runs needs read pairs "
                            "merged first (perform_shortread_qc=true and shortread_qc_mergepairs=true), or no run merging")
    names = [r.get("db_name", "") for r in db_rows(params) if r.get("tool") in ("kraken2", "bracken")]
    for name in sorted({n for n in names if names.count(n) > 1}):
        problems.append(f"databases sheet: db_name '{name}' is used by both kraken2 and bracken; taxprofiler needs a "
                        "name unique across both tools, even for the same database (e.g. add '_bracken')")
    for i, r in enumerate(db_rows(params), start=2):
        path, tool = r.get("db_path", ""), r.get("tool", "")
        if not os.path.exists(path):
            problems.append(f"databases sheet line {i}: db_path does not exist: {path}")
        elif tool in ("kraken2", "bracken") and os.path.isdir(path) and not os.path.isfile(os.path.join(path, "hash.k2d")):
            problems.append(f"databases sheet line {i}: {path} is not a Kraken2 database (no hash.k2d)")
        elif tool == "bracken" and os.path.isdir(path):
            m = re.search(r"-r\s*(\d+)", r.get("db_params", ""))
            if m and not os.path.isfile(os.path.join(path, f"database{m.group(1)}mers.kmer_distrib")):
                problems.append(f"databases sheet line {i}: no Bracken distribution for read length {m.group(1)} in {path}")
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
    if params.get("skip_gtdbtk") is not True and not params.get("gtdb_db"):
        problems.append("GTDB-Tk would download its database (over 100 GB) at run time: set 'gtdb_db' from the "
                        "reference catalogue, or skip_gtdbtk=true")
    if params.get("cat_db_generate") is True:
        problems.append("'cat_db_generate' downloads NCBI nr (hundreds of GB): use 'cat_db' from the catalogue, or leave CAT off")
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


def fasta_contigs(path, max_bytes=500_000_000):
    """Contig names of a local FASTA, from its .fai or by reading the headers of a file small enough to scan
    quickly (None when they cannot be known cheaply)."""
    if not isinstance(path, str) or not os.path.isfile(path):
        return None
    for fai in (path + ".fai", re.sub(r"\.gz$", "", path) + ".fai"):
        if os.path.isfile(fai):
            with open(fai) as fh:
                return [line.split("\t", 1)[0] for line in fh if line.strip()]
    if os.path.getsize(path) > max_bytes:
        return None
    with (gzip.open(path, "rt") if path.endswith(".gz") else open(path)) as fh:
        return [line[1:].split()[0] for line in fh if line.startswith(">") and line[1:].strip()]


def check_mito_name(params):
    """ATAC-seq: mitochondrial reads are removed only if mito_name names the reference's mitochondrial contig."""
    if params.get("genome") or params.get("keep_mito") is True:
        return []
    contigs = fasta_contigs(params.get("fasta"))
    if contigs is None:
        return []
    mito = params.get("mito_name")
    if mito and mito not in contigs:
        return [f"'mito_name' '{mito}' is not a contig of the reference FASTA; its contigs are: "
                f"{', '.join(contigs[:40])}{' ...' if len(contigs) > 40 else ''}"]
    likely = [c for c in contigs if c.lower() in ("mt", "chrm", "mito", "chrmt", "m", "mitochondrion")]
    if not mito and likely:
        return [f"set 'mito_name' to the reference's mitochondrial contig ('{likely[0]}') so that mitochondrial "
                "reads are removed (or keep_mito=true to keep them)"]
    return []


def check_atacseq(rows, params):
    problems = check_replicates(rows, "samplesheet") + check_mito_name(params)
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
    meta = params.get("metadata")
    if isinstance(meta, str) and os.path.isfile(meta):
        with open(meta) as fh:
            header = [h.strip() for h in fh.readline().rstrip("\n").split("\t")]
            ids = [line.split("\t")[0].strip() for line in fh if line.strip()]
        samples = {r.get("sample") for r in rows}
        if header[0] != "ID":
            problems.append(f"metadata: its first column must be named 'ID' and hold the sample names (got '{header[0]}')")
        unknown = sorted(set(ids) - samples)
        if unknown or not set(ids) & samples:
            problems.append(f"metadata IDs must be sample names of the samplesheet (not found: {', '.join(unknown[:10])}). "
                            "Geth cannot rewrite a delivery's metadata: name the samples as the metadata IDs if those "
                            "are valid sample names, or leave 'metadata' unset and say so in the rationale")
        for cat in filter(None, str(params.get("metadata_category") or "").split(",")):
            if cat.strip() not in header:
                problems.append(f"'metadata_category' '{cat.strip()}' is not a column of the metadata ({', '.join(header)})")
    return problems


# nanoseq 3.1.0 demultiplexes with qcat, which names kits its own way (from the schema's help text).
QCAT_KITS = ("Auto", "RBK001", "RBK004", "NBD103/NBD104", "NBD114", "NBD104/NBD114", "PBC001", "PBC096",
             "RPB004/RLB001", "RPB004/LWB001", "RAB204", "VMK001")


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
    elif demux and params.get("barcode_kit") not in QCAT_KITS:
        problems.append(f"'barcode_kit' must be one of qcat's kit names: {', '.join(QCAT_KITS)} "
                        f"(e.g. NBD103/NBD104 for the EXP-NBD103 and EXP-NBD104 native barcoding kits); "
                        f"got '{params.get('barcode_kit')}'")
    if params.get("protocol") not in ("DNA", "cDNA", "directRNA"):
        problems.append("'protocol' must be DNA, cDNA or directRNA")
    if params.get("protocol") == "DNA":
        for key, why in (("skip_quantification", "transcript quantification needs cDNA or directRNA"),
                         ("skip_fusion_analysis", "fusion detection is for RNA")):
            if params.get(key) is not True:
                problems.append(f"with protocol DNA set '{key}=true' ({why})")
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


def sc_value(key, value):
    """Normalise one design value to its menu type; return (value, problem or None)."""
    kind, low, high, _ = SC_MENU[key]
    if kind == "float_or_auto":
        if str(value).strip().lower() == "auto":
            return "auto", None
        kind = "float"
    try:
        if kind == "int":
            v = int(value)
        elif kind == "float":
            v = float(value)
        elif kind == "bool":
            v = value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "1")
            return v, None
        elif kind in ("list_float", "list_str"):
            items = value
            if not isinstance(value, list):  # "0.4,0.8" or "[0.4, 0.8]" (a key=value line holding a JSON list)
                text = str(value).strip()
                try:
                    items = json.loads(text) if text.startswith("[") else text.split(",")
                except ValueError:
                    items = text.strip("[]").split(",")
                items = items if isinstance(items, list) else [items]
            items = [str(x).strip().strip("'\"") for x in items if str(x).strip()]
            v = [float(x) for x in items] if kind == "list_float" else items
        else:
            v = str(value).strip()
    except (TypeError, ValueError):
        return value, f"'{key}' must be {kind.replace('_', ' of ')} (got {value!r})"
    if kind == "choice" and v not in low:
        return v, f"'{key}' must be one of {list(low)} (got '{v}')"
    if kind in ("int", "float") and not low <= v <= high:
        return v, f"'{key}' must be between {low} and {high} (got {v})"
    if kind == "list_float" and (not v or any(not low <= x <= high for x in v)):
        return v, f"'{key}' must be a comma-separated list of values between {low} and {high} (got {value!r})"
    if kind == "list_str" and not low <= len(v) <= high:
        return v, f"'{key}' must list {low} to {high} genes (got {len(v)})"
    if kind == "model" and not (REFERENCES and v.startswith(REFERENCES + "/") and v.endswith(".pkl")
                                and os.path.isfile(v)):
        return v, f"'{key}' must be a CellTypist model file from the reference catalogue ({REFERENCES}/...pkl): {v}"
    return v, None


def check_sc_design(sheet_text, params_text):
    problems = []
    try:
        raw = parse_params(params_text)
    except ValueError as e:
        return [f"design is not valid key=value lines or a JSON object: {e}"], {}
    design = {}
    for key, value in raw.items():
        if key not in SC_MENU:
            close = difflib.get_close_matches(key, SC_MENU, n=3)
            problems.append(f"design key '{key}' is not on the menu" + (f" (closest: {', '.join(close)})" if close else ""))
            continue
        if value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "null")):
            continue  # an empty optional value means "not used"
        design[key], problem = sc_value(key, value)
        if problem:
            problems.append(problem)
    for key, (_, _, _, required) in SC_MENU.items():
        if required and key not in design:
            problems.append(f"design key '{key}' is required")
    if "leiden.chosen" in design and isinstance(design.get("leiden.resolutions"), list) \
            and design["leiden.chosen"] not in design["leiden.resolutions"]:
        problems.append("'leiden.chosen' must be one of 'leiden.resolutions'")
    if design.get("neighbors.n_pcs", 0) > design.get("pca.n_comps", 50):
        problems.append("'neighbors.n_pcs' cannot exceed 'pca.n_comps'")
    for lo, hi in (("qc.min_genes", "qc.max_genes"), ("qc.min_counts", "qc.max_counts")):
        if lo in design and hi in design and design[lo] >= design[hi]:
            problems.append(f"'{lo}' must be smaller than '{hi}'")
    header, rows = parse_sheet(sheet_text)
    if header != ["sample", "h5ad"]:
        problems.append(f"samplesheet must have the columns sample,h5ad (got {','.join(header)})")
    if len(rows) != 1:
        problems.append(f"samplesheet must have exactly one row: one sample per analysis (got {len(rows)})")
    for r in rows:
        h5ad = r.get("h5ad", "")
        if not (h5ad.startswith("/") and h5ad.endswith(".h5ad") and os.path.isfile(h5ad)):
            problems.append(f"h5ad must be an existing .h5ad file given by absolute path: {h5ad}")
        # Cell Ranger multi: a sample's own CellBender run is not valid (its raw matrix lacks the library's empty
        # droplets, so CellBender keeps thousands of empty droplets as cells: 10x_multi_chicken2)
        m = re.search(r"/cellrangermulti/mtx_conversions/([^/]+)/\1_cellbender_filter_matrix\.h5ad$", h5ad)
        if m and not os.path.isdir(os.path.join(h5ad.split("/mtx_conversions/")[0], "count", m.group(1), "outs")):
            problems.append(f"{os.path.basename(h5ad)} is the CellBender run of one sample of a multiplexed library, "
                            "which is not valid (the sample's raw matrix lacks the library's empty droplets). Use "
                            f"the sample's Cell Ranger matrix, {m.group(1)}_filtered_matrix.h5ad, in the same folder")
    return problems, design


def check_plan(pipeline, sheet_text, params_text, contrasts_text=None, profile=None, upstream=None):
    if pipeline not in REGISTRY:
        return [f"pipeline must be one of {sorted(REGISTRY)} (got '{pipeline}')"], {}
    if REGISTRY[pipeline].get("toolbox"):
        problems, design = check_sc_design(sheet_text, params_text)
        if (contrasts_text or "").strip():
            problems.append("the single-cell toolbox takes no contrasts")
        return problems, design
    problems, params = check_params(pipeline, params_text)
    if REGISTRY[pipeline].get("downstream"):
        problems += check_de(sheet_text, params, contrasts_text, (profile or "").strip(), upstream)
    else:
        problems += check_fastq_sheet(pipeline, sheet_text, params)
        if pipeline == "scrnaseq":
            problems += check_multiplexing(sheet_text, params, contrasts_text)
        elif (contrasts_text or "").strip():
            problems.append(f"nf-core/{pipeline} takes no contrasts")
    return problems, params


# ---------------------------------------------------------------- multiplexed 10x, and warnings

DATA_ROOT = os.environ.get("GETH_DATA_ROOT", "").rstrip("/")
# 10x multiplexing: GEM-X On-Chip Multiplexing (OB1-OB4), CellPlex (CMO301...), Flex probe barcodes (BC001...).
MULTIPLEX_STRONG = re.compile(r"10xOCM|\bOCM\b|on[- ]chip multiplex|cellplex|\bCMO\d{3}\b|cell multiplexing oligo|"
                              r"fixed rna profiling|probe barcode", re.I)
MULTIPLEX_TEXT = re.compile(MULTIPLEX_STRONG.pattern + r"|\bOB[1-4]\b|\bBC0\d\d\b|\bflex\b|multiplexed 10x|"
                            r"multiplexed (?:library|libraries)", re.I)
CHEMISTRY = re.compile(r"\bv[1-4](?:\.\d)?\b|gem-?x|next ?gem|single cell [35]'|\b[35]' ?v\d|chemistry", re.I)
GEMX = re.compile(r"gem-?x|\bv4\b|10xOCM|\bOCM\b|on[- ]chip multiplex", re.I)
BARCODE_COLUMNS = ("sample", "multiplexed_sample_id", "probe_barcode_ids", "cmo_ids", "ocm_ids", "description")
FEATURE_TYPES = ("gex", "vdj", "ab", "crispr", "cmo")


def delivery_texts(rows):
    """The delivery's own text files (README, sample tables, the facility's report), from the folder that holds
    the reads up to two levels above it, never above the data area: [(name, text, is_html)]."""
    paths = [r.get(k) for r in rows for k in ("fastq_1", "fastq_2") if (r.get(k) or "").startswith("/")]
    if not paths:
        return []
    folder = os.path.commonpath([os.path.dirname(p) for p in paths])
    found, seen = [], set()
    for _ in range(3):
        if DATA_ROOT and not (folder + "/").startswith(DATA_ROOT + "/"):
            break
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            path = os.path.join(folder, name)
            if path in seen or not os.path.isfile(path) or os.path.getsize(path) > 5_000_000:
                continue
            if name.lower().endswith((".txt", ".md", ".csv", ".tsv", ".html", ".htm")) or name.upper().startswith("README"):
                seen.add(path)
                text = open(path, errors="replace").read()
                html = name.lower().endswith((".html", ".htm"))
                if html:  # reports keep their tables in script data: drop styles and tags only (strong markers)
                    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.S | re.I)
                    text = re.sub(r"<[^>]+>", " ", text)
                found.append((os.path.relpath(path, DATA_ROOT) if DATA_ROOT else name, text, html))
        if DATA_ROOT and folder == DATA_ROOT:
            break
        folder = os.path.dirname(folder)
    return found


def multiplexing_evidence(texts):
    hits = []
    for name, text, html in texts:
        found = sorted({m.group(0) for m in (MULTIPLEX_STRONG if html else MULTIPLEX_TEXT).finditer(text)})
        if found:
            hits.append(f"{name}: {', '.join(found[:4])}")
    return hits


def check_multiplexing(sheet_text, params, barcodes_text):
    """nf-core/scrnaseq: a library that holds several samples (OCM, CellPlex, Flex) is split into its samples only
    by Cell Ranger multi, with a barcodes sheet (the plan's second sheet); a plain 10x plan would mix them."""
    problems = []
    _, rows = parse_sheet(sheet_text)
    aligner = params.get("aligner", "simpleaf")
    evidence = multiplexing_evidence(delivery_texts(rows))
    barcodes_text = (barcodes_text or "").strip()
    if aligner != "cellrangermulti":
        if evidence:
            problems.append("the delivery describes multiplexed 10x libraries (" + "; ".join(evidence) + "): each "
                            "library holds several samples, which only Cell Ranger multi separates. Set "
                            "aligner=cellrangermulti, give each library's FASTQs one sample name with feature_type gex, "
                            "and list each library's samples in the second sheet (contrasts_lines: sample, "
                            "multiplexed_sample_id, probe_barcode_ids, cmo_ids, ocm_ids, description)")
        if barcodes_text:
            problems.append("a multiplexed-samples sheet is only used with aligner=cellrangermulti")
        return problems
    samples = {r.get("sample") for r in rows}
    for i, r in enumerate(rows, start=2):
        if r.get("feature_type") not in FEATURE_TYPES:
            problems.append(f"samplesheet line {i}: Cell Ranger multi needs feature_type, one of {list(FEATURE_TYPES)}")
    if not any(r.get("feature_type") == "vdj" for r in rows) and params.get("skip_cellrangermulti_vdjref") not in (True, "true"):
        problems.append("no VDJ data: set skip_cellrangermulti_vdjref=true (the pipeline would build a VDJ reference "
                        "it does not need, which fails for most species)")
    if params.get("protocol", "auto") != "auto":
        problems.append("set protocol=auto: with Cell Ranger multi, protocol is passed to Cell Ranger as a fixed "
                        "chemistry, and the multiplexed chemistries cannot be named that way (On-Chip Multiplexing "
                        "is detected as \"Single Cell 3' v4 OCM\"; 10XV3 would force v3). Cell Ranger detects the "
                        "chemistry itself. If the scientist named a kit, say in the rationale why it is not set")
    if evidence and not barcodes_text:
        problems.append("the delivery describes multiplexed libraries (" + "; ".join(evidence) + "): list each "
                        "library's samples in the second sheet (contrasts_lines)")
    if not barcodes_text:
        return problems
    header, brows = parse_sheet(barcodes_text)
    if header != list(BARCODE_COLUMNS):
        problems.append(f"multiplexed samples sheet: the header must be {','.join(BARCODE_COLUMNS)} (got {','.join(header)})")
        return problems
    seen, kinds = {}, {}
    for i, b in enumerate(brows, start=2):
        where = f"multiplexed samples line {i}"
        if b["sample"] not in samples:
            problems.append(f"{where}: sample '{b['sample']}' is not a sample of the samplesheet ({', '.join(sorted(samples))})")
        sid = b["multiplexed_sample_id"]
        if not sid or re.search(r"\s", sid):
            problems.append(f"{where}: multiplexed_sample_id must be given, without spaces")
        elif sid in seen:
            problems.append(f"{where}: multiplexed_sample_id '{sid}' is already used on line {seen[sid]}")
        seen[sid] = i
        if not b["description"]:
            problems.append(f"{where}: description is required")
        given = [k for k in ("probe_barcode_ids", "cmo_ids", "ocm_ids") if b[k]]
        if len(given) != 1:
            problems.append(f"{where}: give exactly one of probe_barcode_ids, cmo_ids, ocm_ids (got {len(given)})")
            continue
        kinds.setdefault(b["sample"], set()).add(given[0])
        if given[0] == "ocm_ids" and not re.fullmatch(r"OB[1-4](\|OB[1-4])*", b["ocm_ids"]):
            problems.append(f"{where}: ocm_ids must be OB1, OB2, OB3 or OB4 (got '{b['ocm_ids']}')")
        if given[0] == "cmo_ids" and not re.fullmatch(r"[A-Za-z0-9_|-]+", b["cmo_ids"]):
            problems.append(f"{where}: cmo_ids may only hold letters, digits, '_', '-' and '|' (got '{b['cmo_ids']}')")
    for sample, k in kinds.items():
        if len(k) > 1:
            problems.append(f"multiplexed samples: '{sample}' mixes {sorted(k)}; one kind of barcode per library")
        if "cmo_ids" in k and not any(r.get("sample") == sample and r.get("feature_type") == "cmo" for r in rows):
            problems.append(f"multiplexed samples: '{sample}' uses CMOs, so its CMO capture FASTQs need a samplesheet row "
                            "with feature_type cmo")
        if "probe_barcode_ids" in k and not params.get("gex_frna_probe_set"):
            problems.append("Flex (probe barcodes) needs the probe set: gex_frna_probe_set")
    for sample in samples - set(kinds):
        if evidence:
            problems.append(f"multiplexed samples: library '{sample}' has no rows: list its samples and barcodes")
    return problems


def sample_entries(texts):
    """Lines of the delivery's text files that look like a table of samples ("<id>,<value>"): their first column."""
    entries = []
    for _, text, html in texts:
        if html:
            continue
        blocks, block = [], []  # runs of consecutive table-like lines
        for line in text.splitlines() + [""]:
            m = re.match(r"^\s*([A-Za-z0-9][\w.+-]*)\s*[,\t;]\s*\S", line)
            if m:
                block.append((line, m.group(1)))
            elif block:
                blocks.append(block)
                block = []
        for block in (b for b in blocks if len(b) > 1):  # a table has rows; a lone line is prose
            # a header line: no digit, above rows that have some ("rat,ocm_barcode" over "rat_1,OB1")
            if len(block) > 1 and not re.search(r"\d", block[0][0]) and any(re.search(r"\d", l) for l, _ in block[1:]):
                block = block[1:]
            entries += [e for _, e in block if e.lower() not in ("sample", "samples", "id", "name", "sample_id", "file", "barcode")]
    return list(dict.fromkeys(entries))


# ---------------------------------------------------------------- what the reads say

IUPAC = {"A": "A", "C": "C", "G": "G", "T": "T", "U": "T", "R": "[AG]", "Y": "[CT]", "S": "[CG]", "W": "[AT]",
         "K": "[GT]", "M": "[AC]", "B": "[CGT]", "D": "[AGT]", "H": "[ACT]", "V": "[ACG]", "N": "[ACGT]"}
_HEADS = {}


def fastq_head(path, n=2000):
    """The sequences of a FASTQ's first reads (cached: a plan is checked many times while planning)."""
    if path not in _HEADS:
        seqs = []
        try:
            opener = gzip.open if path.endswith(".gz") else open
            with opener(path, "rt", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i % 4 == 1:
                        seqs.append(line.strip().upper())
                        if len(seqs) >= n:
                            break
        except (OSError, EOFError):
            pass
        _HEADS[path] = seqs
    return _HEADS[path]


def share(seqs, test):
    return sum(1 for x in seqs if test(x)) / len(seqs) if seqs else None


def data_warnings(pipeline, rows, params):
    """When the reads themselves can say whether a plan value (often the scientist's answer) is right."""
    warnings = []
    def fq(key, most=8):  # the first file of each sample (mixed libraries differ: ChIP inputs vs IPs)
        firsts = {}
        for r in rows:
            path = r.get(key) or ""
            sample = r.get("sample") or r.get("Sample_Name") or path
            if path.startswith("/") and sample not in firsts and os.path.isfile(path):
                firsts[sample] = path
        return list(firsts.values())[:most]
    median_len = lambda path: (sorted(map(len, fastq_head(path))) or [0])[len(fastq_head(path)) // 2]
    if pipeline == "ampliseq" and params.get("primer_fwd") and params.get("primer_rev"):
        try:
            fwd = re.compile("^" + "".join(IUPAC[c] for c in str(params["primer_fwd"]).upper()))
            rev = re.compile("^" + "".join(IUPAC[c] for c in str(params["primer_rev"]).upper()))
        except KeyError:
            fwd = rev = None
        r1, r2 = fq("fastq_1"), fq("fastq_2")
        if fwd and r1:
            at_fwd = min(share(fastq_head(f), fwd.match) for f in r1)
            at_rev = min(share(fastq_head(f), rev.match) for f in r2) if r2 else None
            swapped = r2 and share(fastq_head(r2[0]), fwd.match) > 0.3
            if params.get("skip_cutadapt") in (True, "true"):
                if at_fwd > 0.5:
                    warnings.append(f"cutadapt is skipped, but the forward primer starts {at_fwd:.0%} of the reads: "
                                    "the primers are still in the reads")
            elif swapped:
                warnings.append("the forward primer starts the second reads (fastq_2): primer_fwd and primer_rev, or "
                                "fastq_1 and fastq_2, look swapped")
            elif at_fwd < 0.3 or (at_rev is not None and at_rev < 0.3):
                warnings.append(f"the primers start few reads (forward {at_fwd:.0%} of first reads"
                                + (f", reverse {at_rev:.0%} of second reads" if at_rev is not None else "")
                                + "; correct primers usually start most of them): check the sequences, or whether "
                                "the primers were already removed (skip_cutadapt)")
    if pipeline == "scrnaseq" and params.get("aligner", "simpleaf") not in ("cellranger", "cellrangermulti"):
        protocol, r1 = str(params.get("protocol", "")).upper(), fq("fastq_1")
        if r1 and protocol in ("10XV2", "10XV3", "10XV4"):
            length = median_len(r1[0])
            if protocol == "10XV2" and length == 28:
                warnings.append("protocol=10XV2, but the barcode reads (fastq_1) are 28 bp, as in v3/v3.1 and "
                                "GEM-X v4 (v2: 26 bp): check the chemistry")
            elif protocol in ("10XV3", "10XV4") and length == 26:
                warnings.append(f"protocol={protocol}, but the barcode reads (fastq_1) are 26 bp, as in v2 (v3 and "
                                "GEM-X v4: 28 bp): check the chemistry")
    if pipeline == "methylseq":
        r1 = fq("fastq_1")
        if r1:
            rrbs_like = share(fastq_head(r1[0]), lambda x: x[:3] in ("CGG", "TGG"))
            if params.get("rrbs") in (True, "true") and rrbs_like < 0.3:
                warnings.append(f"rrbs=true, but only {rrbs_like:.0%} of the reads start with CGG/TGG (an RRBS "
                                "library's MspI site): check the protocol")
            elif params.get("rrbs") not in (True, "true") and rrbs_like > 0.6:
                warnings.append(f"{rrbs_like:.0%} of the reads start with CGG/TGG, as in RRBS libraries, but rrbs "
                                "is not set: check the protocol")
    if pipeline in ("chipseq", "atacseq") and params.get("read_length"):
        allowed = (50, 75, 100, 150, 200)
        lengths = sorted({median_len(f) for f in fq("fastq_1")} - {0})
        nearest = {min(allowed, key=lambda a: abs(a - L)) for L in lengths}
        if nearest and int(float(params["read_length"])) not in nearest:
            warnings.append(f"read_length={params['read_length']}, but the reads are {', '.join(f'{L} bp' for L in lengths)} "
                            f"(nearest allowed: {', '.join(map(str, sorted(nearest)))})")
    return warnings


def scientist_answers(run_dir):
    """The scientist's answers to the planner (plan_questions.md), as one text."""
    path = os.path.join(run_dir or "", "plan_questions.md")
    if not run_dir or not os.path.isfile(path):
        return ""
    return "\n".join(l[len("- answer:"):].strip() for l in open(path) if l.startswith("- answer:"))


def plan_warnings(pipeline, sheet_text, params, sheet2_text="", run_dir=""):
    """Things a person should check before approving; they do not block the plan."""
    if REGISTRY.get(pipeline, {}).get("downstream") or REGISTRY.get(pipeline, {}).get("toolbox"):
        return []
    warnings = []
    header, rows = parse_sheet(sheet_text)
    texts = delivery_texts(rows)
    planned = {r.get("sample") for r in rows if r.get("sample")}
    if pipeline == "scrnaseq" and (sheet2_text or "").strip():
        _, brows = parse_sheet(sheet2_text)
        planned = {b.get("multiplexed_sample_id") for b in brows} or planned
    # Each entry should appear somewhere in the plan (a sample name, a file name, a barcodes row); replicates
    # and lanes grouped under one sample name are fine, since their files carry the entry's name.
    plan_text = sheet_text + (sheet2_text or "") + json.dumps(params)
    entries = sample_entries(texts)
    missing = [e for e in entries  # a whole name: "s3" is not in ".../tmp_ab3s3x/...", "ATAC01" is in "ATAC01_S1_..."
               if not re.search(rf"(?<![A-Za-z0-9]){re.escape(e)}(?![A-Za-z0-9])", plan_text)]
    if missing:
        warnings.append(f"the delivery's text lists {len(entries)} entries that look like samples, and "
                        f"{len(missing)} of them appear nowhere in the plan ({', '.join(missing[:6])}"
                        f"{', ...' if len(missing) > 6 else ''}); the plan has {len(planned)} sample(s) "
                        f"({', '.join(sorted(planned)[:6])}{', ...' if len(planned) > 6 else ''}): check that "
                        "every sample is accounted for")
    if pipeline == "scrnaseq" and params.get("aligner", "simpleaf") not in ("cellranger", "cellrangermulti"):
        protocol = str(params.get("protocol", ""))
        said = " ".join(t for _, t, _ in texts)
        if protocol.upper().startswith("10XV") and not CHEMISTRY.search(said):
            warnings.append(f"the plan sets protocol={protocol}, but the delivery never states the 10x chemistry: check "
                            "it (GEM-X kits are 10XV4), or use Cell Ranger, which detects it (protocol=auto)")
        elif protocol.upper() == "10XV3" and GEMX.search(said):
            warnings.append("the delivery mentions GEM-X chemistry, but the plan sets protocol=10XV3: GEM-X 3' is 10XV4")
    warnings += data_warnings(pipeline, rows, params)
    # An answer of the scientist that the delivery itself rules out (10x_multi_chicken8: "v3/v3.1" for OCM data)
    answers = scientist_answers(run_dir)
    if pipeline == "scrnaseq" and answers and (sheet2_text or "").strip():
        _, brows = parse_sheet(sheet2_text)
        if any(b.get("ocm_ids") for b in brows) and re.search(r"\bv3(\.1)?\b|next ?gem", answers, re.I) \
                and not re.search(r"gem-?x|\bv4\b", answers, re.I):
            warnings.append("an answer gives a v3/v3.1 chemistry, but On-Chip Multiplexing (OB1-OB4) exists only with "
                            "GEM-X Universal 3' v4: check the kit. The plan is not affected: Cell Ranger multi "
                            "detects the chemistry (protocol=auto)")
    return warnings


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
    pipeline = pipeline_name(read("plan_pipeline.txt"))
    return {"pipeline": pipeline, "sheet": read("plan_samplesheet.csv"),
            "params": params, "contrasts": read(sheet2_file(pipeline)), "profile": read(PART_FILES["profile"]).strip()}


def load_state(run_dir, plan):
    path = os.path.join(run_dir, "gate_state.json")
    if os.path.isfile(path):
        return json.load(open(path))
    return {"sheet": plan["sheet"], "params": plan["params"], "error": None}


def mentioned(name, text):
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text or "") is not None


# Option names too common to tie an error to one parameter (deseq2_vs_method is not named by "a method").
GENERIC_OPTIONS = {"method", "type", "mode", "file", "path", "name", "value", "size", "args", "options", "blind",
                   "test", "level", "list", "data", "format", "version", "skip", "save", "output", "input"}


def names_tool_option(name, text):
    """An error from a tool that names one of its options: deseq2_vst_nsub, after DESEQ2_DIFFERENTIAL failed with
    "less than 'nsub' rows". The parameter's first word is the tool, its last the option (4+ letters, not generic)."""
    parts = name.lower().split("_")
    tool, option, low = parts[0], parts[-1], (text or "").lower()
    return (len(parts) >= 2 and len(tool) >= 3 and len(option) >= 4 and option not in GENERIC_OPTIONS
            and re.search(rf"(?<![a-z0-9]){re.escape(tool)}", low) is not None
            and re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", low) is not None)


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
    sheet2 = REGISTRY[pipeline].get("second_sheet")
    if sheet2:  # contrasts, multiplexed samples: part of the design
        if normalised_csv(contrasts_text) != normalised_csv(plan["contrasts"]):
            problems.append(f"design change: {sheet2['what']} differ{'' if sheet2['what'].endswith('s') else 's'} "
                            "from the approved plan")
    elif (contrasts_text or "").strip():
        problems.append(f"nf-core/{pipeline} takes no contrasts: pass an empty string")
    if REGISTRY[pipeline].get("downstream"):
        if (profile or "").strip() != plan["profile"]:
            problems.append(f"design change: analysis profile must stay '{plan['profile']}' (got '{profile}')")
    elif (profile or "").strip():
        problems.append(f"nf-core/{pipeline} takes no analysis profile: pass an empty string")
    for key in REGISTRY[pipeline].get("design_params", ()):
        if params.get(key) != plan["params"].get(key):
            problems.append(f"design change: param '{key}' describes the data and must stay "
                            f"{plan['params'].get(key)!r} as approved (got {params.get(key)!r})")

    state = load_state(run_dir, plan)
    error = state.get("error") or {}
    text = error.get("text", "")

    if REGISTRY[pipeline].get("toolbox"):
        return problems + sc_gate(plan, params, state)

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
            if not mentioned(k, text) and not skips_named_step(k, params.get(k), text) \
                    and not names_its_file(old.get(k), text) and not skips_named_tools(k, old.get(k), params.get(k), text) \
                    and not names_tool_option(k, text):
                what = "added" if k in added else "removed" if k in removed else f"changed ({old[k]!r} -> {params[k]!r})"
                problems.append(f"param '{k}' was {what} but the previous error does not mention it"
                                + ("" if text else " (the approved plan must be launched unchanged first)"))
        same_sheet = normalised_csv(sheet_text) == normalised_csv(state["sheet"])
        if error.get("kind") == "nextflow" and same_sheet and not (added or removed or changed) \
                and state.get("repeats", 0) >= 1:
            problems.append("this exact attempt has already failed twice: change what the error points to, "
                            "or stop and report the error")
    return problems


def names_step(name, error_text):
    """Does the error name this step or tool? A name of 4+ letters may be part of a process name (preseq in
    PRESEQ_LCEXTRAP); a 3-letter one must stand alone (the ALE process, not 'ALEoutput.txt' or '.gtf')."""
    text = error_text or ""
    if len(name) >= 4:
        return re.search(re.escape(name), text, re.I) is not None
    return len(name) == 3 and re.search(rf"(?<![A-Za-z0-9./]){re.escape(name)}(?![A-Za-z0-9./])", text, re.I) is not None


def skips_named_step(key, value, error_text):
    """skip_<step>=true is the minimal fix when the error names that step (e.g. skip_preseq after a
    PRESEQ_LCEXTRAP failure, skip_ale after an ALE crash)."""
    if not key.startswith("skip_") or value not in (True, "true"):
        return False
    step = key[len("skip_"):]
    first = step.split("_")[0]
    return names_step(step, error_text) or (len(first) >= 4 and names_step(first, error_text))


def skips_named_tools(key, old, new, error_text):
    """A list of skipped tools (sarek's skip_tools) may gain the tools the error names."""
    if key != "skip_tools":
        return False
    before = set(filter(None, str(old or "").split(",")))
    added = set(filter(None, str(new or "").split(","))) - before
    return bool(added) and before <= set(str(new).split(",")) and all(names_step(t, error_text) for t in added)


def names_its_file(old_value, error_text):
    """A file parameter may change when the error names its file (e.g. a file staged twice)."""
    if not (isinstance(old_value, str) and "/" in old_value):
        return False
    name = os.path.basename(old_value)
    return len(name) >= 6 and name in (error_text or "")


def sc_gate(plan, params_text_or_dict, state):
    """Single-cell toolbox: the first analysis runs the approved design unchanged; one revision of the
    tunable keys is allowed afterwards, with a justification that cites the diagnostics."""
    problems, design = check_sc_design("sample,h5ad\nx,/dev/null.h5ad", json.dumps(params_text_or_dict))
    problems = [p for p in problems if "h5ad" not in p and "samplesheet" not in p]
    if problems:
        return problems
    _, approved = check_sc_design("sample,h5ad\nx,/dev/null.h5ad", json.dumps(plan["params"]))
    strip = lambda d: {k: v for k, v in d.items() if k != "justification"}
    done = state.get("analyses", 0)
    changed = sorted(k for k in set(strip(design)) | set(strip(approved)) if design.get(k) != approved.get(k))
    if done == 0:
        return [f"design key '{k}' differs from the approved design; run the approved design first" for k in changed]
    if done >= 2:
        return ["only one revision of the approved design is allowed; stop and report"]
    out = [f"design key '{k}' cannot be revised (not tunable)" for k in changed if k not in SC_TUNABLE]
    reason = str(design.get("justification", "")).lower()
    if changed and not any(term in reason for term in SC_DIAGNOSTIC_TERMS):
        out.append("a revision needs justification=... citing the diagnostics (e.g. cells kept, doublet rate, "
                   "cluster sizes, CellTypist agreement)")
    if not changed:
        out.append("the revision is identical to the previous analysis; stop and report")
    return out


def sc_merge(run_dir, submitted_text):
    """A revision of the single-cell design may name only the keys it changes (and justification=...): it is
    applied to the approved design. A whole design, or text that does not parse (the gate says why), is kept."""
    try:
        submitted = parse_params(submitted_text)
    except ValueError:
        return submitted_text
    required = {k for k, (_, _, _, req) in SC_MENU.items() if req}
    if required <= set(submitted):
        return submitted_text
    approved = parse_params(read_text(os.path.join(run_dir, "plan_params.json")))
    return json.dumps({**approved, **submitted}, indent=2)


def save_plan(run_dir, pipeline, sheet_text, params_text, rationale, contrasts_text="", profile="", upstream=""):
    """Write the planner's proposal as plan_* files. If it fails the plan check but an earlier version
    passed CHECK_PLAN during planning, keep that checked version instead (and say so)."""
    pipeline = pipeline_name(pipeline)
    problems, params = check_plan(pipeline, sheet_text, params_text, contrasts_text, profile, upstream)
    note = ""
    checked = os.path.join(run_dir, ".checked")
    if problems and os.path.isdir(checked):
        read = lambda f: read_text(os.path.join(checked, f))
        c_pipeline = pipeline_name(read("plan_pipeline.txt"))
        c = {"pipeline": c_pipeline, "sheet": read("plan_samplesheet.csv"),
             "params": read("plan_params.json"), "contrasts": read(sheet2_file(c_pipeline)),
             "profile": read(PART_FILES["profile"]).strip()}
        c_problems, c_parsed = check_plan(c["pipeline"], c["sheet"], c["params"], c["contrasts"], c["profile"], upstream)
        if not c_problems:
            note = ("\n\nNote from Geth: the planner's final answer did not pass the plan check ("
                    + "; ".join(problems) + "). The last version that passed CHECK_PLAN during planning is used.")
            pipeline, sheet_text, params, problems = c["pipeline"], c["sheet"], c_parsed, []
            contrasts_text, profile = c["contrasts"], c["profile"]
    write = lambda f, s: open(os.path.join(run_dir, f), "w").write(s.strip() + "\n")
    write("plan_pipeline.txt", pipeline)
    write("plan_samplesheet.csv", normalise_sheet(sheet_text))
    write("plan_params.json", json.dumps(params, indent=2) if params or not problems else params_text)
    write("plan_rationale.txt", rationale.strip() + note)
    if REGISTRY.get(pipeline, {}).get("downstream"):
        write(sheet2_file(pipeline), contrasts_text or "")
        write(PART_FILES["profile"], profile or "")
        if upstream:
            write(PART_FILES["upstream"], upstream)
    elif (contrasts_text or "").strip() and "second_sheet" in REGISTRY.get(pipeline, {}):
        write(sheet2_file(pipeline), contrasts_text)
    result = "PLAN CHECK: OK" if not problems else f"PLAN CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems)
    if not problems and isinstance(params, dict):
        result += "".join(f"\nWARNING: {w}" for w in plan_warnings(pipeline, sheet_text, params, contrasts_text, run_dir))
    write("plan_check.txt", result + ("\n(checked version used)" if note else ""))
    return result + ("\n(checked version used)" if note else "")


def save_checked(run_dir, pipeline, sheet_text, params, contrasts_text="", profile=""):
    checked = os.path.join(run_dir, ".checked")
    os.makedirs(checked, exist_ok=True)
    open(os.path.join(checked, "plan_pipeline.txt"), "w").write(pipeline + "\n")
    open(os.path.join(checked, "plan_samplesheet.csv"), "w").write(normalise_sheet(sheet_text))
    json.dump(params, open(os.path.join(checked, "plan_params.json"), "w"), indent=2)
    open(os.path.join(checked, sheet2_file(pipeline)), "w").write((contrasts_text or "").strip() + "\n")
    open(os.path.join(checked, PART_FILES["profile"]), "w").write((profile or "").strip() + "\n")


def record(run_dir, kind, sheet_text, params_text, error_text=""):
    plan = approved_plan(run_dir)
    state = load_state(run_dir, plan)
    new_params = parse_params(params_text)
    same = normalised_csv(sheet_text) == normalised_csv(state["sheet"]) and new_params == state["params"]
    state["repeats"] = state.get("repeats", 0) + 1 if kind == "nextflow" and same and state.get("error") else 0
    state["sheet"], state["params"] = sheet_text, new_params
    if kind == "analysis":  # single-cell toolbox: count analyses, keep the diagnostics as the reference
        state["analyses"] = state.get("analyses", 0) + 1
        state["error"] = {"kind": "diagnostics", "text": error_text}
    elif kind == "ok":
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


LITERAL = r"'(?:[^'\\]|\\.)*'"  # a single-quoted string as `nextflow config -flat` prints it


def keep_prelude(flat):
    """A pipeline's own beforeScript for some processes (scrnaseq 4.2.0: CELLRANGER_MULTI, to turn telemetry off)
    replaces the site's, which may be what puts the container engine on the jobs' PATH (Eddie: module load
    apptainer). From the resolved configuration (`nextflow config -flat`), a config that runs the site's
    beforeScript first, then the pipeline's, for each such process selector. Empty when nothing is replaced."""
    generic, specific = None, []
    for line in flat.splitlines():
        m = re.match(rf"^process\.beforeScript = ({LITERAL})\s*$", line)
        if m:
            generic = m.group(1)
            continue
        m = re.match(rf"^process\.'(withName|withLabel):([^']+)'\.beforeScript = ({LITERAL})\s*$", line)
        if m:
            specific.append(m.groups())
    if not generic or not generic.strip("'").replace("\\n", "").strip():
        return ""
    lines = [f"    {kind}: '{name}' {{ beforeScript = {generic} + '\\n' + {value} }}"
             for kind, name, value in specific if generic.strip("'") not in value]
    return "process {\n" + "\n".join(lines) + "\n}\n" if lines else ""


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check-plan":
        save_dir, argv = take(argv, "--save-checked")
        run_dir, argv = take(argv, "--run-dir")  # for the warnings that read the scientist's answers
        extra, argv = parts(argv)
        pipeline = pipeline_name(argv[2])
        sheet_text = open(argv[3]).read()
        problems, params = check_plan(pipeline, sheet_text, open(argv[4]).read(), **extra)
        if problems:
            print(f"PLAN CHECK: {len(problems)} problem(s)")
            print("\n".join(f"- {p}" for p in problems))
            return 1
        if len(argv) > 5:
            json.dump(launch_params(pipeline, params), open(argv[5], "w"), indent=2)
        if save_dir:
            save_checked(save_dir, pipeline, sheet_text, params, extra["contrasts_text"], extra["profile"])
        print("PLAN CHECK: OK")
        for w in plan_warnings(pipeline, sheet_text, params, extra["contrasts_text"], save_dir or run_dir or ""):
            print(f"WARNING: {w}")
        return 0
    if cmd == "keep-prelude":  # keep-prelude < flat config: a config restoring the site's beforeScript (see above)
        sys.stdout.write(keep_prelude(sys.stdin.read()))
        return 0
    if cmd == "command":  # command <run_dir>: the nf-core command line of the plan, as Geth will launch it
        run_dir = argv[2]
        read = lambda f: read_text(os.path.join(run_dir, f)).strip()
        pipeline = pipeline_name(read("plan_pipeline.txt"))
        spec = REGISTRY.get(pipeline, {})
        if spec.get("toolbox"):
            print(f"(Geth's single-cell toolbox: the design in plan_params.json, run by sc_analyse.sh)")
            return 0
        try:
            params = parse_params(read("plan_params.json"))
        except ValueError as e:
            print(f"(plan_params.json is not valid: {e})")
            return 0
        profiles = ",".join(p for p in (os.environ.get("GETH_NFCORE_PROFILE", ""), read("plan_profile.txt")) if p)
        words = [f"nextflow run nf-core/{pipeline} -r {spec.get('revision', '?')}"]
        if profiles:
            words.append(f"-profile {profiles}")
        words.append(f"--input {os.path.join(run_dir, 'plan_samplesheet.csv')}")
        sheet2 = spec.get("second_sheet")
        if sheet2 and read(sheet2["file"]):
            words.append(f"--{sheet2['param']} {os.path.join(run_dir, sheet2['file'])}")
        words.append(f"--outdir {os.path.join(run_dir, 'results')}")
        for key, value in params.items():
            value = json.dumps(value) if isinstance(value, (dict, list)) else str(value).lower() if isinstance(value, bool) else str(value)
            words.append(f"--{key} {value if re.fullmatch(r'[\w./:,+=@-]+', value) else repr(value)}")
        print(" \\\n    ".join(words))
        return 0
    if cmd == "sheet2":  # sheet2 <pipeline>: "<nf-core parameter> <file name>" of the plan's second sheet, if any
        spec = REGISTRY.get(pipeline_name(argv[2]), {}).get("second_sheet")
        if spec:
            print(spec["param"], spec["file"].replace("plan_", ""))
        return 0
    if cmd == "normalise-sheet":  # normalise-sheet <in.csv> <out.csv>
        text = open(argv[2]).read()
        open(argv[3], "w").write(normalise_sheet(text))
        return 0
    if cmd == "save-plan":
        extra, argv = parts(argv)
        print(save_plan(argv[2], argv[3], open(argv[4]).read(), open(argv[5]).read(), open(argv[6]).read(), **extra))
        return 0
    if cmd == "approve":
        return approve(argv[2], argv[3] if len(argv) > 3 else getpass.getuser())
    if cmd == "sc-merge":  # sc-merge <run_dir> <submitted design> <out>: a partial revision on the approved design
        open(argv[4], "w").write(sc_merge(argv[2], open(argv[3]).read()))
        return 0
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
    if cmd == "reference-size":  # reference-size <pipeline> <params.json>: bytes, for the resource caps
        print(reference_bytes(pipeline_name(argv[2]), parse_params(read_text(argv[3]))))
        return 0
    if cmd == "resources":  # resources <pipeline> <params.json>: extra Nextflow config (may be empty)
        sys.stdout.write(extra_resources(pipeline_name(argv[2]), parse_params(read_text(argv[3]))))
        return 0
    if cmd == "runtime":  # shell assignments for run_nfcore.sh
        entry = REGISTRY.get(pipeline_name(argv[2]) if len(argv) > 2 else "", {})
        print(f"pipeline_nxf_ver={entry.get('nextflow', '')}")
        java_home = os.environ.get(f"GETH_JAVA{entry['java']}_HOME", "") if "java" in entry else ""
        print(f"pipeline_java_home={java_home}")
        print(f"pipeline_input_format={entry.get('input_format', 'csv')}")
        print(f"pipeline_legacy_limits={'1' if entry.get('legacy_limits') else ''}")
        print(f"pipeline_extra_config={entry.get('extra_config', '')}")
        print("pipeline_env=(" + " ".join(f"{k}={v}" for k, v in entry.get("nxf_env", {}).items()) + ")")
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
