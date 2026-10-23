"""geth plan: the planner agent turns a request and a data folder (or a finished run) into a plan.

    python3 -m harness.plan --run_dir <dir> --question <text> --data_dir <dir> [--upstream_run <dir>]
                            [--ask terminal|file|none] [--answers <file>]

The plan is handed over through SUBMIT_PLAN (a tool call with a schema), so a plan that fails the check comes back
to the agent. The planner can ask the scientist (ASK_USER: in the terminal, from an answers file, or nobody) and
browse the pipeline's options (PIPELINE_OPTIONS); --ask off plans without questions.
"""
import argparse
import json
import os
import sys

from .agent import Agent, load_skills
from .ask import FileAnswerer, Nobody, TerminalAsker, TerminalProgress, ask_tool
from .llm import Client, ModelError
from .tools import (GETH_HOME, check_plan, checks, inspect_reads, list_files, list_references, pipeline_options,
                    read_text, sc_inspect, submit_plan)

INSTRUCTION = '''You are Geth, a bioinformatics analysis planner. You turn a scientist's request and a
sequencing data folder into a run plan for exactly one nf-core pipeline. For new sequencing data:
"rnaseq" (bulk RNA-seq), "scrnaseq" (droplet single-cell RNA-seq), "sarek" (DNA-seq variant calling:
germline or tumour/normal, WGS/WES/panels), "isoseq" (PacBio Iso-Seq full-length transcripts),
"taxprofiler" (taxonomic profiling of shotgun metagenomes), "mag" (metagenome assembly and binning),
"ampliseq" (amplicon/metabarcoding: 16S, 18S, ITS, COI), "chipseq" (ChIP-seq peaks), "atacseq"
(ATAC-seq accessibility), "nanoseq" (Oxford Nanopore DNA/cDNA/direct RNA), "eager" (ancient DNA) or
"methylseq" (DNA methylation: WGBS, RRBS, EM-seq, TAPS).
For a follow-up analysis: "differentialabundance" for differential expression on the results of a
finished nf-core/rnaseq run (an upstream run). If none of these fits the data or the request, say so
in the rationale instead of forcing a pipeline.
Always inspect the folders first: list them, then read every README/metadata text file in them;
for a follow-up analysis also read the upstream run's question.txt, plan_samplesheet.csv,
plan_params.json and plan_rationale.txt, and list its results folder.
Load the skill of the pipeline you choose and follow its rules exactly.
Use absolute paths. Only use files that appear in the listing; never invent files.
If the folder holds no reference genome and annotation, call LIST_REFERENCES and use the entry for the
right species; if none matches, say so in the rationale instead of guessing.
Multiplexed 10x single-cell data (on-chip multiplexing OCM, CellPlex/CMO, Flex/probe barcodes: several
samples share one library) needs nf-core/scrnaseq with aligner cellrangermulti and a second sheet that
maps each library's barcodes to its samples: read the nfcore-scrnaseq skill's multiplexed section.
Before submitting, call CHECK_PLAN with your pipeline, samplesheet and parameters (as key=value lines),
plus the second sheet in contrasts_csv (differentialabundance: the contrasts; multiplexed scrnaseq: the
barcodes sheet) and the analysis profile for differentialabundance (empty strings otherwise),
fix every problem it reports, and repeat until it prints "PLAN CHECK: OK". Read every WARNING it
prints too: fix the plan, or explain in the rationale why the warning does not apply.'''

# A follow-up of a finished nf-core/scrnaseq run: the single-cell toolbox.
SINGLE_CELL = '''
For a follow-up of a finished nf-core/scrnaseq run, design a downstream analysis for Geth's single-cell
toolbox instead (pipeline "sc_downstream"): load the sc-downstream skill, find the sample's filtered
count matrix in the upstream results, call SC_INSPECT on it, and choose every design value from the
observed data; the samplesheet is "sample,h5ad" and the parameters are the design key=value lines.'''

QUESTIONS = '''

You can ask the scientist with ASK_USER, and browse the pipeline's options with PIPELINE_OPTIONS.
1. First inspect the folder and read its text files. Never ask what they already say.
2. Choose the pipeline and load its skill. Its section "Ask when the delivery does not say" lists what the
   plan needs: ask, in one round when you can, every item of it that the files do not tell you. When the
   folder has no sample table, ask for one (for every file: its sample, group or condition, replicate, and
   which files are the same library). Ask for exact values: sequences, names, numbers.
3. Look through PIPELINE_OPTIONS for the options that change this project's results (not run-time or reporting
   details), and ask about those whose right value depends on the scientist's aims. Keep the pipeline's
   defaults for everything else.
Give every question 2 to 4 options, your recommended answer, and why it matters. Your recommended answer must
agree with the files: never recommend a value they rule out. Do not ask a question whose answer cannot change
the plan, and do not ask to confirm what the files already say. When an answer is "use your recommendation", or
nobody answers, use your recommendation. In the rationale, justify every parameter you set and say where its
value comes from: the files, the scientist's answer, or your recommendation. When a check or a skill makes you
set something other than what the scientist answered, or an answer contradicts the files, say so plainly in the
rationale, with the reason. Never write facts about the data that neither the files nor the answers give.
CHECK_PLAN also compares the plan with the reads (primers, barcode read length, read length, RRBS): when such a
WARNING contradicts an answer, ask the scientist about it (ASK_USER) instead of choosing silently.'''

PROMPT = '''Request: {question}
Data folder: {data_dir}
Upstream run: {upstream}

When the plan has passed CHECK_PLAN, call SUBMIT_PLAN with exactly that plan: the pipeline name (e.g. "rnaseq",
"sarek", "differentialabundance"); the samplesheet (for differentialabundance: the observations sheet) as a
list of CSV lines, header line first; the pipeline parameters as a list of key=value entries, one per
parameter (do not include "input", "outdir", "contrasts" or "cellranger_multi_barcodes"); in
contrasts_lines the second sheet as a list of CSV lines, header line first (differentialabundance: the
contrasts; multiplexed 10x scrnaseq: the barcodes sheet; otherwise an empty list); the analysis profile
for differentialabundance (otherwise an empty string); and a short rationale that explains how files or
samples were grouped, which were left out and why, the contrasts and their direction (or which samples
each multiplexed library holds), and why each parameter is set.'''


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--run_dir", required=True)
    ap.add_argument("--question", required=True)
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--upstream_run", default="")
    ap.add_argument("--max_turns", type=int, default=25)
    ap.add_argument("--ask", choices=("terminal", "file", "none", "off"), default="off",
                    help="who answers the planner's questions; off: no questions at all (the R2 planner)")
    ap.add_argument("--answers", default="", help="answers file (--ask file): what the scientist knows, in plain words")
    a = ap.parse_args(argv)
    runs, data_root, references = (os.environ.get(v, "") for v in ("GETH_RUNS_DIR", "GETH_DATA_ROOT", "GETH_REFERENCES"))
    if not (runs and data_root and references):
        sys.exit("Geth's site settings are missing: source env.sh (it loads site/site.env) first")
    if not a.run_dir.startswith(runs.rstrip("/") + "/"):
        sys.exit(f"run_dir must be under {runs}/")
    if a.upstream_run and not os.path.isfile(os.path.join(a.upstream_run, "APPROVED")):
        sys.exit(f"Upstream run {a.upstream_run} has no approved plan")
    os.makedirs(a.run_dir, exist_ok=True)
    open(os.path.join(a.run_dir, "question.txt"), "w").write(a.question + "\n")
    open(os.path.join(a.run_dir, "data_dir.txt"), "w").write(a.data_dir + "\n")
    upstream = (f"{a.upstream_run} (nf-core/{open(os.path.join(a.upstream_run, 'plan_pipeline.txt')).read().strip()} "
                f"results in {a.upstream_run}/results)" if a.upstream_run else "none (this is a new analysis of sequencing data)")
    try:
        site = Client()  # the site's model: the stand-in scientist always uses it
        client = Client("GETH_PLANNER") if os.environ.get("GETH_PLANNER_MODEL") else site
    except ModelError as e:
        sys.exit(f"Geth: {e}")
    if client is not site:
        print(f"Planner model: {client.model} (budget ${client.budget:.4g} per plan); stand-in: {site.model}", flush=True)
    open(os.path.join(a.run_dir, "plan_model.txt"), "w").write(
        f"{client.model}" + (f" (paid, at most ${client.budget:.4g})" if client is not site else "") + "\n")
    tools = [list_files(data_root), read_text(data_root), list_references(references),
             check_plan(a.run_dir, a.upstream_run), submit_plan(a.run_dir, a.upstream_run)]
    instruction, hint, progress = INSTRUCTION, "", None
    single_cell = bool(a.upstream_run) and open(os.path.join(a.upstream_run, "plan_pipeline.txt")).read().strip() == "scrnaseq"
    if single_cell:  # the single-cell toolbox: its inspection runs as a scheduler job
        tools.append(sc_inspect(a.run_dir, data_root))
        instruction += SINGLE_CELL
    if a.ask != "off":
        transcript = os.path.join(a.run_dir, "plan_questions.md")
        open(transcript, "w").close()
        asker = {"terminal": TerminalAsker, "none": Nobody}.get(a.ask)
        asker = FileAnswerer(a.answers, site) if a.ask == "file" else asker()
        if a.ask == "terminal":
            progress = TerminalProgress()
        tools += [pipeline_options(), ask_tool(asker, transcript), inspect_reads(data_root)]
        instruction += QUESTIONS
        hint = "If you cannot fix it from the data, ask the scientist with ASK_USER (for example which file to use)."
    skills = load_skills(os.path.join(GETH_HOME, "geth", "skills"))
    if not single_cell:
        skills.pop("sc-downstream", None)
    agent = Agent("planner", instruction, tools, client, skills=skills, max_turns=a.max_turns,
                  trace_path=os.path.join(a.run_dir, "harness_trace_plan.jsonl"), log=lambda m: print(m, flush=True),
                  stuck_hint=hint, progress=progress)
    try:
        result = agent.run(PROMPT.format(question=a.question, data_dir=a.data_dir, upstream=upstream),
                           done=lambda name, out: out.startswith("PLAN CHECK: OK"))
    except ModelError as e:
        print(f"Geth: {e}", flush=True)
        result = None
    if progress:
        progress.close()
    if client.usage.get("usd"):
        with open(os.path.join(a.run_dir, "plan_model.txt"), "a") as fh:
            fh.write(f"cost of this plan: ${client.usage['usd']:.3f} ({client.usage['requests']} requests)\n")
    print(f"Model usage: {json.dumps(dict({k: round(v, 4 if k == 'usd' else 1) for k, v in client.usage.items()}, model=client.model))}", flush=True)
    if client is not site:
        print(f"Stand-in usage: {json.dumps({k: round(v, 1) for k, v in site.usage.items()})}", flush=True)
    if result is None:
        # No accepted submission: fall back on the last plan that passed CHECK_PLAN, if any (as SAVE_PLAN does).
        checked = os.path.join(a.run_dir, ".checked")
        pipeline_file = os.path.join(checked, "plan_pipeline.txt")
        if not os.path.isfile(pipeline_file):
            print("Planning failed: no plan passed CHECK_PLAN.", flush=True)
            return 1
        rationale = os.path.join(a.run_dir, ".harness", "fallback_rationale.txt")
        open(rationale, "w").write("The planner did not submit a final plan; the last version that passed "
                                   "CHECK_PLAN during planning is used.\n")
        pipeline = open(pipeline_file).read().strip()
        second = next((os.path.join(checked, f) for f in ("plan_contrasts.csv", "plan_barcodes.csv")
                       if os.path.isfile(os.path.join(checked, f))), "/dev/null")
        profile = os.path.join(checked, "plan_profile.txt")
        result = checks("save-plan", a.run_dir, pipeline, os.path.join(checked, "plan_samplesheet.csv"),
                        os.path.join(checked, "plan_params.json"), rationale, "--contrasts", second,
                        "--profile", open(profile).read().strip() if os.path.isfile(profile) else "",
                        *(["--upstream", a.upstream_run] if a.upstream_run else []))
    print(result, flush=True)
    return 0 if os.path.isfile(os.path.join(a.run_dir, "plan_pipeline.txt")) else 1


if __name__ == "__main__":
    sys.exit(main())
