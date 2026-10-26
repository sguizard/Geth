"""geth legion: the coordinator agent, at the project's three decision points.

    python3 -m harness.project --run_dir <project dir> --mode plan [--ask terminal|file|none|off] [--answers <file>]
    python3 -m harness.project --run_dir <project dir> --mode review --step <id>
    python3 -m harness.project --run_dir <project dir> --mode summary

- plan: reads the delivery and proposes the steps (SUBMIT_STEPS, checked by geth_project.py check);
- review: after a step finished, decides to continue, stop, or propose new steps (DECIDE);
- summary: writes the project report from the steps' reports (SUBMIT_REPORT, checked against every step's results).
The coordinator never runs anything: the project's runner (geth_project.py run) does, with the usual commands.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from .agent import Agent, Tool, string_params
from .ask import FileAnswerer, Nobody, TerminalAsker, TerminalProgress, ask_tool
from .llm import ModelError, model_client
from .tools import GETH_HOME, inspect_reads, list_files, list_references, read_text, scratch

BIN = os.path.join(GETH_HOME, "geth", "bin")
PROJECT = os.path.join(BIN, "geth_project.py")
sys.path.insert(0, BIN)
import check_report  # noqa: E402
import geth_project as gp  # noqa: E402

COORDINATOR = '''You are Geth's coordinator. A scientist asks a question about a delivery of data. You split the work into
steps that Geth's specialists can do, in order, and you never improvise an analysis that no specialist does.
First inspect the delivery: list it, read every README or metadata text file, and measure the reads when the
files do not say what they are. Then call LIST_CAPABILITIES and LIST_REFERENCES.
Plan as few steps as the question needs:
- a pipeline step for each kind of data in the delivery that the question needs (a delivery may hold several,
  e.g. RNA-seq and ATAC-seq: give each step its own data folder then, the one that holds that kind's README,
  sample table and reference, not only its reads);
- a follow-up step only when the question asks for what it does (a comparison between conditions, cell types),
  and only after the step it builds on: a question that asks to quantify, count or call needs no follow-up;
- a reference step when a pipeline step needs a genome that the catalogue lacks: find it with FIND_GENOME and
  list it in that pipeline step's after;
- a gap for every part of the question that no specialist does: what it is, the nf-core pipeline that would do
  it (SEARCH_NFCORE) if there is one, and what the earlier steps hand over to it.
Each step's question tells its specialist exactly what to do, in the scientist's terms; for a comparison, say
what is compared with what. Ask the scientist (ASK_USER) only what the files do not say and the choice of steps
depends on; each step's own details (strandedness, parameters) are for its specialist, who will ask if needed.
Call CHECK_STEPS until it prints "STEP CHECK: OK", then SUBMIT_STEPS with exactly that list and a short rationale.'''

PLAN_PROMPT = '''Request: {question}
Delivery: {data_dir}'''

REVIEWER = '''You are Geth's coordinator, reviewing a project between steps. A step has just finished (or failed). Read its
report and decide what happens next, in the scientist's interest:
- continue: the remaining steps still make sense as approved;
- stop: the project cannot answer the question (say why, and what a person should check);
- revise: the remaining steps must change (e.g. a follow-up's comparison, or a gap that a result reveals). Give
  the whole new step list: the steps that have started stay exactly as they are. A person approves it first.
Never revise to work around a failure by changing the data or the design of a finished step. Call DECIDE.'''

REVIEW_PROMPT = '''The project's question: {question}

The approved steps and where they stand:
{steps}

Step '{step}' just ended: {state}.
Its outcome:
{outcome}
Its report (first part):
{report}'''

SUMMARIZER = '''You are Geth's coordinator, writing the project report for the scientist. Read each step's report
(READ_STEP) and answer the project's question from them. Copy numbers exactly as the reports print them: do not
recompute, round differently or invent values. Do not add links. Sections: Summary (the answer, in a few
sentences); Steps (what each step did, its run name, and its outcome); Results (the findings that answer the
question, step by step; say plainly that a lab step's results come from agent-written code and are
EXPERIMENTAL); Gaps (what no step could do, and what would do it); Caveats and next steps.
Then call SUBMIT_REPORT with the whole report in Markdown.'''

SUMMARY_PROMPT = '''The project's question: {question}

The steps and where they ended:
{steps}'''


def steps_text(pdir, doc):
    lines = []
    for s in doc.get("steps", []):
        what = s.get("pipeline") or s.get("species") or s.get("nfcore") or ""
        run = os.path.basename(gp.step_run(pdir, s["id"])) if s.get("kind") in ("pipeline", "lab") else ""
        lines.append(f"- {s['id']} ({s.get('kind')} {what}{', after ' + ', '.join(s.get('after') or []) if s.get('after') else ''})"
                     f": {gp.status(pdir, s)}{'; run ' + run if run else ''}. Question: {s.get('question', '')}"
                     + (f" Gap: {s.get('suggestion')}" if s.get("kind") == "gap" else ""))
    return "\n".join(lines)


def project_cli(*args):
    result = subprocess.run(["python3", PROJECT, *args], capture_output=True, text=True, timeout=900)
    return (result.stdout + result.stderr).strip()


# ---------------------------------------------------------------- tools

STEP = {"type": "object", "required": ["id", "kind", "question"], "properties": {
    "id": {"type": "string", "description": "short name, lower case: e.g. count, cells, genome"},
    "kind": {"type": "string", "enum": list(gp.KINDS)},
    "question": {"type": "string", "description": "what this step must do, in the scientist's terms"},
    "after": {"type": "array", "items": {"type": "string"}, "description": "ids of the steps it builds on"},
    "pipeline": {"type": "string", "description": "kind pipeline: the pipeline name, e.g. rnaseq"},
    "data": {"type": "string", "description": "kind pipeline on sequencing data: its folder in the delivery"},
    "species": {"type": "string", "description": "kind reference, from FIND_GENOME, e.g. mus_musculus"},
    "assembly": {"type": "string", "description": "kind reference, from FIND_GENOME"},
    "release": {"type": "string", "description": "kind reference, the Ensembl release, from FIND_GENOME"},
    "label": {"type": "string", "description": "kind reference: e.g. Mus musculus (mouse)"},
    "suggestion": {"type": "string", "description": "kind gap: what is missing and what would fill it"},
    "nfcore": {"type": "string", "description": "kind gap: the nf-core pipeline that would do it, if any"}}}


def clean(steps, pdir):
    """The steps as the check reads them: no empty fields, after as a list, data folders as absolute paths."""
    out = []
    for s in steps if isinstance(steps, list) else []:
        s = {k: v for k, v in (s if isinstance(s, dict) else {}).items() if v not in ("", None, [])}
        if isinstance(s.get("after"), str):
            s["after"] = [a.strip() for a in s["after"].split(",") if a.strip()]
        out.append(s)
    return gp.normalise(pdir, {"steps": out})["steps"]


def check_steps_tool(pdir):
    def run(steps):
        path = scratch(pdir, **{"steps.json": json.dumps({"steps": clean(steps, pdir)}, indent=2)})["steps.json"]
        return project_cli("check", pdir, path)
    return Tool("CHECK_STEPS", "Check a step list. Prints STEP CHECK: OK, or the problems, and notes such as the "
                "size of a download.", {"type": "object", "required": ["steps"],
                                         "properties": {"steps": {"type": "array", "items": STEP}}}, run, check=True)


def submit_steps_tool(pdir, proposed=False):
    def run(steps, rationale):
        doc = {"steps": clean(steps, pdir), "rationale": str(rationale)}
        path = scratch(pdir, **{"final_steps.json": json.dumps(doc, indent=2)})["final_steps.json"]
        result = project_cli("check", pdir, path)
        if result.startswith("STEP CHECK: OK"):
            gp.save(os.path.join(pdir, "steps.proposed.json" if proposed else "steps.json"), doc)
            open(os.path.join(pdir, "steps_check.txt"), "w").write(result + "\n")
        return result
    return Tool("SUBMIT_STEPS", "Submit the project's steps, exactly as checked, with a short rationale. Geth checks "
                "them again and saves them for a person to approve.",
                {"type": "object", "required": ["steps", "rationale"], "properties": {
                    "steps": {"type": "array", "items": STEP}, "rationale": {"type": "string"}}},
                run, final=True, check=True)


def capabilities_tool(pdir):
    lab = (gp.load(os.path.join(pdir, "options.json"), {}) or {}).get("lab", False)
    return Tool("LIST_CAPABILITIES", "What a project's steps may be: the pipelines Geth runs, their follow-ups, "
                "reference downloads, gaps (and the lab, if this project allows it).", {"type": "object", "properties": {}},
                lambda: gp.capabilities(lab))


def nfcore_tool():
    return Tool("SEARCH_NFCORE", "Search nf-core's pipelines (all of them, not only those Geth runs) by words, e.g. "
                "'small RNA'. Says which ones Geth runs.", string_params(words="a few words"), lambda words: gp.nfcore(str(words).split()))


def genome_tool():
    return Tool("FIND_GENOME", "Find a species' current genome and annotation in Ensembl: species, assembly, release "
                "and download sizes, for a reference step.", string_params(species="scientific or common name"),
                lambda species: gp.ensembl(str(species)))


def lab_tables(pdir, sid, lines=60):
    """A lab step's result tables (agent-written code: EXPERIMENTAL), as text."""
    _, build = gp.lab_runs(pdir, sid)
    out = []
    for path in sorted(glob.glob(os.path.join(build, "results", "**", "*.tsv"), recursive=True))[:12]:
        out.append(f"--- {os.path.relpath(path, build)}\n" + "".join(gp.read(path).splitlines(True)[:lines]))
    return "\n".join(out)


def read_step_tool(pdir):
    def run(step):
        run_dir = gp.step_run(pdir, step)
        design, build = gp.lab_runs(pdir, step)
        if os.path.isdir(design):  # a lab step (EXPERIMENTAL)
            parts = [f"Lab step {step} (EXPERIMENTAL: agent-written code). Design: {os.path.basename(design)}; build: "
                     f"{os.path.basename(build)}; state: {gp.read(os.path.join(build, 'build_state.txt')).strip() or 'not built'}"]
            for f in ("lab_design_steps.txt", "lab_design_statistics.txt", "review_1.txt", "review_2.txt"):
                text = gp.read(os.path.join(design if f.startswith("lab_") else build, f)).strip()
                if text:
                    parts.append(f"--- {f}\n{text[:4000]}")
            parts.append(lab_tables(pdir, step) or "(no result tables)")
            return "\n".join(parts)
        if not os.path.isdir(run_dir):
            return f"NOT FOUND: step '{step}' has no run (gaps and reference steps have none)"
        parts = [f"Run {os.path.basename(run_dir)}"]
        for f in ("plan_pipeline.txt", "outcome.txt", "report.md", "report_check.txt"):
            parts.append(f"--- {f}\n{gp.read(os.path.join(run_dir, f)).strip()[:12000] or '(none)'}")
        return "\n".join(parts)
    return Tool("READ_STEP", "Read a step's run: pipeline, outcome, report and its check.",
                string_params(step="the step's id"), run)


def decide_tool(pdir, step):
    def run(action, reason, steps=None, rationale=""):
        action = str(action).strip().lower()
        if action not in ("continue", "stop", "revise"):
            return "REFUSED: action is continue, stop or revise"
        if action == "revise":
            doc = gp.approved_doc(pdir, quiet=True) or {}
            started = [s["id"] for s in doc.get("steps", []) if gp.status(pdir, s) != "todo"]
            new = {"steps": clean(steps, pdir), "rationale": str(rationale or reason)}
            problems, notes = gp.check(pdir, new, started)
            if problems:
                return gp.check_report_text(problems, notes)
            gp.save(os.path.join(pdir, "steps.proposed.json"), new)
            open(os.path.join(pdir, "steps_check.txt"), "w").write(gp.check_report_text(problems, notes) + "\n")
        reviews = gp.load(os.path.join(pdir, "reviews.json"), {}) or {}
        reviews[step] = {"action": action, "reason": str(reason)}
        gp.save(os.path.join(pdir, "reviews.json"), reviews)
        gp.log(pdir, f"coordinator after {step}: {action}: {reason}")
        return f"DECISION SAVED: {action}"
    return Tool("DECIDE", "Decide what happens after this step: continue, stop or revise (with the whole new step "
                "list, started steps unchanged, and a rationale).",
                {"type": "object", "required": ["action", "reason"], "properties": {
                    "action": {"type": "string", "enum": ["continue", "stop", "revise"]},
                    "reason": {"type": "string", "description": "why, from the report"},
                    "steps": {"type": "array", "items": STEP, "description": "revise only: the whole new step list"},
                    "rationale": {"type": "string", "description": "revise only"}}}, run, final=True, check=True)


def project_report_tool(pdir, doc):
    """The project report, checked against every finished step's results (one chance to correct)."""
    tries = []

    def run(report):
        report = check_report.strip_fences(str(report))
        sources = []
        for s in doc.get("steps", []):
            run_dir = gp.step_run(pdir, s["id"])
            if s.get("kind") == "pipeline" and os.path.isfile(os.path.join(run_dir, "outcome.txt")):
                outcome = gp.read(os.path.join(run_dir, "outcome.txt"))
                attempts = next((l.split(": ", 1)[1] for l in outcome.splitlines() if l.startswith("attempts: ")), "0")
                sources.append(check_report.facts_of(run_dir, gp.read(os.path.join(run_dir, "plan_pipeline.txt")).strip(), attempts))
                sources.append((gp.read(os.path.join(run_dir, "report.md")), []))  # what the step's report quoted
        extra = gp.read(os.path.join(pdir, "question.txt")) + json.dumps(doc)
        extra += "".join(lab_tables(pdir, s["id"], lines=100000) for s in doc.get("steps", []) if s.get("kind") == "lab")
        summary, unverified, links = check_report.check_against(report, sources, extra)
        tries.append(summary)
        if (unverified or links) and len(tries) < 2:
            return (f"NOT SAVED. {summary}\nCorrect these values from the steps' reports (copied exactly) or remove "
                    "them, then call SUBMIT_REPORT again with the whole report.")
        if unverified or links:
            report += ("\n\n---\n> **Automatic check:** these values could not be traced to the steps' results and "
                       "may be wrong: " + ", ".join(sorted(set(unverified)) + links) + ".")
        with open(os.path.join(pdir, "report.md"), "w") as fh:
            fh.write(report + "\n")
        with open(os.path.join(pdir, "report_check.txt"), "w") as fh:
            fh.write(summary + "\n")
        return f"REPORT SAVED. {summary}"
    return Tool("SUBMIT_REPORT", "Submit the whole project report in Markdown: Geth checks every number against the "
                "steps' results, then saves it.", string_params(report="the whole report, in Markdown"), run, final=True)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--mode", choices=("plan", "review", "summary"), required=True)
    ap.add_argument("--step", default="")
    ap.add_argument("--ask", choices=("terminal", "file", "none", "off"), default="none")
    ap.add_argument("--answers", default="")
    ap.add_argument("--step_run", action="append", default=[], help="(for the sandbox: a step's run folder, read-only)")
    ap.add_argument("--progress", action="store_true", help="show what the coordinator does, one line per step")
    a = ap.parse_args(argv)
    runs, data_root, references = (os.environ.get(v, "") for v in ("GETH_RUNS_DIR", "GETH_DATA_ROOT", "GETH_REFERENCES"))
    if not (runs and data_root and references):
        sys.exit("Geth's site settings are missing: source env.sh first")
    pdir = a.run_dir
    if not pdir.startswith(runs.rstrip("/") + "/projects/"):
        sys.exit(f"run_dir must be under {runs}/projects/")
    try:
        client = model_client()
    except ModelError as e:
        sys.exit(f"Geth: {e}")
    question = gp.read(os.path.join(pdir, "question.txt")).strip()
    trace, log = os.path.join(pdir, f"harness_trace_{a.mode}.jsonl"), (lambda m: print(m, flush=True))

    if a.mode == "plan":
        tools = [list_files(data_root), read_text(data_root), inspect_reads(data_root), list_references(references),
                 capabilities_tool(pdir), nfcore_tool(), genome_tool(), check_steps_tool(pdir), submit_steps_tool(pdir)]
        if a.ask != "off":
            asker = FileAnswerer(a.answers, model_client(site=True)) if a.ask == "file" else {"terminal": TerminalAsker, "none": Nobody}[a.ask]()
            tools.append(ask_tool(asker, os.path.join(pdir, "project_questions.md")))
        agent = Agent("coordinator", COORDINATOR, tools, client, max_turns=30, trace_path=trace, log=log)
        prompt = PLAN_PROMPT.format(question=question, data_dir=gp.read(os.path.join(pdir, "data_dir.txt")).strip())
        done = lambda name, out: out.startswith("STEP CHECK: OK")
    elif a.mode == "review":
        doc = gp.approved_doc(pdir, quiet=True) or {}
        step = next((s for s in doc.get("steps", []) if s["id"] == a.step), None)
        if step is None:
            sys.exit(f"No approved step '{a.step}'")
        run_dir = gp.step_run(pdir, a.step)
        tools = [read_text(data_root), list_files(data_root), read_step_tool(pdir), capabilities_tool(pdir),
                 nfcore_tool(), check_steps_tool(pdir), decide_tool(pdir, a.step)]
        agent = Agent("coordinator", REVIEWER, tools, client, max_turns=12, trace_path=trace, log=log)
        if step.get("kind") == "lab":  # a lab step: its build's state, reviews and result tables
            outcome = gp.read(os.path.join(gp.lab_runs(pdir, a.step)[1], "build_state.txt")).strip() or "(none)"
            report = read_step_tool(pdir).func(a.step)[:6000]
        else:
            outcome = gp.read(os.path.join(run_dir, "outcome.txt")).strip() or "(none)"
            report = gp.read(os.path.join(run_dir, "report.md")).strip()[:6000] or "(none)"
        prompt = REVIEW_PROMPT.format(question=question, steps=steps_text(pdir, doc), step=a.step,
                                      state=gp.status(pdir, step), outcome=outcome, report=report)
        done = lambda name, out: out.startswith("DECISION SAVED")
    else:
        doc = gp.approved_doc(pdir, quiet=True) or {}
        agent = Agent("coordinator", SUMMARIZER, [read_step_tool(pdir), project_report_tool(pdir, doc)], client,
                      max_turns=12, trace_path=trace, log=log, text_answer=("SUBMIT_REPORT", "report", 400))
        prompt = SUMMARY_PROMPT.format(question=question, steps=steps_text(pdir, doc))
        done = lambda name, out: out.startswith("REPORT SAVED")
    if a.progress or a.ask == "terminal":
        agent.progress = TerminalProgress(who="coordinator")
    try:
        result = agent.run(prompt, done=done)
    except ModelError as e:
        log(f"Geth: {e}")
        result = None
    if agent.progress:
        agent.progress.close()
    print(f"Model usage: {json.dumps({k: round(v, 4 if k == 'usd' else 1) for k, v in client.usage.items()})}", flush=True)
    print(result or f"The coordinator ended without a final answer ({a.mode}).", flush=True)
    return 0 if result else 1


if __name__ == "__main__":
    sys.exit(main())
