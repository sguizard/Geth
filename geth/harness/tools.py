"""The planner's tools, as plain Python: the same behaviour and output as the Nextflow tools of geth/main.nf.

They only read under GETH_DATA_ROOT (data, and finished runs for follow-ups) and the reference catalogue, and
only write in the run folder.
"""
import gzip
import os
import subprocess

from .agent import Tool, string_params

GETH_HOME = os.environ.get("GETH_HOME", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CHECKS = os.path.join(GETH_HOME, "geth", "bin", "geth_checks.py")
SC_JOB = os.path.join(GETH_HOME, "geth", "bin", "sc_job.sh")


def under(path, root):
    """Is path inside root (lexically, after normalisation: '..' cannot climb out)?"""
    path = os.path.normpath(path or "")
    return bool(root) and path.startswith(os.path.normpath(root) + "/")


def list_files(data_root):
    def run(dir):
        if not under(dir, data_root):
            return f"REFUSED: only folders under {data_root} can be listed"
        # as `find <dir> -maxdepth 3 \( -type f -o -type l \)`: files and links, 3 levels, links not followed
        found, base = [], os.path.normpath(dir)
        if not os.path.isdir(base):
            return f"NOT FOUND: {dir}"
        for parent, dirs, files in os.walk(base):
            level = 0 if parent == base else parent[len(base) + 1:].count("/") + 1
            for name in files + [d for d in dirs if os.path.islink(os.path.join(parent, d))]:
                p = os.path.join(parent, name)
                try:
                    found.append(f"{p}\t{os.lstat(p).st_size} bytes")
                except OSError:
                    pass
            if level >= 2:
                dirs[:] = []
        return "\n".join(sorted(found)[:300]) or "(empty)"
    return Tool("LIST_FILES", "List the files of a folder (3 levels deep) with their sizes. Only folders under the "
                f"data area ({data_root}) can be listed.", string_params(dir="absolute path of the folder"), run)


def read_text(data_root):
    def run(path):
        if not under(path, data_root):
            return f"REFUSED: only files under {data_root} can be read"
        if not os.path.isfile(path):
            return f"NOT FOUND: {path}"
        if path.endswith(".gz"):
            with open(path, "rb") as fh:
                magic = fh.read(2)
            if magic != b"\x1f\x8b":
                return f"(file type: not gzip-compressed although named .gz)\n"
            try:
                with gzip.open(path, "rt", errors="replace") as fh:
                    lines = [next(fh, "") for _ in range(8)]
            except (OSError, EOFError) as e:
                return f"(file type: gzip compressed data; cannot be read: {e})"
            return "(file type: gzip compressed data; first 8 lines, decompressed)\n" + "".join(lines)
        with open(path, "rb") as fh:
            return fh.read(8000).decode(errors="replace")
    return Tool("READ_TEXT", "Read a text file (the first 8 kB), or the first 8 lines of a .gz file. Only files "
                f"under the data area ({data_root}).", string_params(path="absolute path of the file"), run)


def list_references(references):
    def run(species=""):
        out = []
        for name in sorted(os.listdir(references)) if os.path.isdir(references) else []:
            readme = os.path.join(references, name, "README.txt")
            if os.path.isfile(readme):
                out.append(f"== {os.path.join(references, name)}\n{open(readme).read()}")
        return "\n".join(out) or "The reference catalogue is empty."
    return Tool("LIST_REFERENCES", "List the reference catalogue: genomes, annotations and databases, with their "
                "files and notes.", string_params(species="the species you are looking for"), run)


def scratch(run_dir, **files):
    folder = os.path.join(run_dir, ".harness")
    os.makedirs(folder, exist_ok=True)
    paths = {}
    for name, text in files.items():
        paths[name] = os.path.join(folder, name)
        with open(paths[name], "w") as fh:
            fh.write((text or "").strip() + "\n")
    return paths


def checks(*args):
    result = subprocess.run(["python3", CHECKS, *args], capture_output=True, text=True, timeout=600)
    return (result.stdout + result.stderr).strip()


def check_plan(run_dir, upstream):
    def run(pipeline, samplesheet_csv, params_json, contrasts_csv="", profile=""):
        p = scratch(run_dir, **{"samplesheet.csv": samplesheet_csv, "params.json": params_json,
                                "contrasts.csv": contrasts_csv})
        return checks("check-plan", pipeline, p["samplesheet.csv"], p["params.json"], "--save-checked", run_dir,
                      "--contrasts", p["contrasts.csv"], "--profile", profile.strip(),
                      *(["--upstream", upstream] if upstream else []))
    return Tool("CHECK_PLAN", "Check a plan against the pinned pipeline release: samplesheet, parameters (JSON object "
                "or key=value lines), the second sheet (contrasts, or a multiplexed barcodes sheet; empty string if "
                "none) and the analysis profile (empty string if none). Prints PLAN CHECK: OK, or the problems.",
                string_params(pipeline="pipeline name, e.g. rnaseq", samplesheet_csv="the samplesheet, CSV text",
                              params_json="the parameters", contrasts_csv="the second sheet, CSV text, or ''",
                              profile="analysis profile, or ''"), run, check=True)


def submit_plan(run_dir, upstream):
    def run(pipeline, samplesheet_lines, params, contrasts_lines, profile, rationale):
        lines = lambda v: "\n".join(v) if isinstance(v, list) else str(v)
        p = scratch(run_dir, **{"final_samplesheet.csv": lines(samplesheet_lines), "final_params.txt": lines(params),
                                "final_rationale.txt": rationale, "final_contrasts.csv": lines(contrasts_lines)})
        return checks("save-plan", run_dir, pipeline, p["final_samplesheet.csv"], p["final_params.txt"],
                      p["final_rationale.txt"], "--contrasts", p["final_contrasts.csv"], "--profile", profile.strip(),
                      *(["--upstream", upstream] if upstream else []))
    array = {"type": "array", "items": {"type": "string"}}
    return Tool("SUBMIT_PLAN", "Submit your final plan: exactly the plan that passed CHECK_PLAN. Geth checks it "
                "again and saves it for a person to review; if it reports problems, fix them and submit again.",
                {"type": "object", "required": ["pipeline", "samplesheet_lines", "params", "contrasts_lines",
                                                "profile", "rationale"],
                 "properties": {
                     "pipeline": {"type": "string", "description": "pipeline name, e.g. rnaseq"},
                     "samplesheet_lines": dict(array, description="the samplesheet, one CSV line per item, header first"),
                     "params": dict(array, description="one key=value entry per parameter"),
                     "contrasts_lines": dict(array, description="the second sheet, CSV lines, header first; [] if none"),
                     "profile": {"type": "string", "description": "the analysis profile, or ''"},
                     "rationale": {"type": "string", "description": "the rationale of the plan"}}},
                run, final=True, check=True)


def pipeline_options():
    """Browse the pinned release's parameter schema: its sections, a section's options, or a search."""
    import glob
    import json as _json
    import importlib.util
    spec = importlib.util.spec_from_file_location("geth_checks", CHECKS)
    gc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gc)
    skip_sections = {"institutional_config_options", "generic_options"}

    def run(pipeline, section="", search=""):
        pipeline = pipeline.replace("nf-core/", "").strip()
        rev = gc.REGISTRY.get(pipeline, {}).get("revision")
        path = os.path.join(GETH_HOME, "geth", "schemas", f"{pipeline}-{rev}.params.json")
        if not rev or not os.path.isfile(path):
            return f"No parameter schema for '{pipeline}'. Pipelines: {', '.join(sorted(k for k in gc.REGISTRY if not gc.REGISTRY[k].get('toolbox')))}"
        schema = _json.load(open(path))
        defs = schema.get("$defs") or schema.get("definitions") or {}

        def visible(sec):
            return {k: v for k, v in defs[sec].get("properties", {}).items()
                    if not v.get("hidden") and k not in gc.OWNED}

        def line(name, p):
            bits = [p.get("type", "")]
            if "default" in p:
                bits.append(f"default {p['default']!r}")
            if "enum" in p:
                bits.append(f"one of {p['enum']}")
            text = f"--{name} ({', '.join(b for b in bits if b)}): {p.get('description', '')}"
            if p.get("help_text"):
                text += f" | {' '.join(str(p['help_text']).split())[:240]}"
            return text

        if search:
            term = search.lower()
            hits = [line(k, v) + f"   [section {sec}]" for sec in defs if sec not in skip_sections
                    for k, v in visible(sec).items()
                    if term in k.lower() or term in str(v.get("description", "")).lower() or term in str(v.get("help_text", "")).lower()]
            return "\n".join(hits[:40]) or f"No option of nf-core/{pipeline} {rev} matches '{search}'."
        if section:
            if section not in defs:
                return f"No section '{section}'. Sections: {', '.join(s for s in defs if s not in skip_sections)}"
            return f"nf-core/{pipeline} {rev}, {defs[section].get('title', section)}:\n" + "\n".join(
                line(k, v) for k, v in visible(section).items())
        return f"nf-core/{pipeline} {rev}: option sections (call again with section=... or search=...):\n" + "\n".join(
            f"- {sec}: {d.get('title', '')} ({len(visible(sec))} options). {d.get('description', '')}"
            for sec, d in defs.items() if sec not in skip_sections and visible(sec))

    return Tool("PIPELINE_OPTIONS", "Browse the options of the pinned pipeline release (its parameter schema): call "
                "it with only the pipeline to list the sections, with a section to list its options with their "
                "defaults, or with search to find options by word (e.g. 'primer', 'strand', 'umi').",
                {"type": "object", "required": ["pipeline"], "properties": {
                    "pipeline": {"type": "string", "description": "pipeline name, e.g. rnaseq"},
                    "section": {"type": "string", "description": "a section name from the list, or ''"},
                    "search": {"type": "string", "description": "a word to search for, or ''"}}}, run)


def inspect_reads(data_root):
    """What a FASTQ says about itself: read lengths, from its first reads (a model cannot count 76 letters)."""
    def run(path, n=2000):
        if not under(path, data_root):
            return f"REFUSED: only files under {data_root} can be read"
        if not os.path.isfile(path):
            return f"NOT FOUND: {path}"
        opener = gzip.open if path.endswith(".gz") else open
        lengths, names = [], []
        try:
            with opener(path, "rt", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i % 4 == 0:
                        if not line.startswith("@"):
                            return f"{path}: not a FASTQ file (line {i + 1} does not start with @)"
                        if len(names) < 2:
                            names.append(line.strip()[:80])
                    elif i % 4 == 1:
                        lengths.append(len(line.strip()))
                        if len(lengths) >= int(n):
                            break
        except (OSError, EOFError) as e:
            return f"{path}: cannot be read ({e})"
        if not lengths:
            return f"{path}: no reads"
        lengths.sort()
        common = max(set(lengths), key=lengths.count)
        return (f"{os.path.basename(path)}: first {len(lengths)} reads; length min {lengths[0]}, median "
                f"{lengths[len(lengths) // 2]}, max {lengths[-1]}; most common {common} bp "
                f"({100 * lengths.count(common) // len(lengths)}% of reads). First read names: {'; '.join(names)}")
    return Tool("INSPECT_READS", "Read lengths of a FASTQ file (.fastq or .fastq.gz), from its first reads: use it "
                "for the read length instead of counting letters.", string_params(path="absolute path of the FASTQ"), run)


def sc_job(run_dir, task, arg):
    """One job of the single-cell toolbox (bin/sc_job.sh: geth/jobs.nf through the site's scheduler)."""
    result = subprocess.run(["bash", SC_JOB, run_dir, task, arg], capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


def sc_inspect(run_dir, data_root):
    def run(h5ad):
        if not under(h5ad, data_root) or not h5ad.endswith(".h5ad"):
            return f"REFUSED: only .h5ad files under {data_root} can be inspected"
        if not os.path.isfile(h5ad):
            return f"NOT FOUND: {h5ad}"
        return sc_job(run_dir, "inspect", h5ad)
    return Tool("SC_INSPECT", "Inspect a single-cell count matrix (.h5ad) with Geth's single-cell toolbox: cells, "
                "and the distributions of counts, genes and mitochondrial fraction per cell (a scheduler job: a few "
                "minutes).", string_params(h5ad="absolute path of the .h5ad file"), run)
