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
    "differentialabundance": {
        "revision": "2.0.0", "design": None, "key": "sample", "downstream": True,
        "profiles": ("rnaseq", "rnaseq_deseq2_gprofiler2", "rnaseq_deseq2_gsea", "rnaseq_limma"),
    },
    # Geth's own single-cell toolbox (bin/sc_downstream.py): the agents design, the toolbox executes.
    "sc_downstream": {"revision": "1.0.0", "design": ("sample", "h5ad"), "key": "sample", "toolbox": True},
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
    "doublets.threshold": ("float", 0.05, 0.95, False),
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
REFERENCES = os.environ.get("PERSEUS_VEIL", "/exports/eddie/scratch/sguizard/Perseus_Veil") + "/references"
BASE_FILES = ("plan_pipeline.txt", "plan_samplesheet.csv", "plan_params.json")
PART_FILES = {"contrasts": "plan_contrasts.csv", "profile": "plan_profile.txt", "upstream": "plan_upstream.txt"}


# ---------------------------------------------------------------- parsing

def pipeline_name(name):
    return name.strip().replace("nf-core/", "")


def load_schema(pipeline, kind):
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
    return problems, params


def check_fastq_sheet(pipeline, sheet_text, params):
    problems = []
    if "genome" in params and ("fasta" in params or "gtf" in params):
        problems.append("set either 'genome' or 'fasta'/'gtf', not both")
    for key in ("fasta", "gtf", "gff", "transcript_fasta"):
        if isinstance(params.get(key), str) and not os.path.isfile(params[key]):
            problems.append(f"param '{key}' points to a file that does not exist: {params[key]}")

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
            if not value:
                if col in required and not (col == "fastq_2" and pipeline == "rnaseq"):
                    problems.append(f"samplesheet line {i}: '{col}' is empty")
                continue
            if "enum" in spec and value not in spec["enum"]:
                problems.append(f"samplesheet line {i}: '{col}' must be one of {spec['enum']} (got '{value}')")
            if "pattern" in spec and not re.search(spec["pattern"], value):
                problems.append(f"samplesheet line {i}: '{col}' value '{value}' is not valid ({spec.get('errorMessage', 'pattern ' + spec['pattern'])})")
            if spec.get("type") == "integer" and not value.isdigit():
                problems.append(f"samplesheet line {i}: '{col}' must be an integer (got '{value}')")
            if spec.get("format") == "file-path":
                if not value.startswith("/"):
                    problems.append(f"samplesheet line {i}: '{col}' must be an absolute path (got '{value}')")
                elif not os.path.isfile(value):
                    problems.append(f"samplesheet line {i}: '{col}' file does not exist: {value}")
                elif value.endswith(".gz") and open(value, "rb").read(2) != b"\x1f\x8b":
                    problems.append(f"samplesheet line {i}: '{col}' is named .gz but is not gzip-compressed: {value}")
        fq1 = row.get("fastq_1", "")
        if fq1 and fq1 in seen:
            problems.append(f"samplesheet line {i}: fastq_1 already used on line {seen[fq1]}")
        seen[fq1] = i
    if pipeline == "rnaseq":
        layout = {}
        for row in rows:
            layout.setdefault(row.get("sample"), set()).add(bool(row.get("fastq_2")))
        for sample, kinds in layout.items():
            if len(kinds) > 1:
                problems.append(f"samplesheet: sample '{sample}' mixes single-end and paired-end rows")
    return problems


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
    try:
        if kind == "int":
            v = int(value)
        elif kind == "float":
            v = float(value)
        elif kind == "bool":
            v = value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "1")
            return v, None
        elif kind == "list_float":
            v = [float(x) for x in (value if isinstance(value, list) else str(value).split(",")) if str(x).strip()]
        elif kind == "list_str":
            v = [str(x).strip() for x in (value if isinstance(value, list) else str(value).split(",")) if str(x).strip()]
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
    if kind == "model" and not (v.startswith(REFERENCES + "/") and v.endswith(".pkl") and os.path.isfile(v)):
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
    key = REGISTRY[pipeline]["key"]

    # 1. Experimental design: frozen exactly as approved.
    _, plan_rows = parse_sheet(plan["sheet"])
    _, rows = parse_sheet(sheet_text)
    if design_of(pipeline, rows) != design_of(pipeline, plan_rows):
        cols = REGISTRY[pipeline]["design"]
        before = {r.get(key): r for r in plan_rows}
        after = {r.get(key): r for r in rows}
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

    if REGISTRY[pipeline].get("toolbox"):
        return problems + sc_gate(plan, params, state)

    # 2. Other samplesheet columns may change only if the previous error names them.
    if REGISTRY[pipeline]["design"] is not None:
        _, base_rows = parse_sheet(state["sheet"])
        base = {r.get(key): r for r in base_rows}
        for row in rows:
            old = base.get(row.get(key), {})
            for col in sorted((set(row) | set(old)) - set(REGISTRY[pipeline]["design"])):
                if row.get(col, "") != old.get(col, "") and not mentioned(col, text):
                    problems.append(f"samplesheet column '{col}' changed for {os.path.basename(row.get(key, '?'))} "
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
