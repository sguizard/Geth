#!/usr/bin/env python3
"""Geth projects: several analyses towards one question.

The coordinator agent (geth/harness/project.py) proposes the steps and a person approves them. This file checks
the steps, keeps the project's state and runs it. Each pipeline step is an ordinary Geth run, planned, approved
and run with the usual commands. Nothing here talks to a model.

  geth_project.py capabilities [--lab]               what a project's steps may be
  geth_project.py check <project_dir> <steps.json>   the step check: STEP CHECK: OK, or the problems
  geth_project.py nfcore <words...>                   nf-core pipelines matching the words (for gaps)
  geth_project.py ensembl <species>                   a species' genome and annotation in Ensembl
  geth_project.py show <project_dir>
  geth_project.py list <projects folder>
  geth_project.py approve <project_dir> <who>
  geth_project.py approve-lab <project_dir> <step id> <who>   a lab step's design
  geth_project.py run <project_dir> [--answers <file>] [--auto-approve] [--overrule <who>]

A project folder, $GETH_RUNS_DIR/projects/<name>/:
  question.txt, data_dir.txt, options.json   the request, the delivery, {"lab": true|false}
  steps.json, steps_check.txt                the coordinator's steps, as checked
  steps.proposed.json                        a change the coordinator proposed during the run (needs approval)
  APPROVED                                   who approved the steps, when, and their SHA-256
  reviews.json                               the coordinator's decision after each finished step
  log.md                                     what happened, in order
  report.md, report_check.txt                the project report
Pipeline step <id> runs as $GETH_RUNS_DIR/<project>-<id>. Exit status of run: 0 finished, 2 waiting for a person,
3 the coordinator proposes new steps (approve them, then run again), 1 an error.
"""
import glob
import hashlib
import shutil
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.dirname(HERE))
import geth_checks as gc  # noqa: E402
from harness.prose import wrap  # noqa: E402  (standard library only; no agent is started)

GETH_HOME = os.environ.get("GETH_HOME", os.path.dirname(os.path.dirname(HERE)))
GETH = os.path.join(GETH_HOME, "geth", "geth")
RUNS = os.environ.get("GETH_RUNS_DIR", "").rstrip("/")
DATA_ROOT = os.environ.get("GETH_DATA_ROOT", "").rstrip("/")
REFERENCES = os.environ.get("GETH_REFERENCES", "").rstrip("/")
CATALOGUE = os.path.join(GETH_HOME, "geth", "schemas", "nfcore_catalogue.tsv")
ENSEMBL_REST = "https://rest.ensembl.org"
ENSEMBL_FTP = "https://ftp.ensembl.org/pub"

KINDS = ("pipeline", "reference", "gap", "lab")
MAX_STEPS = 8
STEP_ID = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
H5AD_STEPS = ("scrnaseq", "sc_downstream")  # steps whose results a lab step can start from


def read(path, default=""):
    try:
        with open(path, errors="replace") as fh:
            return fh.read()
    except OSError:
        return default


def load(path, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save(path, data):
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def log(pdir, text):
    with open(os.path.join(pdir, "log.md"), "a") as fh:
        fh.write(wrap(f"- {time.strftime('%F %T')} {text}", width=100) + "\n")
    print(wrap(f"[{time.strftime('%H:%M')}] {text}"), flush=True)


def step_run(pdir, sid):
    return os.path.join(RUNS, f"{os.path.basename(pdir)}-{sid}")


def lab_runs(pdir, sid):
    """A lab step's two lab runs: its design, and its build."""
    name = os.path.basename(step_run(pdir, sid))
    return os.path.join(RUNS, "lab", name + "-design"), os.path.join(RUNS, "lab", name)


# ---------------------------------------------------------------- what the coordinator may plan

def skill_descriptions():
    out = {}
    for path in glob.glob(os.path.join(GETH_HOME, "geth", "skills", "*", "SKILL.md")):
        m = re.search(r"^description:\s*(.*)$", read(path), re.M)
        name = os.path.basename(os.path.dirname(path)).replace("nfcore-", "").replace("-", "_")
        out[name] = m.group(1).strip() if m else ""
    return out


def capabilities(lab):
    desc = skill_descriptions()
    raw = [p for p in sorted(gc.REGISTRY) if not gc.REGISTRY[p].get("follows")]
    follow = [p for p in sorted(gc.REGISTRY) if gc.REGISTRY[p].get("follows")]
    lines = ["Kind pipeline, on sequencing data (no analysis step before it; 'data' = its folder in the delivery):"]
    lines += [f"- {p}: {desc.get(p, '')}" for p in raw]
    lines += ["", "Kind pipeline, follow-ups (after = the one finished step they build on):"]
    lines += [f"- {p}: after a {gc.REGISTRY[p]['follows']} step. {desc.get(p, '')}"
              + (" It analyses ONE count matrix per run: one sample, or the step's combined matrix of all its samples "
                 "analysed together. It cannot analyse several samples or experiments separately, nor compare them: "
                 "that needs the lab (if allowed) or is a gap." if gc.REGISTRY[p].get("toolbox") else "")
              for p in follow]
    lines += ["", "Kind reference: download a genome and its annotation from Ensembl into the reference catalogue, when "
              "LIST_REFERENCES has no entry for the species a pipeline step needs (fields species, assembly, release: "
              "from FIND_GENOME). That pipeline step lists it in after.",
              "", "Kind gap: a part of the question that none of the above does. Say what it is (suggestion), name the "
              "nf-core pipeline that would do it if one exists (nfcore, from SEARCH_NFCORE), and what the earlier steps "
              "hand over to it."]
    if lab:
        lines += ["", "Kind lab (EXPERIMENTAL, allowed in this project): agents design and write a single-cell analysis "
                  "of a count matrix (.h5ad) and test it in a sandbox. After a scrnaseq or sc_downstream step, or with "
                  "no after when the delivery is a folder with one .h5ad file. Use it only for what no pipeline does. It starts from the combined matrix of all the samples of a scrnaseq "
                  "step (counts, with each cell's sample), so it can treat samples or experiments separately."]
    else:
        lines += ["", "The lab (agents writing analysis code) is not allowed in this project: what would need it is a gap."]
    return "\n".join(lines)


def nfcore(words):
    words = [w.lower() for w in words if len(w) > 2]
    hits = []
    for line in read(CATALOGUE).splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, release, description = (line.split("\t") + ["", ""])[:3]
        score = sum(w in f"{name} {description}".lower() for w in words)
        if score:
            hits.append((-score, name, release, description))
    out = [f"nf-core/{n} (release {r}; {'Geth runs it' if n in gc.REGISTRY else 'not in Geth'}): {d}"
           for _, n, r, d in sorted(hits)[:10]]
    return "\n".join(out) or "No nf-core pipeline matches these words."


# ---------------------------------------------------------------- Ensembl, for reference steps

def http_json(url):
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def http_size(url):
    """The size of a file on Ensembl's server, or None if it is not there."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=60) as response:
            return int(response.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError:
        return None


def ensembl_files(species, assembly, release):
    """The genome and annotation a reference step downloads, as geth/references/stage_ensembl.sh fetches them:
    [(url, bytes), (url, bytes)]. Raises ValueError when Ensembl has no such files."""
    base, cap = f"{ENSEMBL_FTP}/release-{release}", species[:1].upper() + species[1:]
    for kind in ("primary_assembly", "toplevel"):
        fasta = f"{base}/fasta/{species}/dna/{cap}.{assembly}.dna.{kind}.fa.gz"
        size = http_size(fasta)
        if size is not None:
            break
    else:
        raise ValueError(f"Ensembl release {release} has no genome for {species} {assembly}")
    # the annotation: species imported from Ensembl Genomes (e.g. yeast) carry that site's release in its name
    try:
        with urllib.request.urlopen(f"{base}/gtf/{species}/", timeout=60) as response:
            listing = response.read().decode(errors="replace")
    except urllib.error.HTTPError:
        listing = ""
    names = sorted(set(re.findall(re.escape(f"{cap}.{assembly}.") + r"\d+\.gtf\.gz", listing)))
    if not names:
        raise ValueError(f"Ensembl release {release} has no annotation (GTF) for {species} {assembly}")
    gtf = f"{base}/gtf/{species}/{names[0]}"
    return [(fasta, size), (gtf, http_size(gtf) or 0)]


def ensembl(name):
    species = name.strip().lower().replace(" ", "_")
    try:
        if not re.match(r"^[a-z]+_[a-z]+", species):  # a common name ("mouse"): Ensembl's taxonomy
            found = http_json(f"{ENSEMBL_REST}/taxonomy/name/{urllib.parse.quote(name.strip())}")
            species = found[0]["scientific_name"].lower().replace(" ", "_")
        genome = http_json(f"{ENSEMBL_REST}/info/genomes/{species}")
        release = http_json(f"{ENSEMBL_REST}/info/data")["releases"][0]
        files = ensembl_files(genome["name"], genome["assembly_name"], release)
    except (urllib.error.URLError, ValueError, KeyError, IndexError, OSError) as e:
        return f"NOT FOUND in Ensembl ({e}): Geth stages genomes from Ensembl only; without one, the step is a gap."
    return (f"species: {genome['name']} ({genome.get('display_name', '')})\nassembly: {genome['assembly_name']}\n"
            f"release: {release}\n" + "\n".join(f"file: {u} ({s / 1e6:,.0f} MB)" for u, s in files))


def delivered_genomes(data_dir):
    """Genome FASTA files the delivery brings with it (3 levels deep)."""
    found = []
    for pattern in ("*.fa", "*.fa.gz", "*.fasta", "*.fasta.gz", "*.fna", "*.fna.gz"):
        for depth in ("", "*/", "*/*/", "*/*/*/"):
            found += glob.glob(os.path.join(data_dir, depth + pattern))
    return sorted(found)


READS = (".fastq", ".fastq.gz", ".fq", ".fq.gz", ".bam", ".cram", ".fast5", ".pod5", ".sra")


def sequencing_files(folder):
    """Sequencing files (reads) in a folder, 3 levels deep."""
    found = []
    for depth in ("", "*/", "*/*/", "*/*/*/"):
        found += [f for f in glob.glob(os.path.join(folder, depth + "*")) if f.lower().endswith(READS)]
    return found


def described(folder):
    """Text files that describe data (README, sample tables) directly in a folder."""
    return [f for f in glob.glob(os.path.join(folder, "*")) if os.path.isfile(f)
            and f.lower().endswith((".txt", ".tsv", ".csv", ".md", ".xlsx"))]


def catalogue_entry(step):
    """The catalogue folder a reference step creates (as stage_ensembl.sh names it)."""
    return os.path.join(REFERENCES, f"{step.get('species')}_{step.get('assembly')}_ens{step.get('release')}")


# ---------------------------------------------------------------- the step check

def normalise(pdir, doc):
    """Steps as Geth keeps them: a pipeline step's data folder as an absolute path (a relative one is inside the
    delivery, e.g. RNA or fastq)."""
    data_dir = read(os.path.join(pdir, "data_dir.txt")).strip()
    for s in doc.get("steps") or [] if isinstance(doc, dict) else []:
        data = str(s.get("data") or "").strip() if isinstance(s, dict) else ""
        if data:
            s["data"] = os.path.normpath(data if data.startswith("/") else os.path.join(data_dir, data))
        if isinstance(s, dict) and s.get("nfcore"):  # a pipeline's bare name: smrnaseq, not nf-core/smrnaseq
            s["nfcore"] = str(s["nfcore"]).strip().replace("nf-core/", "")
    return doc


def check(pdir, doc, started=()):
    """Problems and notes of a step list. started: ids of steps already begun, which a revision must keep as is."""
    problems, notes, seen = [], [], {}
    steps = normalise(pdir, doc).get("steps") if isinstance(doc, dict) else None
    if not isinstance(steps, list) or not steps:
        return ["no steps: give at least one step"], notes
    if len(steps) > MAX_STEPS:
        problems.append(f"{len(steps)} steps: at most {MAX_STEPS} per project")
    lab = (load(os.path.join(pdir, "options.json"), {}) or {}).get("lab", False)
    data_dir = read(os.path.join(pdir, "data_dir.txt")).strip()
    old = {s.get("id"): s for s in (load(os.path.join(pdir, "steps.json"), {}) or {}).get("steps", [])}
    folders = {}  # data folder -> the pipeline step on sequencing data that uses it
    for i, s in enumerate(steps, start=1):
        s = s if isinstance(s, dict) else {}
        sid, kind, where = str(s.get("id", "")), s.get("kind"), f"step {i}"
        if not STEP_ID.match(sid):
            problems.append(f"{where}: id '{sid}' must be 1-16 lower-case letters, digits or '_', starting with a letter")
        elif sid in seen:
            problems.append(f"{where}: id '{sid}' is used twice")
        where = f"step {i} ({sid})"
        if sid in started and s != old.get(sid):
            problems.append(f"{where} has started: it must stay exactly as approved")
        if kind not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)} (got {kind!r})")
        if not str(s.get("question", "")).strip():
            problems.append(f"{where}: the question for this step is missing")
        after = s.get("after") or []
        after = after if isinstance(after, list) else [after]
        for a in after:
            if a not in seen:
                problems.append(f"{where}: after '{a}': no step above with that id (a step builds on steps listed before it)")
        ups = [seen[a] for a in after if a in seen]
        if kind == "pipeline":
            p = gc.pipeline_name(str(s.get("pipeline", "")))
            if p not in gc.REGISTRY:
                problems.append(f"{where}: Geth does not run '{p}' (LIST_CAPABILITIES); if nf-core has it "
                                f"(SEARCH_NFCORE), make this step a gap naming it")
                seen[sid] = s
                continue
            follows = gc.REGISTRY[p].get("follows")
            analyses = [u for u in ups if u.get("kind") != "reference"]
            if follows and not (len(analyses) == 1 and gc.pipeline_name(str(analyses[0].get("pipeline", ""))) == follows):
                problems.append(f"{where}: {p} builds on one finished {follows} step: list that step in after")
            if not follows:
                if analyses:
                    problems.append(f"{where}: {p} runs on sequencing data, so it builds on no analysis step "
                                    "(only on reference steps)")
                data = str(s.get("data") or data_dir)
                if data in folders:
                    problems.append(f"{where}: steps {folders[data]} and {sid} both use {data}: give each its own "
                                    "folder of the delivery (data), e.g. RNA and ATAC")
                folders.setdefault(data, sid)
                parent = os.path.dirname(data)
                if data != data_dir and parent.startswith(data_dir) and described(parent) and not described(data):
                    problems.append(f"{where}: data {data} holds no README or sample table, but {parent} does: give "
                                    f"{parent}, so that the step's planner reads them (and any reference beside them)")
                if not (data.startswith(DATA_ROOT + "/") and os.path.isdir(data)):
                    problems.append(f"{where}: data '{data}' is not a folder of the delivery ({data_dir}): give the "
                                    "folder that holds this step's files (e.g. RNA), or leave data out for the whole delivery")
                elif not sequencing_files(data):
                    problems.append(f"{where}: {p} needs sequencing reads, and {data} holds none (e.g. only count "
                                    "matrices): what the question needs on such data is another kind of step")
        elif kind == "reference":
            if after:
                problems.append(f"{where}: a reference step builds on nothing (after must be empty)")
            species, assembly, release = (str(s.get(k, "")).strip() for k in ("species", "assembly", "release"))
            if not (re.match(r"^[a-z]+_[a-z0-9_]+$", species) and assembly and release.isdigit()):
                problems.append(f"{where}: species (e.g. mus_musculus), assembly and release (a number) are needed: "
                                "copy them from FIND_GENOME")
            elif os.path.isdir(catalogue_entry(s)):
                problems.append(f"{where}: the catalogue already has {catalogue_entry(s)}: no download needed")
            elif delivered_genomes(data_dir):
                problems.append(f"{where}: the delivery brings its own genome ({delivered_genomes(data_dir)[0]}): the "
                                "pipeline steps use it, no download needed")
            else:
                try:
                    files = ensembl_files(species, assembly, release)
                    notes.append(f"{where} downloads {sum(b for _, b in files) / 1e9:.1f} GB (compressed) into "
                                 f"{catalogue_entry(s)}")
                except (ValueError, urllib.error.URLError, OSError) as e:
                    problems.append(f"{where}: cannot verify the files in Ensembl ({e})")
        elif kind == "gap":
            if not str(s.get("suggestion", "")).strip():
                problems.append(f"{where}: say what the gap is and what would fill it (suggestion)")
            nf = str(s.get("nfcore", "")).strip().replace("nf-core/", "")
            if nf and nf not in [l.split("\t")[0] for l in read(CATALOGUE).splitlines() if not l.startswith("#")]:
                problems.append(f"{where}: nf-core has no pipeline named '{nf}' (SEARCH_NFCORE)")
            elif nf and nf in gc.REGISTRY:
                problems.append(f"{where}: Geth runs {nf}: make this step a pipeline step")
        elif kind == "lab":
            if not lab:
                problems.append(f"{where}: this project does not allow the lab (geth legion new ... --lab): make it a gap")
            analyses = [u for u in ups if u.get("kind") == "pipeline"]
            single = glob.glob(os.path.join(data_dir, "*.h5ad"))
            if analyses and not (len(analyses) == 1 and gc.pipeline_name(str(analyses[0].get("pipeline"))) in H5AD_STEPS):
                problems.append(f"{where}: a lab step starts from one scrnaseq or sc_downstream step's count matrix")
            if not analyses and len(single) != 1:
                problems.append(f"{where}: with no step before it, the delivery must be a folder with one .h5ad file")
        seen[sid] = s
    if not any(s.get("kind") in ("pipeline", "lab") for s in steps if isinstance(s, dict)):
        notes.append("no step analyses data: the project report will only describe the gaps")
    return problems, notes


def check_report_text(problems, notes):
    text = "STEP CHECK: OK" if not problems else f"STEP CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems)
    return text + "".join(f"\nNOTE: {n}" for n in notes)


# ---------------------------------------------------------------- approval and state

def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def approve(pdir, who):
    proposed = os.path.join(pdir, "steps.proposed.json")
    path = proposed if os.path.isfile(proposed) else os.path.join(pdir, "steps.json")
    doc = load(path)
    started = [s["id"] for s in (approved_doc(pdir, quiet=True) or {}).get("steps", []) if status(pdir, s) != "todo"]
    problems, notes = check(pdir, doc or {}, started)
    if problems:
        print(check_report_text(problems, notes))
        return 1
    if path == proposed:
        os.replace(proposed, os.path.join(pdir, "steps.json"))
        log(pdir, "approved the coordinator's revised steps")
    save(os.path.join(pdir, "APPROVED"), {"approved_by": who, "approved_at": time.strftime("%F %T"),
                                          "sha256": sha(os.path.join(pdir, "steps.json"))})
    print(f"Project steps approved by {who}.")
    return 0


def approved_doc(pdir, quiet=False):
    """The approved steps, or None (quiet) / an error when they are not approved or changed since."""
    record, path = load(os.path.join(pdir, "APPROVED")), os.path.join(pdir, "steps.json")
    if record and os.path.isfile(path) and record.get("sha256") == sha(path):
        return load(path)
    if quiet:
        return None
    raise ValueError("the project's steps are not approved (or changed since): geth legion approve " + os.path.basename(pdir))


def status(pdir, step):
    kind, run = step.get("kind"), step_run(pdir, step.get("id"))
    if kind == "gap":
        return "gap"
    if kind == "reference":
        if os.path.isfile(os.path.join(catalogue_entry(step), "README.txt")):
            return "done"
        return "failed" if os.path.isfile(os.path.join(pdir, f"reference_{step['id']}.failed")) else "todo"
    if kind == "lab":
        design, build = lab_runs(pdir, step["id"])
        if not os.path.isdir(design):
            return "todo"
        if not read(os.path.join(design, "lab_design_check.txt")).startswith("DESIGN CHECK: OK"):
            return "plan failed"
        if not os.path.isfile(os.path.join(pdir, f"lab_{step['id']}.approved")):
            return "waiting for approval"
        state = read(os.path.join(build, "build_state.txt")).strip()
        if not state:
            return "approved"
        return "done" if state.startswith("done") else "failed" if state.startswith(("failed", "stopped")) else "running"
    if not os.path.isdir(run):
        return "todo"
    if not os.path.isfile(os.path.join(run, "plan_pipeline.txt")):
        return "plan failed"
    if not os.path.isfile(os.path.join(run, "APPROVED")):
        return "waiting for approval"
    outcome = read(os.path.join(run, "outcome.txt"))
    if not outcome:
        return "approved"
    return "done" if "succeeded: true" in outcome else "failed"


def show(pdir):
    doc = load(os.path.join(pdir, "steps.json"), {}) or {}
    print(f"Project : {os.path.basename(pdir)}")
    print(wrap(f"Question: {read(os.path.join(pdir, 'question.txt')).strip()}", labels=True, whole=True))
    print(f"Data    : {read(os.path.join(pdir, 'data_dir.txt')).strip()}")
    print(f"Lab     : {'allowed (EXPERIMENTAL)' if (load(os.path.join(pdir, 'options.json'), {}) or {}).get('lab') else 'not allowed'}")
    versions = read(os.path.join(pdir, "geth_version.txt")).splitlines()
    if versions:  # "<stage> <date> <time> Geth <release> (commit ...)": the coordinator's last stage
        stage, day, clock, version = (versions[-1].split(" ", 3) + [""] * 4)[:4]
        print(f"Geth    : {version} (coordinator, {stage.replace('project_', '')}, {day} {clock[:5]})")
    spend = [l.split() for l in read(os.path.join(pdir, "model_spend.txt")).splitlines() if len(l.split()) >= 3]
    if spend:  # a paid model chosen with --model: what the project's commands spent on it, steps included
        print(f"Model   : ${sum(float(r[1]) for r in spend):.2f} on {', '.join(sorted({r[2] for r in spend}))} "
              f"({len(spend)} agent stages; model_spend.txt)")
    print("\nSteps:")
    for i, s in enumerate(doc.get("steps", []), start=1):
        kind = s.get("kind")
        what = {"pipeline": f"nf-core/{s.get('pipeline')}" if s.get("pipeline") != "sc_downstream" else "single-cell toolbox",
                "reference": f"download {s.get('species')} {s.get('assembly')} (Ensembl {s.get('release')})",
                "gap": "GAP: no specialist" + (f" (nf-core/{str(s.get('nfcore')).replace('nf-core/', '')} would)" if s.get("nfcore") else ""),
                "lab": "lab: agents write the analysis (EXPERIMENTAL)"}.get(kind, kind)
        after = f", after {', '.join(s.get('after') or [])}" if s.get("after") else ""
        run = f"   run: {os.path.basename(step_run(pdir, s['id']))}" if kind in ("pipeline", "lab") else ""
        print(f"  {i}. {s.get('id')} [{what}{after}] {status(pdir, s)}{run}")
        print(wrap(s.get("question", ""), indent=5))
        if s.get("suggestion"):
            print(wrap(f"-> {s['suggestion']}", indent=5))
    if doc.get("rationale"):
        print("\nRationale:\n" + wrap(doc["rationale"], indent=2))
    reviews = load(os.path.join(pdir, "reviews.json"), {}) or {}
    if reviews:
        print("\nThe coordinator's decisions:")
        for sid, r in reviews.items():
            print(f"  after {sid}: {r.get('action', '?')}\n" + wrap(r.get("reason", ""), indent=4))
    print("\n" + wrap(read(os.path.join(pdir, "steps_check.txt")).strip() or "Not checked yet.", labels=True))
    record = load(os.path.join(pdir, "APPROVED"))
    print("Approved by " + record["approved_by"] + " on " + record["approved_at"] if approved_doc(pdir, quiet=True)
          else "Not approved: geth legion approve " + os.path.basename(pdir))
    if os.path.isfile(os.path.join(pdir, "steps.proposed.json")):
        print("The coordinator proposes new steps (steps.proposed.json): review them, then geth legion approve.")
    if os.path.isfile(os.path.join(pdir, "report.md")):
        print(f"Report: {os.path.join(pdir, 'report.md')} ({read(os.path.join(pdir, 'report_check.txt')).strip() or 'not checked'})")


# ---------------------------------------------------------------- the run

def geth(*args, quiet=False, env=None):
    """A geth command, as a person would type it (its output shown unless quiet)."""
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL} if quiet else {}
    return subprocess.run([GETH, *args], env={**os.environ, **(env or {})}, **kwargs).returncode


def coordinate(pdir, mode, step=""):
    """The coordinator agent at a decision point (sandboxed, like every agent stage)."""
    return geth("legion", "_coordinate", os.path.basename(pdir), mode, step)


def download(pdir, step):
    """A reference step: geth/references/stage_ensembl.sh, as a job where the site allows downloads."""
    script = os.path.join(GETH_HOME, "geth", "references", "stage_ensembl.sh")
    label = step.get("label") or step["species"].replace("_", " ").capitalize()
    submit = os.environ.get("GETH_DOWNLOAD_SUBMIT", "").split()
    log(pdir, f"step {step['id']}: downloading {step['species']} {step['assembly']} (Ensembl {step['release']})"
        + (f" with: {' '.join(submit)}" if submit else " here"))
    out = os.path.join(pdir, f"reference_{step['id']}.log")
    args = [step["species"], step["assembly"], str(step["release"]), label]
    command = [*submit, script, *args] if submit else ["bash", script, *args]  # submit: e.g. qsub -sync y -q staging
    with open(out, "w") as fh:
        rc = subprocess.run(command, stdout=fh, stderr=subprocess.STDOUT, cwd=pdir).returncode
    if rc != 0 or status(pdir, step) != "done":
        open(os.path.join(pdir, f"reference_{step['id']}.failed"), "w").write(f"exit {rc}: see {out}\n")


def review(pdir, step):
    """The coordinator's decision after a step finished: continue, stop or revise (kept in reviews.json)."""
    reviews = load(os.path.join(pdir, "reviews.json"), {}) or {}
    if step["id"] not in reviews:
        coordinate(pdir, "review", step["id"])
        reviews = load(os.path.join(pdir, "reviews.json"), {}) or {}
    decision = reviews.get(step["id"], {"action": "continue", "reason": "the coordinator gave no decision"})
    return decision.get("action", "continue")


def overrule(pdir, who):
    """A person overrules the coordinator: its stops become continues, a proposed revision is dropped."""
    reviews = load(os.path.join(pdir, "reviews.json"), {}) or {}
    for sid, r in reviews.items():
        if r.get("action") in ("stop", "revise"):
            log(pdir, f"{who} overruled the coordinator's {r['action']} after {sid}: the approved steps go on")
            reviews[sid] = {"action": "continue", "reason": f"overruled by {who} ({r['action']}: {r.get('reason', '')})"}
    save(os.path.join(pdir, "reviews.json"), reviews)
    proposed = os.path.join(pdir, "steps.proposed.json")
    if os.path.isfile(proposed):
        os.replace(proposed, proposed + ".overruled")
    for f in ("report.md", "report_check.txt"):  # the report of a stopped project is written again at the end
        if os.path.isfile(os.path.join(pdir, f)):
            os.replace(os.path.join(pdir, f), os.path.join(pdir, f + ".before-overrule"))


class BudgetSpent(Exception):
    """The paid model's total for this command (geth legion run --model ... --budget) is spent: the project pauses."""


def budget_left():
    """What is left of this command's total for a chosen model (driver_slots.sh: GETH_MODEL_TOTAL_USD, counted in
    GETH_MODEL_SPEND from GETH_MODEL_SPEND_FROM), or None without one."""
    total = os.environ.get("GETH_MODEL_TOTAL_USD")
    if not (os.environ.get("GETH_MODEL_MODEL") and total):
        return None
    path, start = os.environ.get("GETH_MODEL_SPEND", ""), int(os.environ.get("GETH_MODEL_SPEND_FROM") or 0)
    lines = open(path).readlines()[start:] if path and os.path.isfile(path) else []
    return float(total) - sum(float(l.split()[1]) for l in lines if len(l.split()) > 1)


def need_budget(what):
    left = budget_left()
    if left is not None and left <= 0.01:
        raise BudgetSpent(what)


def stopped_by_budget(*logs):
    """A stage that the budget stopped: refused at its start, or its next request would have crossed it."""
    return any("Budget spent:" in read(path) or "budget reached:" in read(path) for path in logs)


def run(pdir, answers="", auto=False):
    try:
        return run_steps(pdir, answers, auto)
    except BudgetSpent as e:
        name = os.path.basename(pdir)
        log(pdir, f"the paid model's budget for this command is spent ({e}): the project pauses here, and nothing "
            f"stopped by it counts as failed. To go on: geth legion run {name} --model <name> --budget <USD> "
            f"(or without --model, on the site's model)")
        return 4


def run_steps(pdir, answers, auto):
    doc = approved_doc(pdir)
    name, question = os.path.basename(pdir), read(os.path.join(pdir, "question.txt")).strip()
    steps = {s["id"]: s for s in doc["steps"]}
    print(f"Project {name}: " + "; ".join(f"{s['id']} ({status(pdir, s)})" for s in doc["steps"]), flush=True)
    stopped = False
    for step in doc["steps"]:
        sid, kind, run_name = step["id"], step["kind"], os.path.basename(step_run(pdir, step["id"]))
        state = status(pdir, step)
        blocked = [a for a in step.get("after") or [] if status(pdir, steps[a]) != "done"]
        if stopped or (blocked and state == "todo"):
            if state == "todo":
                log(pdir, f"step {sid}: not started ({'the project stopped' if stopped else 'it builds on ' + ', '.join(blocked) + ', not done'})")
            continue
        if kind == "gap":
            continue
        if kind == "reference" and state == "todo":
            download(pdir, step)
        if kind == "pipeline":
            if state == "todo":
                upstream = [a for a in step.get("after") or [] if steps[a]["kind"] == "pipeline"]
                where = ["--from", os.path.basename(step_run(pdir, upstream[0]))] if upstream else [step.get("data") or read(os.path.join(pdir, "data_dir.txt")).strip()]
                need_budget(f"planning step {sid}")
                log(pdir, f"step {sid}: planning {run_name}")
                geth("plan", *where, f"{step['question']} (Step '{sid}' of the project: {question})", run_name,
                     *(["--answers", answers] if answers else []))
                state = status(pdir, step)
                if state == "plan failed" and stopped_by_budget(os.path.join(step_run(pdir, sid), "geth_plan.log")):
                    shutil.rmtree(step_run(pdir, sid))  # not a failed plan: planned again next time
                    raise BudgetSpent(f"planning step {sid}")
            if state == "waiting for approval":
                if not auto:
                    log(pdir, f"step {sid}: planned, waiting for you: geth show {run_name}; geth approve {run_name}; "
                        f"then geth legion run {name}")
                    return 2
                geth("approve", run_name, "--yes", quiet=True)
                state = status(pdir, step)
            if state == "approved":
                need_budget(f"running step {sid}")
                log(pdir, f"step {sid}: running {run_name}")
                geth("run", run_name)
                run_log = os.path.join(step_run(pdir, sid), "geth_run.log")
                if status(pdir, step) == "failed" and stopped_by_budget(run_log):  # resumed next time, not failed
                    os.replace(os.path.join(step_run(pdir, sid), "outcome.txt"),
                               os.path.join(step_run(pdir, sid), "outcome.budget-stopped.txt"))
                    raise BudgetSpent(f"running step {sid}")
                if stopped_by_budget(run_log):  # the pipeline succeeded, the report did not get written
                    raise BudgetSpent(f"reporting step {sid} (then: geth report {run_name} --model <name> --budget <USD>)")
        if kind == "lab":
            state = lab_step(pdir, step, steps, auto)
            if state in ("waiting", "running"):
                return 2
        state = status(pdir, step)
        reviewed = sid in (load(os.path.join(pdir, "reviews.json"), {}) or {})
        if state in ("done", "failed", "plan failed"):
            if not reviewed:  # newly finished: say so, and let the coordinator decide what follows
                log(pdir, f"step {sid}: {state}")
                need_budget(f"the coordinator's review after step {sid}")
            action = review(pdir, step)
            if not reviewed and sid not in (load(os.path.join(pdir, "reviews.json"), {}) or {}) and stopped_by_budget(
                    *glob.glob(os.path.join(pdir, f"geth_project_review_{sid}.log"))):
                raise BudgetSpent(f"the coordinator's review after step {sid}")
            if action == "revise":
                log(pdir, f"the coordinator proposes new steps after {sid}: geth legion show {name}; "
                    f"geth legion approve {name}; then geth legion run {name}")
                return 3
            stopped = action == "stop"
    if not os.path.isfile(os.path.join(pdir, "report.md")):
        need_budget("the project report")
        log(pdir, "all steps processed: writing the project report")
        coordinate(pdir, "summary")
        if not os.path.isfile(os.path.join(pdir, "report.md")) and stopped_by_budget(
                os.path.join(pdir, "geth_project_summary.log")):
            raise BudgetSpent("the project report")
    print(read(os.path.join(pdir, "report_check.txt")).strip(), flush=True)
    return 0


def matrix_of(pdir, step):
    """The count matrix a finished step hands over to a lab step."""
    run_dir = step_run(pdir, step["id"])
    if step.get("pipeline") == "sc_downstream":
        done = sorted(glob.glob(os.path.join(run_dir, "analysis_*", "SUCCEEDED")), key=lambda p: int(p.split("analysis_")[1].split("/")[0]))
        return os.path.join(os.path.dirname(done[-1]), "processed.h5ad") if done else ""
    for name in ("combined_cellbender_filter_matrix.h5ad", "combined_filtered_matrix.h5ad"):
        found = glob.glob(os.path.join(run_dir, "results", "**", "mtx_conversions", name), recursive=True)
        if found:
            return found[0]
    return ""


def lab_input(pdir, step, steps):
    """The lab's data folder for a step: one .h5ad (an earlier step's count matrix, or the delivery's) and a README."""
    folder = os.path.join(pdir, f"lab_{step['id']}")
    if os.path.isdir(folder):
        return folder
    ups = [steps[a] for a in step.get("after") or [] if steps[a].get("kind") == "pipeline"]
    source = matrix_of(pdir, ups[0]) if ups else (glob.glob(os.path.join(read(os.path.join(pdir, "data_dir.txt")).strip(), "*.h5ad")) or [""])[0]
    if not os.path.isfile(source):
        raise ValueError(f"step {step['id']}: no count matrix to start from ({source or 'none found'})")
    os.makedirs(folder)
    try:
        os.link(source, os.path.join(folder, os.path.basename(source)))
    except OSError:
        shutil.copy(source, folder)
    origin = (f"step {ups[0]['id']} ({ups[0]['pipeline']}, run {os.path.basename(step_run(pdir, ups[0]['id']))})"
              if ups else "the delivery")
    readme = os.path.join(read(os.path.join(pdir, "data_dir.txt")).strip(), "README.txt")
    with open(os.path.join(folder, "README.txt"), "w") as fh:
        fh.write(f"Count matrix for a step of the Geth project {os.path.basename(pdir)}.\n"
                 f"The project's question: {read(os.path.join(pdir, 'question.txt')).strip()}\n"
                 f"This step: {step['question']}\n"
                 f"{os.path.basename(source)} comes from {origin}.\n")
        if ups:
            fh.write("\nThe report of that step:\n" + read(os.path.join(step_run(pdir, ups[0]["id"]), "report.md"))[:6000])
        elif os.path.isfile(readme):
            fh.write("\nThe delivery's README:\n" + read(readme)[:6000])
    return folder


def lab_env(folder):
    """The lab reads only benchmark folders (GETH_LAB_DATA): a project's lab step adds its own data folder."""
    roots = os.environ.get("GETH_LAB_DATA") or os.path.join(DATA_ROOT, "testdata")
    return {"GETH_LAB_DATA": f"{roots}:{folder}"}


def lab_step(pdir, step, steps, auto):
    """A lab step: the lab designs the analysis, a person approves the design, the lab builds and runs it (arm B)."""
    name = os.path.basename(step_run(pdir, step["id"]))
    design, build = lab_runs(pdir, step["id"])
    state = status(pdir, step)
    folder = os.path.join(pdir, f"lab_{step['id']}")
    if state == "todo":
        folder = lab_input(pdir, step, steps)
        need_budget(f"the lab's design of step {step['id']}")
        log(pdir, f"step {step['id']}: the lab designs the analysis ({os.path.basename(design)}, EXPERIMENTAL)")
        geth("lab", "design", folder, step["question"], os.path.basename(design), env=lab_env(folder))
        state = status(pdir, step)
        if state == "plan failed" and stopped_by_budget(os.path.join(design, "geth_design.log")):
            shutil.rmtree(design)  # designed again next time
            raise BudgetSpent(f"the lab's design of step {step['id']}")
    if state == "waiting for approval":
        if not auto:
            log(pdir, f"step {step['id']}: the lab's design waits for you: geth lab show {os.path.basename(design)}; "
                f"geth legion approve {os.path.basename(pdir)} --lab {step['id']}; then geth legion run {os.path.basename(pdir)}")
            return "waiting"
        approve_lab(pdir, step["id"], "benchmark (automatic)")
        state = status(pdir, step)
    if state == "approved":
        need_budget(f"the lab's build of step {step['id']}")
        log(pdir, f"step {step['id']}: the lab builds and runs it ({name}, EXPERIMENTAL)")
        geth("lab", "build", os.path.basename(design), name, env=lab_env(folder))
        if status(pdir, step) == "failed" and stopped_by_budget(*glob.glob(os.path.join(build, "geth_*.log"))):
            shutil.move(build, build + f".budget-stopped.{time.strftime('%Y%m%d-%H%M%S')}")  # built again next time
            raise BudgetSpent(f"the lab's build of step {step['id']}")
    return status(pdir, step)


def approve_lab(pdir, sid, who):
    design, _ = lab_runs(pdir, sid)
    if not read(os.path.join(design, "lab_design_check.txt")).startswith("DESIGN CHECK: OK"):
        print(f"Step {sid} has no checked lab design to approve.")
        return 1
    files = sorted(glob.glob(os.path.join(design, "lab_design_*.txt")))
    save(os.path.join(pdir, f"lab_{sid}.approved"), {"approved_by": who, "approved_at": time.strftime("%F %T"),
                                                     "sha256": {os.path.basename(f): sha(f) for f in files}})
    log(pdir, f"step {sid}: the lab's design approved by {who}")
    return 0


def list_projects(root):
    print(f"{'PROJECT':24} {'APPROVED':9} STEPS")
    for pdir in sorted(glob.glob(os.path.join(root, "*"))):
        doc = load(os.path.join(pdir, "steps.json"), {}) or {}
        states = [f"{s.get('id')}: {status(pdir, s)}" for s in doc.get("steps", [])]
        print(f"{os.path.basename(pdir):24} {'yes' if approved_doc(pdir, quiet=True) else 'no':9} "
              f"{'; '.join(states) or 'no steps yet'}")


def main(argv):
    cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if cmd == "capabilities":
        print(capabilities("--lab" in args))
    elif cmd == "nfcore":
        print(nfcore(args))
    elif cmd == "ensembl":
        print(ensembl(" ".join(args)))
    elif cmd == "check":
        problems, notes = check(args[0], load(args[1], {}) or {})
        text = check_report_text(problems, notes)
        print(text)
        return 1 if problems else 0
    elif cmd == "show":
        show(args[0])
    elif cmd == "list":
        list_projects(args[0])
    elif cmd == "approve":
        return approve(args[0], args[1])
    elif cmd == "approve-lab":
        return approve_lab(args[0], args[1], args[2])
    elif cmd == "run":
        answers = args[args.index("--answers") + 1] if "--answers" in args else ""
        try:
            if "--overrule" in args:
                approved_doc(args[0])
                overrule(args[0], args[args.index("--overrule") + 1])
            return run(args[0], answers, "--auto-approve" in args)
        except ValueError as e:
            print(f"Geth: {e}", file=sys.stderr)
            return 1
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
