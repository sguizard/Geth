"""geth run / geth report: the operator (or the single-cell analyst) runs the approved plan, the reporter writes
report.md.

    python3 -m harness.run --run_dir <dir> [--report_only]

Two fences (which Geth 1.x's Nextflow agents, with their typed final answers, could not give):
- the operator's outcome goes through SUBMIT_OUTCOME, which refuses "succeeded" unless the last launched attempt's
  pipeline log says it completed;
- the reporter's report goes through SUBMIT_REPORT, which runs the report check: numbers that cannot be traced to
  the results come back to the reporter once, to correct, before the report is saved with Geth's note.
The pipelines run on Nextflow (run_nfcore.sh), as scheduler jobs. A single-cell downstream design
(pipeline sc_downstream) goes to the analyst instead of the operator: Geth's toolbox, as scheduler jobs too
(bin/sc_job.sh, geth/jobs.nf).
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from .agent import Agent, Tool, load_skills, string_params
from .ask import TerminalProgress
from .llm import ModelError, model_client
from .tools import GETH_HOME, pipeline_options, sc_job, scratch

BIN = os.path.join(GETH_HOME, "geth", "bin")
sys.path.insert(0, BIN)
import check_report  # noqa: E402

OPERATOR = '''You are Geth's pipeline operator. You execute a plan that a person has approved, using the
RUN_NFCORE tool. First call it to run the approved plan as approved (only the pipeline name).
If the tool reports STATUS: FAILED, change only what the error names and call RUN_NFCORE again:
the run resumes where it stopped. When the error names a tool's option, find the parameter that sets it
with PIPELINE_OPTIONS (search for the option's name); never invent a parameter name. Never change sample names, file assignments or the pipeline.
If the tool reports STATUS: REFUSED, your change was not allowed: go back to the approved plan.
Make at most 3 RUN_NFCORE calls. If the error cannot be fixed within these rules, stop and report it.
Never claim success unless the tool printed STATUS: SUCCESS.'''

OPERATOR_PROMPT = '''Execute the approved plan now: call RUN_NFCORE with only its pipeline, which runs the approved plan
exactly as approved. After a failure, pass in full only what you change (the whole samplesheet, or all the
parameters); what you leave out stays as approved. The approved plan:
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

ANALYST = '''You are Geth's single-cell analyst. You run a downstream analysis design that a person has
approved, with the SC_ANALYSE tool, then interpret the diagnostics.
First call SC_ANALYSE with the approved design lines exactly as given. Read the diagnostics: cells kept
per QC step, doublet rate, clusters per resolution, and for each cluster its size, top markers, the
canonical marker panel and, when the design has a CellTypist model, the CellTypist label with its agreement.
You may call SC_ANALYSE once more, only if a diagnostic shows a real problem, changing only tunable keys
(QC thresholds, doublet rate/threshold, HVG number, neighbours, Leiden resolutions/chosen) and adding a
line justification=... that cites the diagnostic. If STATUS: REFUSED, do not insist: report.
The diagnostics end with FLAGS computed by Geth: for each flag, either revise the design to address it
or state in your final answer why it needs no change. Do not describe the results as better than the
diagnostics show.
Then annotate every cluster of the final analysis from its markers, supported by CellTypist if the design
has a model; write "uncertain" when markers and CellTypist disagree, or, without a model, when the markers do
not point to one cell type. Save the annotations with SAVE_ANNOTATIONS
(one line per cluster: "cluster <id>: <cell type> (<key markers>)"). Never claim success unless the
tool printed STATUS: SUCCESS.'''

ANALYST_PROMPT = '''Run the approved design now: call SC_ANALYSE with this design exactly as given (a JSON object; for a
revision you may send the changed keys and the justification as key=value lines instead):
{params}

When you are done, call SUBMIT_OUTCOME with: whether the analysis succeeded, the OUTDIR of the final analysis,
every change you made to the design with its justification, and how you handled each FLAG (or an empty list),
one annotation per cluster as "cluster <id>: <cell type> (<key markers>)" (also saved with SAVE_ANNOTATIONS),
and the last error (or "none").'''

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
    def run(pipeline, samplesheet_csv="", params_json="", contrasts_csv="", profile=""):
        """What the operator leaves out (or empty) is the approved plan's: no need to copy it to run it as approved."""
        calls.append(pipeline)
        approved = lambda *names: next((read(run_dir, n) for n in names if os.path.isfile(os.path.join(run_dir, n))), "")
        samplesheet_csv = samplesheet_csv if str(samplesheet_csv).strip() else approved("plan_samplesheet.csv")
        params_json = params_json if str(params_json).strip() else approved("plan_params.json")
        contrasts_csv = contrasts_csv if str(contrasts_csv).strip() else approved("plan_contrasts.csv", "plan_barcodes.csv")
        profile = profile if str(profile).strip() else approved("plan_profile.txt")
        if isinstance(params_json, dict):
            params_json = json.dumps(params_json)
        p = scratch(run_dir, **{"samplesheet.csv": samplesheet_csv, "params.json": params_json, "contrasts.csv": contrasts_csv})
        result = subprocess.run(["bash", os.path.join(BIN, "run_nfcore.sh"), run_dir, pipeline, p["samplesheet.csv"],
                                 p["params.json"], p["contrasts.csv"], profile.strip()],
                                capture_output=True, text=True, cwd=os.path.join(run_dir, ".harness"))
        return (result.stdout + result.stderr).strip()
    params = string_params(pipeline="pipeline name",
                           samplesheet_csv="only to change it: the whole samplesheet, CSV text (default: as approved)",
                           params_json="only to change them: all the parameters, a JSON object (default: as approved)",
                           contrasts_csv="only to change it: the whole second sheet (default: as approved)",
                           profile="only to change it: the analysis profile (default: as approved)")
    params["required"] = ["pipeline"]
    return Tool("RUN_NFCORE", "Launch the approved nf-core run (one gated, resumable attempt) and print a short "
                "status digest: STATUS: SUCCESS, FAILED (with the error) or REFUSED (a change that was not allowed). "
                "With only the pipeline, it runs the approved plan as approved.", params, run, check=True)


def pipeline_progress(run_dir):
    """The running attempt in a few words, for the person watching: tasks done, running or queued, the latest."""
    attempts = sorted(glob.glob(os.path.join(run_dir, "attempt_*")), key=lambda p: int(p.rsplit("_", 1)[1]))
    log = os.path.join(attempts[-1], "nextflow.log") if attempts else ""
    if not log or not os.path.isfile(log):
        return "checking the attempt"
    submitted, latest = 0, ""
    with open(log, errors="replace") as fh:
        for line in fh:
            if "Submitted process >" in line or "Cached process >" in line:
                submitted, latest = submitted + 1, line.split(">", 1)[1].strip()
    if not submitted:
        return "starting the pipeline (downloading it and its containers the first time)"
    start = os.path.getmtime(os.path.join(attempts[-1], "params.json")) if os.path.isfile(
        os.path.join(attempts[-1], "params.json")) else 0
    done = failed = 0
    for trace in glob.glob(os.path.join(run_dir, "results", "pipeline_info", "execution_trace_*.txt")):
        if os.path.getmtime(trace) >= start:  # this attempt's trace (Nextflow adds a line per finished task)
            with open(trace, errors="replace") as fh:
                for line in fh:
                    status = (line.rstrip("\n").split("\t") + [""] * 5)[4]
                    done += status in ("COMPLETED", "CACHED")
                    failed += status == "FAILED"
    name = latest.split(":")[-1]
    return (f"{done} tasks done, {max(submitted - done - failed, 0)} running or queued"
            + (f", {failed} failed" if failed else "") + f"; latest: {name}")


def completed(attempt):
    return bool(attempt) and "Pipeline completed successfully" in read(attempt, "nextflow.log")


def succeeded_analyses(run_dir):
    """The single-cell toolbox's analyses that succeeded (sc_analyse.sh leaves SUCCEEDED), in order. A revision
    the gate refused, or that failed, leaves a folder too, but does not undo an earlier analysis."""
    analyses = sorted(glob.glob(os.path.join(run_dir, "analysis_*")), key=lambda p: int(p.rsplit("_", 1)[1]))
    return [a for a in analyses if os.path.isfile(os.path.join(a, "SUCCEEDED"))]


def sc_analyse_tool(run_dir, calls):
    def run(design):
        calls.append("SC_ANALYSE")
        text = json.dumps(design) if isinstance(design, dict) else str(design)
        return sc_job(run_dir, "analyse", scratch(run_dir, **{f"design_{len(calls)}.txt": text})[f"design_{len(calls)}.txt"])
    return Tool("SC_ANALYSE", "Run one analysis of the single-cell design with Geth's toolbox (a scheduler job) and "
                "print its diagnostics: STATUS: SUCCESS with OUTDIR, FAILED, or REFUSED (a change that is not allowed).",
                string_params(design="the design: a JSON object, or key=value lines (a revision: the changed keys and "
                              "justification=...)"), run, check=True)


def save_annotations_tool(run_dir):
    def run(annotations):
        lines = annotations if isinstance(annotations, list) else str(annotations).splitlines()
        lines = [str(l).strip() for l in lines if str(l).strip()]
        write(run_dir, "annotations.txt", "\n".join(lines) + "\n")
        return f"Saved {len(lines)} annotation line(s)."
    return Tool("SAVE_ANNOTATIONS", "Save the cluster annotations, one line per cluster: "
                "\"cluster <id>: <cell type> (<key markers>)\".",
                string_params(annotations="the annotation lines, one per cluster"), run)


def save_outcome(run_dir, outcome):
    """outcome.txt, as Geth 1.x wrote it (lists as Groovy printed them: [a, b])."""
    listed = lambda v: "[" + ", ".join(v) + "]"
    write(run_dir, "outcome.txt", f"succeeded: {str(outcome['succeeded']).lower()}\nattempts: {outcome['attempts']}\n"
              f"outdir: {outcome['outdir']}\nchanges_to_plan: {listed(outcome['fixes_applied'])}\n"
              f"annotations: {listed(outcome['annotations'])}\nlast_error: {outcome['last_error']}\n")


def submit_outcome_tool(run_dir, outcome, calls, analyst=False):
    """The operator's (or analyst's) final answer. The claim must agree with the disk, either way: the pipeline log of
    the last launched attempt (the toolbox: the last analysis); the number of attempts is the number of calls Geth
    saw, not the model's count."""
    def run(succeeded, outdir, changes_to_plan, last_error, annotations=None):
        ok = str(succeeded).lower() in ("true", "yes", "1")
        if analyst:
            good = succeeded_analyses(run_dir)
            names = ", ".join(os.path.basename(g) for g in good)
            if ok and not good:
                return "REFUSED: no analysis succeeded: report succeeded=false with the last error."
            if ok and os.path.basename(os.path.normpath(str(outdir or ""))) not in [os.path.basename(g) for g in good]:
                return f"REFUSED: OUTDIR must be the folder of an analysis that printed STATUS: SUCCESS ({names})."
            if good and not ok:
                return (f"REFUSED: {names} succeeded (a refused or failed revision does not undo it): report "
                        "succeeded=true with the OUTDIR of the analysis your annotations describe.")
        else:
            done = completed(last_attempt(run_dir))
            if ok and not done:
                return ("REFUSED: the last launched attempt did not complete (its pipeline log has no 'Pipeline "
                        "completed successfully'): report succeeded=false with its error, or fix it.")
            if done and not ok:
                return "REFUSED: the last launched attempt succeeded: report succeeded=true."
        listed = lambda v: [str(c) for c in (v if isinstance(v, list) else [v] if v else [])
                            if str(c).strip() and str(c).strip().lower() != "none"]
        outcome.update(succeeded=ok, attempts=len(calls), outdir=str(outdir or "none"), fixes_applied=listed(changes_to_plan),
                       annotations=listed(annotations), last_error=str(last_error or "none"))
        save_outcome(run_dir, outcome)
        return "OUTCOME SAVED"
    array = {"type": "array", "items": {"type": "string"}}
    props = {"succeeded": {"type": "boolean"},
             "outdir": {"type": "string", "description": "the OUTDIR printed by the tool, or 'none'"},
             "changes_to_plan": dict(array, description="every change you made to the plan" + (
                 " with its justification, and how you handled each FLAG" if analyst else "") + ", or []"),
             "last_error": {"type": "string", "description": "the last error, or 'none'"}}
    if analyst:
        props["annotations"] = dict(array, description='one line per cluster: "cluster <id>: <cell type> (<key markers>)"')
    return Tool("SUBMIT_OUTCOME", "Report the outcome when you are done. Geth checks the claim against the "
                + ("toolbox's" if analyst else "pipeline's") + " record.",
                {"type": "object", "required": list(props), "properties": props}, run, final=True)


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
    """outcome.txt back as an outcome (a list as one entry, as Geth 1.x read it back)."""
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
    ap.add_argument("--progress", action="store_true", help="show what the agents do, one line per step, in the terminal")
    a = ap.parse_args(argv)
    runs = os.environ.get("GETH_RUNS_DIR", "")
    if not runs or not a.run_dir.startswith(runs.rstrip("/") + "/"):
        sys.exit(f"run_dir must be under {runs}/ (source env.sh first)")
    if not os.path.isfile(os.path.join(a.run_dir, "APPROVED")):
        sys.exit(f"The plan in {a.run_dir} has not been approved: run `geth approve` first")
    plan = load_plan(a.run_dir)
    single_cell = plan["pipeline"] == "sc_downstream"
    try:
        client = model_client()
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
        if single_cell:
            skills = {k: v for k, v in load_skills(os.path.join(GETH_HOME, "geth", "skills")).items() if k == "sc-downstream"}
            agent = Agent("analyst", ANALYST, [sc_analyse_tool(a.run_dir, calls), save_annotations_tool(a.run_dir),
                                               submit_outcome_tool(a.run_dir, outcome, calls, analyst=True)],
                          client, skills=skills, max_turns=8, trace_path=trace, log=log)
            prompt = ANALYST_PROMPT.format(params=plan["params"])
        else:
            agent = Agent("operator", OPERATOR, [run_nfcore_tool(a.run_dir, calls), pipeline_options(),
                                                 submit_outcome_tool(a.run_dir, outcome, calls)],
                          client, max_turns=10, trace_path=trace, log=log)
            prompt = OPERATOR_PROMPT.format(**{k: plan[k] or "''" for k in ("pipeline", "sheet", "params", "sheet2", "profile")})
        if a.progress:
            agent.progress = TerminalProgress(who=agent.name, watch=lambda name: pipeline_progress(a.run_dir)
                                              if name == "RUN_NFCORE" else "")
        try:  # a gate refusal is a check's refusal: the same one again and again ends the loop
            agent.run(prompt, done=lambda name, out: out.startswith("OUTCOME SAVED") or "STATUS: SUCCESS" in out)
        except ModelError as e:
            log(f"Geth: {e}")
        if not outcome:  # the agent gave no outcome: say what the disk says
            good = succeeded_analyses(a.run_dir)
            ok = bool(good) if single_cell else completed(last_attempt(a.run_dir))
            outdir = (good[-1] if single_cell else os.path.join(a.run_dir, "results")) if ok else "none"
            outcome.update(succeeded=ok, attempts=len(calls), outdir=outdir, fixes_applied=[], annotations=[],
                           last_error="none" if ok else f"the {agent.name} ended without reporting an outcome")
            save_outcome(a.run_dir, outcome)

    reporter = Agent("reporter", REPORTER, [collect_tool(a.run_dir),
                                            submit_report_tool(a.run_dir, plan["pipeline"], lambda: outcome.get("attempts", 0))],
                     client, max_turns=6, trace_path=trace, log=log, text_answer=("SUBMIT_REPORT", "report", 400))
    sheet2_part = f"second sheet:\n{plan['sheet2']}\n" if plan["sheet2"] else ""
    if a.progress:
        if not a.report_only and agent.progress:
            agent.progress.close()
        reporter.progress = TerminalProgress(who="reporter")
    try:
        result = reporter.run(REPORTER_PROMPT.format(question=plan["question"], pipeline=plan["pipeline"], sheet=plan["sheet"],
                                                     params=plan["params"], sheet2_part=sheet2_part, rationale=plan["rationale"],
                                                     outcome=json.dumps(outcome)),
                              done=lambda name, out: out.startswith("REPORT SAVED"))
    except ModelError as e:
        log(f"Geth: {e}")
        result = None
    if reporter.progress:
        reporter.progress.close()
    if result is None:  # no report from the reporter: say so in the report, not nothing
        write(a.run_dir, "report.md", f"# Report\n\nThe reporting agent did not write a report (see geth_{'report' if a.report_only else 'run'}.log). "
              f"The run's outcome:\n\n```\n{read(a.run_dir, 'outcome.txt')}```\n")
        write(a.run_dir, "report_check.txt", "REPORT CHECK: no report was written\n")
    print(read(a.run_dir, "report_check.txt").strip() or "No report was saved.", flush=True)
    print(f"Model usage: {json.dumps({k: round(v, 4 if k == 'usd' else 1) for k, v in client.usage.items()})}", flush=True)
    return 0 if (a.report_only or outcome.get("succeeded")) and result else 1


if __name__ == "__main__":
    sys.exit(main())
