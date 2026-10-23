"""Rannoch run: the operator and reporter agents of geth/main.nf (--mode run, --mode report) on Geth's own loop.

    python3 -m harness.run --run_dir <dir> [--report_only]

Same instructions and tools as the Nextflow agents. Two fences the structured answers could not give:
- the operator's outcome goes through SUBMIT_OUTCOME, which refuses "succeeded" unless the last launched attempt's
  pipeline log says it completed;
- the reporter's report goes through SUBMIT_REPORT, which runs the report check: numbers that cannot be traced to
  the results come back to the reporter once, to correct, before the report is saved with Geth's note.
The pipelines themselves still run on Nextflow (run_nfcore.sh), as scheduler jobs.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from .agent import Agent, Tool, string_params
from .llm import Client, ModelError
from .tools import GETH_HOME, scratch

BIN = os.path.join(GETH_HOME, "geth", "bin")
sys.path.insert(0, BIN)
import check_report  # noqa: E402

OPERATOR = '''You are Geth's pipeline operator. You execute a plan that a person has approved, using the
RUN_NFCORE tool. First call it with the approved samplesheet and parameters exactly as given.
If the tool reports STATUS: FAILED, change only what the error names and call RUN_NFCORE again:
the run resumes where it stopped. Never change sample names, file assignments or the pipeline.
If the tool reports STATUS: REFUSED, your change was not allowed: go back to the approved plan.
Make at most 3 RUN_NFCORE calls. If the error cannot be fixed within these rules, stop and report it.
Never claim success unless the tool printed STATUS: SUCCESS.'''

OPERATOR_PROMPT = '''Execute the approved plan now: call RUN_NFCORE with its pipeline, samplesheet_csv, params_json,
contrasts_csv and profile (pass empty strings where the plan has none). The approved plan:
pipeline: {pipeline}
samplesheet_csv:
{sheet}
params_json:
{params}
contrasts_csv:
{sheet2}
profile: {profile}

When you are done, call SUBMIT_OUTCOME with: whether the run succeeded, the OUTDIR printed by the tool (or
"none"), every change you made to the plan (or an empty list), and the last error (or "none").'''

REPORTER = '''You are Geth's reporting assistant. You write concise, factual analysis reports in Markdown
for biologists. Copy tables and numbers from the COLLECT_RESULTS output exactly as printed: do not
convert units, recompute, round differently, estimate ratios or invent values. Do not add links.
Say clearly when something is missing. Interpret results in the light of the data actually used
(for example a reference subset, or tiny test data) before suggesting lab or sequencing changes.'''

REPORTER_PROMPT = '''Original request: {question}
The approved plan: pipeline nf-core/{pipeline}
samplesheet:
{sheet}
parameters: {params}
{sheet2_part}rationale: {rationale}
The run's outcome: {outcome}

Call COLLECT_RESULTS once with the plan's pipeline, then write the report with these sections:
Summary; Samples (how input files were grouped, from the plan); Quality control (copy the QC tables);
Results; Caveats and next steps. If the run failed, explain why and what a person should check instead.
Then call SUBMIT_REPORT with the Markdown report. If it lists numbers it cannot trace to the results, correct
them from the COLLECT_RESULTS output or remove them, and submit again.'''


def read(run_dir, name, default=""):
    path = os.path.join(run_dir, name)
    if not os.path.isfile(path):
        return default
    with open(path, errors="replace") as fh:
        return fh.read()


def write(run_dir, name, text):
    with open(os.path.join(run_dir, name), "w") as fh:
        fh.write(text)


def load_plan(run_dir):
    pipeline = read(run_dir, "plan_pipeline.txt").strip()
    sheet2 = "".join(read(run_dir, f) for f in ("plan_contrasts.csv", "plan_barcodes.csv"))
    return {"pipeline": pipeline, "sheet": read(run_dir, "plan_samplesheet.csv").strip(),
            "params": read(run_dir, "plan_params.json").strip(), "sheet2": sheet2.strip(),
            "profile": read(run_dir, "plan_profile.txt").strip(), "rationale": read(run_dir, "plan_rationale.txt").strip(),
            "question": read(run_dir, "question.txt").strip()}


def last_attempt(run_dir):
    attempts = sorted(glob.glob(os.path.join(run_dir, "attempt_*")), key=lambda p: int(p.rsplit("_", 1)[1]))
    launched = [a for a in attempts if os.path.isfile(os.path.join(a, "nextflow.log")) and not os.path.isfile(os.path.join(a, "STOPPED"))]
    return launched[-1] if launched else None


def run_nfcore_tool(run_dir, calls):
    def run(pipeline, samplesheet_csv, params_json, contrasts_csv="", profile=""):
        calls.append(pipeline)
        p = scratch(run_dir, **{"samplesheet.csv": samplesheet_csv, "params.json": params_json, "contrasts.csv": contrasts_csv})
        result = subprocess.run(["bash", os.path.join(BIN, "run_nfcore.sh"), run_dir, pipeline, p["samplesheet.csv"],
                                 p["params.json"], p["contrasts.csv"], profile.strip()],
                                capture_output=True, text=True, cwd=os.path.join(run_dir, ".harness"))
        return (result.stdout + result.stderr).strip()
    return Tool("RUN_NFCORE", "Launch the approved nf-core run (one gated, resumable attempt) and print a short "
                "status digest: STATUS: SUCCESS, FAILED (with the error) or REFUSED (a change that was not allowed).",
                string_params(pipeline="pipeline name", samplesheet_csv="the samplesheet, CSV text",
                              params_json="the parameters, a JSON object", contrasts_csv="the second sheet, or ''",
                              profile="analysis profile, or ''"), run, check=True)


def completed(attempt):
    return bool(attempt) and "Pipeline completed successfully" in read(attempt, "nextflow.log")


def save_outcome(run_dir, outcome):
    """outcome.txt, as SAVE_OUTCOME of geth/main.nf writes it (lists as Groovy prints them: [a, b])."""
    listed = lambda v: "[" + ", ".join(v) + "]"
    write(run_dir, "outcome.txt", f"succeeded: {str(outcome['succeeded']).lower()}\nattempts: {outcome['attempts']}\n"
              f"outdir: {outcome['outdir']}\nchanges_to_plan: {listed(outcome['fixes_applied'])}\n"
              f"annotations: {listed(outcome['annotations'])}\nlast_error: {outcome['last_error']}\n")


def submit_outcome_tool(run_dir, outcome, calls):
    """The operator's final answer. The claim must agree with the pipeline log of the last launched attempt, either
    way; the number of attempts is the number of RUN_NFCORE calls Geth saw, not the model's count."""
    def run(succeeded, outdir, changes_to_plan, last_error):
        ok = str(succeeded).lower() in ("true", "yes", "1")
        done = completed(last_attempt(run_dir))
        if ok and not done:
            return ("REFUSED: the last launched attempt did not complete (its pipeline log has no 'Pipeline completed "
                    "successfully'): report succeeded=false with its error, or fix it with RUN_NFCORE.")
        if done and not ok:
            return "REFUSED: the last launched attempt completed successfully (its pipeline log says so): report succeeded=true."
        changes = changes_to_plan if isinstance(changes_to_plan, list) else [str(changes_to_plan)] if changes_to_plan else []
        outcome.update(succeeded=ok, attempts=len(calls), outdir=str(outdir or "none"),
                       fixes_applied=[str(c) for c in changes if str(c).strip() and str(c).lower() != "none"],
                       annotations=[], last_error=str(last_error or "none"))
        save_outcome(run_dir, outcome)
        return "OUTCOME SAVED"
    array = {"type": "array", "items": {"type": "string"}}
    return Tool("SUBMIT_OUTCOME", "Report the run's outcome, when you are done with RUN_NFCORE. Geth checks the claim "
                "against the pipeline's log.",
                {"type": "object", "required": ["succeeded", "outdir", "changes_to_plan", "last_error"],
                 "properties": {"succeeded": {"type": "boolean"},
                                "outdir": {"type": "string", "description": "the OUTDIR printed by RUN_NFCORE, or 'none'"},
                                "changes_to_plan": dict(array, description="every change you made to the plan, or []"),
                                "last_error": {"type": "string", "description": "the last error, or 'none'"}}},
                run, final=True)


def collect_tool(run_dir):
    def run(pipeline):
        result = subprocess.run(["python3", os.path.join(BIN, "collect_results.py"), run_dir, pipeline.replace("nf-core/", "")],
                                capture_output=True, text=True, timeout=1800)
        return (result.stdout + result.stderr).strip()
    return Tool("COLLECT_RESULTS", "Summarise the run's results folder as ready-to-copy Markdown tables.",
                string_params(pipeline="pipeline name, e.g. rnaseq"), run)


def submit_report_tool(run_dir, pipeline, attempts):
    """The reporter's final answer: the report check of FINALIZE_REPORT, with one chance to correct what it finds."""
    tries = []

    def run(report):
        report = check_report.strip_fences(report)
        summary, unverified, links = check_report.check(report, run_dir, pipeline, str(attempts()))
        tries.append(summary)
        if (unverified or links) and len(tries) < 2:
            return (f"NOT SAVED. {summary}\nCorrect these values from the COLLECT_RESULTS output (copied exactly) or "
                    "remove them, then call SUBMIT_REPORT again with the whole report.")
        os.makedirs(os.path.join(run_dir, ".harness"), exist_ok=True)
        write(run_dir, ".harness/report.raw.md", report + "\n")
        write(run_dir, "report_check.txt", summary + "\n")
        if unverified or links:
            report += ("\n\n---\n> **Automatic check:** these values could not be traced to the pipeline results "
                       "and may be wrong: " + ", ".join(sorted(set(unverified)) + links) + ".")
        write(run_dir, "report.md", report + "\n")
        return f"REPORT SAVED. {summary}"
    return Tool("SUBMIT_REPORT", "Submit the whole Markdown report: Geth checks every number against the results, "
                "then saves it.", string_params(report="the whole report, in Markdown"), run, final=True)


def outcome_from_file(run_dir):
    """outcome.txt back as an outcome (lists as one entry, as savedList() of geth/main.nf)."""
    saved = {}
    for line in read(run_dir, "outcome.txt").splitlines():
        if ": " in line:
            k, v = line.split(": ", 1)
            saved[k] = v
    listed = lambda v: [v.strip("[]")] if v and v != "[]" else []
    return {"succeeded": saved.get("succeeded") == "true", "attempts": int(saved.get("attempts", "0") or 0),
            "outdir": saved.get("outdir", "none"), "fixes_applied": listed(saved.get("changes_to_plan", "")),
            "annotations": listed(saved.get("annotations", "")), "last_error": saved.get("last_error", "none")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--report_only", action="store_true", help="write the report again from a finished run's results")
    a = ap.parse_args(argv)
    runs = os.environ.get("GETH_RUNS_DIR", "")
    if not runs or not a.run_dir.startswith(runs.rstrip("/") + "/"):
        sys.exit(f"run_dir must be under {runs}/ (source env.sh first)")
    if not os.path.isfile(os.path.join(a.run_dir, "APPROVED")):
        sys.exit(f"The plan in {a.run_dir} has not been approved: run `geth approve` first")
    plan = load_plan(a.run_dir)
    if plan["pipeline"] == "sc_downstream":
        sys.exit("The single-cell toolbox's analyst is not on the Rannoch runner yet (R4b): run without GETH_RUNNER=harness")
    try:
        client = Client()
    except ModelError as e:
        sys.exit(f"Geth: {e}")
    log = lambda m: print(m, flush=True)
    trace = os.path.join(a.run_dir, f"harness_trace_{'report' if a.report_only else 'run'}.jsonl")
    os.makedirs(os.path.join(a.run_dir, ".harness"), exist_ok=True)

    if a.report_only:
        if not os.path.isfile(os.path.join(a.run_dir, "outcome.txt")):
            sys.exit(f"No finished run in {a.run_dir}: nothing to report")
        outcome = outcome_from_file(a.run_dir)
    else:
        outcome, calls = {}, []
        operator = Agent("operator", OPERATOR, [run_nfcore_tool(a.run_dir, calls), submit_outcome_tool(a.run_dir, outcome, calls)],
                         client, max_turns=10, trace_path=trace, log=log)
        try:  # a gate refusal is a check's refusal: the same one again and again ends the loop
            operator.run(OPERATOR_PROMPT.format(**{k: plan[k] or "''" for k in ("pipeline", "sheet", "params", "sheet2", "profile")}),
                         done=lambda name, out: out.startswith("OUTCOME SAVED") or "STATUS: SUCCESS" in out)
        except ModelError as e:
            log(f"Geth: {e}")
        if not outcome:  # the operator gave no outcome: say what the disk says
            ok = completed(last_attempt(a.run_dir))
            outcome.update(succeeded=ok, attempts=len(calls), outdir=os.path.join(a.run_dir, "results") if ok else "none",
                           fixes_applied=[], annotations=[], last_error="none" if ok else "the operator ended without reporting an outcome")
            save_outcome(a.run_dir, outcome)

    reporter = Agent("reporter", REPORTER, [collect_tool(a.run_dir),
                                            submit_report_tool(a.run_dir, plan["pipeline"], lambda: outcome.get("attempts", 0))],
                     client, max_turns=6, trace_path=trace, log=log)
    sheet2_part = f"second sheet:\n{plan['sheet2']}\n" if plan["sheet2"] else ""
    try:
        result = reporter.run(REPORTER_PROMPT.format(question=plan["question"], pipeline=plan["pipeline"], sheet=plan["sheet"],
                                                     params=plan["params"], sheet2_part=sheet2_part, rationale=plan["rationale"],
                                                     outcome=json.dumps(outcome)),
                              done=lambda name, out: out.startswith("REPORT SAVED"))
    except ModelError as e:
        log(f"Geth: {e}")
        result = None
    if result is None:  # no report from the reporter: say so in the report, not nothing
        write(a.run_dir, "report.md", f"# Report\n\nThe reporting agent did not write a report (see geth_{'report' if a.report_only else 'run'}.log). "
              f"The run's outcome:\n\n```\n{read(a.run_dir, 'outcome.txt')}```\n")
        write(a.run_dir, "report_check.txt", "REPORT CHECK: no report was written\n")
    print(read(a.run_dir, "report_check.txt").strip() or "No report was saved.", flush=True)
    print(f"Model usage: {json.dumps({k: round(v, 1) for k, v in client.usage.items()})}", flush=True)
    return 0 if (a.report_only or outcome.get("succeeded")) and result else 1


if __name__ == "__main__":
    sys.exit(main())
