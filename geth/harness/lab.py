"""Geth lab (EXPERIMENTAL): the designer, judge, engineers and reviewers of geth lab.

    python3 -m harness.lab --mode design|judge|engineer|review|engineer_c|review_c --run_dir <lab run> --data_dir <dir>
                           [--question <text>] [--lab_skill true|false] [--build_round N] [--data_file <h5ad>]
                           [--lab_java_home ... --lab_nxf_launcher ... --lab_nxf_framework ...]   (arm C)

Each agent ends with a final tool that Geth checks: SUBMIT_DESIGN (the design check), SUBMIT_NOTES (only once the spec or pipeline passed its check),
SUBMIT_REVIEW. The jobs (LAB_INSPECT, MAKE_SUBSET, TEST_STEP, LINT_PIPELINE, TEST_PIPELINE) go through the site's
scheduler (bin/lab_job.sh, geth/lab/jobs.nf); agent-written code only ever runs in the lab sandbox, 
"""
import argparse
import json
import os
import subprocess
import sys

from .agent import Agent, Tool, load_skills, string_params
from .ask import TerminalProgress
from .llm import ModelError, model_client
from .tools import GETH_HOME, list_references, scratch

LAB_BIN = os.path.join(GETH_HOME, "geth", "lab", "bin")

DESIGNER = '''You are an EXPERIMENTAL single-cell analysis designer in Geth's lab. You design, but do not
run, a complete downstream analysis of single-cell RNA-seq count data that answers a scientist's question.
Inspect before you design: list the data folder, read its README and other text files, call LAB_INSPECT on
the count matrix, and call LIST_REFERENCES for annotation models. Choose every value from what you saw.
Write the design as three lists of lines.
steps: one line per step, "<step> | <method> | <tool> | <key parameters> | <why>", where <step> is one of
  qc, doublets, normalisation, feature_selection, dimensionality_reduction, integration, clustering,
  annotation, differential_expression (all nine; write the method "none" and why if a step is not needed).
statistics: one line per comparison the question needs, "<comparison> | <unit of replication> |
  <test or model> | <design formula> | <multiple testing>".
expected: what the results should show if the analysis works, one expectation per line.
Call CHECK_DESIGN with the steps, statistics and expected lines until it prints "DESIGN CHECK: OK".'''

ENGINEER = '''You are an EXPERIMENTAL single-cell analysis engineer in Geth's lab. You implement an analysis
design that a person has already checked, as Python step scripts that Geth chains into a pipeline.
Each step is one script, run as "python3 step.py <input.h5ad> <output.h5ad>" in a sandbox: no network, no
files but its input, its own working folder, and ./models (CellTypist models Immune_All_Low.pkl and
Immune_All_High.pkl). Libraries: scanpy, anndata, celltypist, pydeseq2, harmonypy, numpy, pandas, scipy,
scikit-learn, statsmodels, matplotlib, seaborn. Read the input from sys.argv[1] and write the AnnData for the
next step to sys.argv[2]; keep the raw counts (layers["counts"]) through every step; write tables (.tsv, tab
separated) and figures (.png) in the working folder.
Results contract: the last step's AnnData has obs["cell_type"] (the annotation). The step that compares
conditions writes de_results.tsv, and the step that finds markers writes markers.tsv; both have at least
the columns cell_type, gene, log2fc, padj, one row per gene and group, with gene symbols (the var names,
e.g. ISG15) in gene and a cell-type label in cell_type. Markers per cluster also get a cluster column, and
cell_type then holds the cluster's annotation.
Implement the design's steps in its order; one script may hold several small steps; leave out steps whose
method is none. If the design names a tool the image lacks (an R package such as scDblFinder or edgeR), use
the closest available method (e.g. scanpy's scrublet, pydeseq2) and print the substitution. If the var
names are IDs (Ensembl), the gene symbols are in a var column such as gene_symbol. Work one step at a time: WRITE_STEP saves a script and checks it; TEST_STEP runs it on a
3000-cell subset, the first step from "input", every other step from the previous step's name, and shows
its log and outputs. Fix and test again until the step works and its outputs look right (cells kept,
columns, plausible values), then go on to the next step. READ_BUILD shows the design, the subset, your
steps and their test outputs. When every step has passed its test in order, call SAVE_SPEC with one line
per step in order, "<step> | <cpus> | <memory GB> | <minutes>" for the full data (at most 8 cpus, 64 GB,
240 minutes), until it prints "SPEC CHECK: OK".'''

REVIEWER = '''You are an EXPERIMENTAL code reviewer in Geth's lab. A person checked an analysis design; an
engineer implemented it as Python step scripts, tested each on a 3000-cell subset, and saved the pipeline
spec. Review the implementation with fresh eyes. READ_BUILD shows the design ("design"), the spec ("spec"),
the steps and their test status ("steps"), each script ("step:<name>"), its test log and outputs
("test:<name>") and the tables it wrote ("file:<name>/<table>"). Read every script. Check that each design
step is implemented as designed (method, thresholds, what is compared with what, the unit of replication,
the design formula); that raw counts are used where the design needs them (pseudobulk sums, DESeq2) and
normalised values elsewhere; that no step silently drops cells, genes or samples, mixes up conditions or
reverses a contrast; that the outputs follow the contract (obs cell_type; de_results.tsv or markers.tsv with
cell_type, gene, log2fc, padj, gene symbols, cell-type labels, per-cluster markers with a cluster column);
and that the subset results look plausible. Give your verdict with SUBMIT_REVIEW: verdict "approve" or
"revise", and issues as one line per required change, naming the step and what to change (no issues when
you approve). Ask only for changes that affect correctness, not for style. The image has Python only:
accept a printed substitution for an R tool the design names (scrublet for scDblFinder, pydeseq2 for
DESeq2 or edgeR) when it does the same job.'''

ENGINEER_C = '''You are an EXPERIMENTAL pipeline engineer in Geth's lab. You implement an analysis design that a
person has already checked, as a complete Nextflow pipeline: main.nf, with Python scripts in bin/. Geth runs it
in a sandbox: Nextflow 26.10 (strict syntax), local executor, no containers, no network, no files but its
inputs. Geth runs "nextflow run main.nf --input <count matrix .h5ad> --outdir <results folder> --models
<folder of CellTypist models: Immune_All_Low.pkl, Immune_All_High.pkl>". Scripts in bin/ are on the PATH of
every task (start them with "#!/usr/bin/env python3"); they have Python 3 with scanpy, anndata, celltypist,
pydeseq2, harmonypy, numpy, pandas, scipy, scikit-learn, statsmodels, matplotlib, seaborn.
Results contract: publish to params.outdir final.h5ad (the annotated data, with obs["cell_type"]), and
de_results.tsv for condition comparisons and/or markers.tsv for markers, tab separated, with at least the
columns cell_type, gene, log2fc, padj, one row per gene and group, gene symbols in gene and a cell-type label
in cell_type (markers per cluster also get a cluster column). Keep raw counts for the statistics the design
asks of them. If the design names a tool the image lacks (an R package such as scDblFinder or edgeR), use the
closest available method and print the substitution. If the var names are IDs (Ensembl), the gene symbols
are in a var column such as gene_symbol.
Work in small steps: WRITE_FILE saves main.nf or bin/<name>.py (Python scripts are checked); LINT_PIPELINE
checks main.nf; TEST_PIPELINE runs the whole pipeline on a 3000-cell subset and shows the Nextflow output,
the error output of failed tasks, and what was published. READ_PROJECT shows the design ("design"), the
subset ("subset"), your files ("project", "file:<path>"), the last test ("test") and its published tables
("result:<table>"). Fix and test again until the pipeline runs and its results look right (cells kept,
columns, plausible values). Then call SAVE_PIPELINE with the resources for the full data, "<cpus> | <memory
GB> | <minutes>" for the whole pipeline (at most 8 cpus, 64 GB, 240 minutes), until it prints "PIPELINE
CHECK: OK".'''

REVIEWER_C = '''You are an EXPERIMENTAL code reviewer in Geth's lab. A person checked an analysis design; an
engineer implemented it as a Nextflow pipeline (main.nf and Python scripts in bin/), tested it on a 3000-cell
subset, and saved it. Review it with fresh eyes. READ_PROJECT shows the design ("design"), the files
("project", "file:main.nf", "file:bin/<name>.py"), the last test ("test") and the tables it published
("result:<table>"). Read every file. Check that each design step is implemented as designed (method,
thresholds, what is compared with what, the unit of replication, the design formula); that the processes
pass the right data from one to the next; that raw counts are used where the design needs them (pseudobulk
sums, DESeq2) and normalised values elsewhere; that no step silently drops cells, genes or samples, mixes up
conditions or reverses a contrast; that the published results follow the contract (final.h5ad with obs
cell_type; de_results.tsv or markers.tsv with cell_type, gene, log2fc, padj, gene symbols, cell-type labels,
per-cluster markers with a cluster column); and that the subset results look plausible. Give your verdict
with SUBMIT_REVIEW: verdict "approve" or "revise", and issues as one line per required change, naming the
file and what to change (no issues when you approve). Ask only for changes that affect correctness, not for
style. The image has Python only: accept a printed substitution for an R tool the design names (scrublet for
scDblFinder, pydeseq2 for DESeq2 or edgeR) when it does the same job.'''

JUDGE = '''You are an EXPERIMENTAL judge in Geth's lab. Several designers answered the same request
independently, each with a design for the downstream analysis of single-cell RNA-seq count data. Compare
their designs against the data and best practice, then write the single best design: for each step and each
comparison take the soundest choice from any of them, and correct them where they are all wrong. Check
their claims about the data yourself: list the data folder, read its README, call LAB_INSPECT on the count
matrix and LIST_REFERENCES for annotation models. Write the design in the same format as the designers.
steps: one line per step, "<step> | <method> | <tool> | <key parameters> | <why>", where <step> is one of
  qc, doublets, normalisation, feature_selection, dimensionality_reduction, integration, clustering,
  annotation, differential_expression (all nine; write the method "none" and why if a step is not needed).
statistics: one line per comparison the question needs, "<comparison> | <unit of replication> |
  <test or model> | <design formula> | <multiple testing>".
expected: what the results should show if the analysis works, one expectation per line.
Call CHECK_DESIGN with the steps, statistics and expected lines until it prints "DESIGN CHECK: OK". In the
rationale, say for each main choice which design it comes from (A, B, C) or why you changed it.'''

DESIGN_PROMPT = '''Request: {question}
Data folder: {data_dir}
{candidates}
When CHECK_DESIGN has printed "DESIGN CHECK: OK", call SUBMIT_DESIGN with the steps, the statistics and the expected
results exactly as checked, each as a list of lines, and {rationale}.'''

BUILD_PROMPT = '''Request: {question}

The checked design:
{design}

Review of the previous round: {review}

The subset for tests: {subset}

When {save} has printed "{ok}", call SUBMIT_NOTES with short notes: one line per {unit} on what it does and
anything a reviewer should know.'''

REVIEW_PROMPT = '''Request: {question}

The checked design:
{design}

When you have read everything, give your verdict with SUBMIT_REVIEW.'''


def lab_roots():
    return [r for r in os.environ.get("GETH_LAB_DATA", "").split(":") if r]


def inside(path, roots, exact=False):
    path = os.path.normpath(path or "")
    return any(path.startswith(os.path.normpath(r) + "/") or (exact and path == os.path.normpath(r)) for r in roots)


def lab(*args, stdin=None):
    result = subprocess.run(["python3", *args], input=stdin, capture_output=True, text=True, timeout=600)
    return (result.stdout + result.stderr).strip()


def job(run_dir, task, *params):
    result = subprocess.run(["bash", os.path.join(LAB_BIN, "lab_job.sh"), run_dir, task, *params],
                            capture_output=True, text=True)
    return (result.stdout + result.stderr).strip()


def lines(v):
    return "\n".join(str(x) for x in v) if isinstance(v, list) else str(v or "")


# ---------------------------------------------------------------- tools

def lab_list_files(roots):
    def run(dir):
        if not inside(dir, roots, exact=True):
            return f"REFUSED: the lab only lists benchmark folders: {':'.join(roots)}"
        if not os.path.isdir(dir):
            return f"NOT FOUND: no folder {dir}; list its parent folder to see what exists"
        found, base = [], os.path.normpath(dir)
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
        return "\n".join(sorted(found)[:300])
    return Tool("LAB_LIST_FILES", "List a benchmark folder (3 levels deep) with file sizes.",
                string_params(dir="absolute path of the folder"), run)


def lab_read_text(roots):
    def run(path):
        if path.endswith((".h5ad", ".gz")) and inside(path, roots):
            return "REFUSED: binary file; use LAB_INSPECT for count matrices"
        if not inside(path, roots):
            return f"REFUSED: the lab only reads benchmark folders: {':'.join(roots)}"
        if not os.path.isfile(path):
            return f"NOT FOUND: no file {path}; use LAB_LIST_FILES to see what exists"
        with open(path, "rb") as fh:
            return fh.read(8000).decode(errors="replace")
    return Tool("LAB_READ_TEXT", "Read a text file of a benchmark folder (the first 8 kB).",
                string_params(path="absolute path of the file"), run)


def lab_inspect(run_dir, roots):
    def run(h5ad):
        if not (inside(h5ad, roots) and h5ad.endswith(".h5ad")):
            return "REFUSED: only .h5ad files in the benchmark folders can be inspected"
        return job(run_dir, "inspect", "--h5ad", h5ad)
    return Tool("LAB_INSPECT", "Inspect a count matrix (.h5ad): cells, genes, metadata columns, counts per cell "
                "(a scheduler job: a few minutes).", string_params(h5ad="absolute path of the .h5ad file"), run)


def check_design(run_dir):
    def run(steps, statistics, expected):
        p = scratch(run_dir, **{"steps.txt": lines(steps), "statistics.txt": lines(statistics), "expected.txt": lines(expected)})
        return lab(os.path.join(LAB_BIN, "lab_checks.py"), "check-design", p["steps.txt"], p["statistics.txt"],
                   p["expected.txt"], "--save-checked", run_dir)
    return Tool("CHECK_DESIGN", "Check the design's format: steps, statistics and expected lines (each a list of lines "
                "or text). Prints DESIGN CHECK: OK, or the problems.", design_params(), run, check=True)


def design_params(rationale=False):
    array = {"type": "array", "items": {"type": "string"}}
    props = {"steps": dict(array, description="one line per step"),
             "statistics": dict(array, description="one line per comparison"),
             "expected": dict(array, description="one expectation per line")}
    if rationale:
        props["rationale"] = {"type": "string", "description": "the rationale of the main choices"}
    return {"type": "object", "required": list(props), "properties": props}


def submit_design(run_dir):
    def run(steps, statistics, expected, rationale):
        p = scratch(run_dir, **{"final_steps.txt": lines(steps), "final_statistics.txt": lines(statistics),
                                "final_expected.txt": lines(expected), "final_rationale.txt": rationale})
        return lab(os.path.join(LAB_BIN, "lab_checks.py"), "save-design", run_dir, p["final_steps.txt"],
                   p["final_statistics.txt"], p["final_expected.txt"], p["final_rationale.txt"])
    return Tool("SUBMIT_DESIGN", "Submit the final design, exactly as checked: Geth checks it again and saves it.",
                design_params(rationale=True), run, final=True, check=True)


def write_step(run_dir):
    def run(name, code):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "write-step", run_dir, name, stdin=code)
    return Tool("WRITE_STEP", "Save a step script (Python) and check it.",
                string_params(name="the step's name", code="the whole Python script"), run)


def test_step(run_dir):
    def run(name, input_from):
        return job(run_dir, "test_step", "--step", name, "--input_from", input_from)
    return Tool("TEST_STEP", "Run a step on the test subset in the sandbox (a scheduler job) and show its log and "
                "outputs.", string_params(name="the step's name", input_from="'input' for the first step, else "
                                          "the previous step's name"), run)


def read_build(run_dir):
    def run(what):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "read", run_dir, what)
    return Tool("READ_BUILD", "Read the build: 'design', 'spec', 'steps', 'step:<name>', 'test:<name>' or "
                "'file:<name>/<table>'.", string_params(what="what to read"), run)


def save_spec(run_dir):
    def run(spec):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "check-spec", run_dir, stdin=lines(spec))
    return Tool("SAVE_SPEC", "Save the pipeline spec, one line per step in order: '<step> | <cpus> | <memory GB> | "
                "<minutes>'. Prints SPEC CHECK: OK, or the problems.", string_params(spec="the spec lines"), run, check=True)


def write_file(run_dir):
    def run(path_name, content):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "write-file", run_dir, path_name, stdin=content)
    return Tool("WRITE_FILE", "Save main.nf or bin/<name>.py (Python scripts are checked).",
                string_params(path_name="main.nf or bin/<name>.py", content="the whole file"), run)


def arm_c_job(run_dir, task, arm_c, description):
    def run(note=""):
        return job(run_dir, task, *arm_c)
    return Tool(task.upper() if task != "lint" else "LINT_PIPELINE", description,
                {"type": "object", "properties": {"note": {"type": "string", "description": "optional note"}}}, run)


def read_project(run_dir):
    def run(what):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "read-c", run_dir, what)
    return Tool("READ_PROJECT", "Read the project: 'design', 'subset', 'project', 'file:<path>', 'test' or "
                "'result:<table>'.", string_params(what="what to read"), run)


def save_pipeline(run_dir):
    def run(resources):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "check-pipeline", run_dir, stdin=lines(resources))
    return Tool("SAVE_PIPELINE", "Save the pipeline with its full-data resources: '<cpus> | <memory GB> | <minutes>'. "
                "Prints PIPELINE CHECK: OK, or the problems.", string_params(resources="the resources line"), run, check=True)


def submit_notes(run_dir, round_, spec_file, save):
    def run(notes):
        if not os.path.isfile(os.path.join(run_dir, spec_file)):
            return f"REFUSED: nothing has passed {save} yet: call {save} until it prints its OK first."
        with open(os.path.join(run_dir, f"engineer_notes_{round_}.txt"), "w") as fh:
            fh.write(lines(notes).strip() + "\n")
        return "NOTES SAVED. " + lab(os.path.join(LAB_BIN, "lab_build.py"), "read", run_dir, "spec")
    return Tool("SUBMIT_NOTES", "Finish: your notes for the reviewer, one line per step or process.",
                {"type": "object", "required": ["notes"], "properties": {
                    "notes": {"type": "array", "items": {"type": "string"}, "description": "one line each"}}},
                run, final=True)


def submit_review(run_dir, round_):
    def run(verdict, issues):
        return lab(os.path.join(LAB_BIN, "lab_build.py"), "save-review", run_dir, str(round_), verdict, stdin=lines(issues))
    return Tool("SUBMIT_REVIEW", "Give your verdict: 'approve' or 'revise', and the issues, one line per required "
                "change (none when you approve).",
                {"type": "object", "required": ["verdict", "issues"], "properties": {
                    "verdict": {"type": "string", "enum": ["approve", "revise"]},
                    "issues": {"type": "array", "items": {"type": "string"}, "description": "one line per change"}}},
                run, final=True)


def design_text(run_dir):
    parts = []
    for part in ("steps", "statistics", "expected"):
        with open(os.path.join(run_dir, f"lab_design_{part}.txt")) as fh:
            parts.append(f"{part}:\n" + "\n".join(l.rstrip("\n") for l in fh if not l.startswith("#")))
    return "\n\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", required=True, choices=("design", "judge", "engineer", "review", "engineer_c", "review_c"))
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--question", default="")
    ap.add_argument("--lab_skill", default="true")
    ap.add_argument("--build_round", type=int, default=1)
    ap.add_argument("--data_file", default="")
    ap.add_argument("--progress", action="store_true", help="show what the agent does, one line per step, in the terminal")
    for k in ("lab_java_home", "lab_nxf_launcher", "lab_nxf_framework"):
        ap.add_argument(f"--{k}", default="")
    a = ap.parse_args(argv)
    runs, references, roots = os.environ.get("GETH_RUNS_DIR", ""), os.environ.get("GETH_REFERENCES", ""), lab_roots()
    if not (runs and references and roots):
        sys.exit("Geth's site settings are missing: source env.sh before running the lab")
    if not a.run_dir.startswith(runs.rstrip("/") + "/lab/"):
        sys.exit(f"run_dir must be under {runs}/lab/")
    if not inside(a.data_dir, roots, exact=True):
        sys.exit(f"The lab only works on benchmark data (GETH_LAB_DATA: {':'.join(roots)})")
    if a.mode in ("engineer", "engineer_c", "review_c") and not inside(a.data_file, [a.data_dir]):
        sys.exit(f"--data_file must be in the design's data folder ({a.data_dir})")
    try:
        client = model_client()
    except ModelError as e:
        sys.exit(f"Geth: {e}")
    d, skill = a.run_dir, a.lab_skill.lower() == "true"
    all_skills = load_skills(os.path.join(GETH_HOME, "geth", "lab", "skills"))
    skills = lambda *names: {k: v for k, v in all_skills.items() if k in names}
    arm_c = [x for k in ("lab_java_home", "lab_nxf_launcher", "lab_nxf_framework") for x in (f"--{k}", getattr(a, k))]
    trace, log = os.path.join(d, f"harness_trace_{a.mode}.jsonl"), (lambda m: print(m, flush=True))
    question = a.question or open(os.path.join(d, "question.txt")).read().strip()
    previous = os.path.join(d, f"review_{a.build_round - 1}.txt")
    review = open(previous).read() if os.path.isfile(previous) else "none (first round)"

    if a.mode == "design":
        for name, text in (("question.txt", a.question), ("data_dir.txt", a.data_dir),
                           ("lab_arm.txt", "A1 design, with skill" if skill else "A0 design, no skill")):
            with open(os.path.join(d, name), "w") as fh:
                fh.write(text + "\n")
    if a.mode == "judge":
        with open(os.path.join(d, "lab_arm.txt"), "w") as fh:
            fh.write("A1 judged design, from three designs\n")
    if a.mode in ("design", "judge"):
        tools = [lab_list_files(roots), lab_read_text(roots), lab_inspect(d, roots), list_references(references),
                 check_design(d), submit_design(d)]
        candidates = ("\nThe designs to judge:\n" + open(os.path.join(d, "candidates.txt")).read()) if a.mode == "judge" else ""
        agent = Agent("judge" if a.mode == "judge" else "designer", JUDGE if a.mode == "judge" else DESIGNER, tools, client,
                      skills=skills("sc-design-lab") if (skill or a.mode == "judge") else None,
                      max_turns=30 if a.mode == "judge" else 25, trace_path=trace, log=log)
        prompt = DESIGN_PROMPT.format(question=question, data_dir=a.data_dir, candidates=candidates,
                                      rationale="a rationale that says where each main choice comes from" if a.mode == "judge"
                                      else "a short rationale for the main choices")
        done = lambda name, out: out.startswith("DESIGN CHECK: OK")
    elif a.mode in ("engineer", "engineer_c"):
        subset = job(d, "subset", "--data_file", a.data_file)
        if a.mode == "engineer":
            tools = [write_step(d), test_step(d), read_build(d), save_spec(d), submit_notes(d, a.build_round, "build_spec.txt", "SAVE_SPEC")]
            agent = Agent("engineer", ENGINEER, tools, client, skills=skills("sc-build-lab") if skill else None,
                          max_turns=90, trace_path=trace, log=log)
            save, ok, unit = "SAVE_SPEC", "SPEC CHECK: OK", "step"
        else:
            tools = [write_file(d), arm_c_job(d, "lint", arm_c, "Check main.nf (Nextflow lint, a scheduler job)."),
                     arm_c_job(d, "test_pipeline", arm_c, "Run the whole pipeline on the test subset in the sandbox "
                               "(a scheduler job) and show its output."),
                     read_project(d), save_pipeline(d), submit_notes(d, a.build_round, "build_spec_c.txt", "SAVE_PIPELINE")]
            agent = Agent("engineer_c", ENGINEER_C, tools, client, skills=skills("sc-build-lab", "nf-build-lab"),
                          max_turns=120, trace_path=trace, log=log)
            save, ok, unit = "SAVE_PIPELINE", "PIPELINE CHECK: OK", "process"
        prompt = BUILD_PROMPT.format(question=question, design=design_text(d), review=review, subset=subset,
                                     save=save, ok=ok, unit=unit)
        done = lambda name, out: out.startswith("NOTES SAVED")
    else:
        tools = ([read_build(d)] if a.mode == "review" else [read_project(d)]) + [submit_review(d, a.build_round)]
        agent = Agent("reviewer", REVIEWER if a.mode == "review" else REVIEWER_C, tools, client, max_turns=40,
                      trace_path=trace, log=log)
        prompt = REVIEW_PROMPT.format(question=question, design=design_text(d))
        done = lambda name, out: out.startswith("VERDICT:")
    if a.progress:
        agent.progress = TerminalProgress(who=f"lab {agent.name}")
    try:
        result = agent.run(prompt, done=done)
    except ModelError as e:
        print(f"Geth: {e}", flush=True)
        result = None
    if agent.progress:
        agent.progress.close()
    print(f"Model usage: {json.dumps({k: round(v, 4 if k == 'usd' else 1) for k, v in client.usage.items()})}", flush=True)
    print(result or f"The {agent.name} ended without a final answer.", flush=True)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
