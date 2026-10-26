# Developer guide

How Geth works inside, how to change it, and how to add a pipeline. It assumes you know Nextflow and
nf-core, and have read the [introduction](introduction.md).

## Design in one paragraph

Geth is a few **agents on a small harness** (`geth/harness`, Python standard library only), surrounded by
**deterministic gates**. Each agent gets an instruction, a few **tools**, optionally **skills** that it loads
when it needs them, and ends by calling a **final tool** that Geth checks (`SUBMIT_PLAN`, `SUBMIT_OUTCOME`,
`SUBMIT_REPORT` ...). An answer only counts once its final tool accepts it; a refusal goes back to the agent.
The agents talk to the model service directly. **Nextflow runs the nf-core pipelines and the tools' scheduler
jobs** (`geth/jobs.nf`), nothing else. The gates, in plain Python (`geth_checks.py`), validate every plan
against the pinned pipeline's own schemas, freeze the approved design, decide which changes a retry may
make, and check a finished report number by number against the results. The agents decide; the gates
verify; a person approves.

Geth 1.x ran its agents on Nextflow's preview `agent` feature. Geth 2.0 (codename Rannoch) moved them to
their own harness, one measured step at a time (`docs/history/rannoch.html`).

## Where to start reading

Follow one analysis through the code, in the order things happen:

1. `geth/geth`: the commands. `geth plan`, `geth run` and `geth report` each end in `agents()`, which starts
   a stage (`python3 -m harness.plan`, `harness.run`, `harness.report`). Each stage goes through `sandboxed`
   (`geth/bin/driver_slots.sh`), inside the agent sandbox when the site asks for it.
2. `geth/harness/agent.py`: the loop. Then `harness/plan.py`: the planner's instruction, its tools
   (`tools.py`, `ask.py`) and its final tool `SUBMIT_PLAN`. `llm.py` is the model client.
3. `geth/bin/geth_checks.py`: what the tools call. `REGISTRY` describes every pipeline; `check_plan` is the
   plan check; `approve` fingerprints the plan; `gate` is the plan-diff gate the operator meets on every
   launch.
4. `geth/harness/run.py` and `geth/bin/run_nfcore.sh`: the operator, analyst and reporter, and the operator's
   only way to start a pipeline, with the gate before and the error digest after.
5. `geth/bin/collect_results.py` and `check_report.py`: what the reporter sees, and how its report is
   checked.
6. A skill, e.g. `geth/skills/nfcore-rnaseq/SKILL.md`: what the planner is told about a pipeline.

Then the tests (`geth/tests/test_geth_checks.py`) show each gate rule on a real failure that motivated it.

## Repository layout

```
env.sh                     source first: loads site/site.env, derives defaults, exports everything
env.fish                   the same for fish: imports what env.sh exports (geth/bin/env_export.sh), loads completions
VERSION                    release number (bumped on release branches)
site/
  site.env.example         documented template of the site configuration (copy to site/site.env)
  examples/                worked site configurations: local machine, an SGE cluster with GPUs
geth/
  geth                     the command line: plan, show, approve, run, status, report, list, stop, doctor, version,
                           legion, lab
  harness/                 the agents (Python, standard library only):
    agent.py               the loop: tools, skills, final tools, refusal guard, trace
    prose.py               agents' text for people: one sentence per line, wrapped (display only)
    llm.py                 the model client: chat completions or the Responses API, retries, usage, budgets
    plan.py, tools.py, ask.py   the planner, its tools, and its questions (ASK_USER, the stand-in)
    run.py, report.py      the operator, the single-cell analyst and the reporter (geth run, geth report)
    lab.py                 the lab's designer, judge, engineers and reviewers
    project.py             the project coordinator: plan the steps, review after each, write the project report
  jobs.nf                  the tools' scheduler jobs: the single-cell toolbox (SC_INSPECT, SC_ANALYSE)
  nextflow.config          settings of those jobs, read from the environment (folders)
  bin/                     the gates and launchers (on the jobs' PATH: Nextflow adds jobs.nf's bin/)
    geth_checks.py         the gates: registry, plan check, save-plan, approve, plan-diff gate, record
    run_nfcore.sh          RUN_NFCORE tool: one gated, resumable nf-core launch per call
    sc_downstream.py       the single-cell toolbox (inspect / run), executed in the CellTypist container
    sc_analyse.sh          SC_ANALYSE tool: one gated toolbox analysis per call
    sc_job.sh              starts one toolbox job (inspect or analyse) through jobs.nf
    geth_project.py        projects: the step check, approval, state, Ensembl lookup, and the runner
    collect_results.py     ready-to-copy result tables for the reporter
    check_report.py        traces every number and link of the report to the facts
    geth_doctor.sh         installation checks (geth doctor)
    driver_slots.sh        driver slots (GETH_MAX_DRIVERS), stage time limits, the sandboxed() launcher
    stop_driver.sh         geth stop / geth lab stop: ends a run's drivers, processes and scheduler jobs
    agent_sandbox.sh       runs an agent stage in a container (GETH_AGENT_SANDBOX, phase 12)
    env_export.sh          env.fish helper: what env.sh changes in the environment, as NUL-separated records
  completions/geth.fish    fish tab completion (loaded by env.fish)
  conf/                    configs added to nf-core runs: resource caps (test, production), legacy singularity engine
  schemas/                 <pipeline>-<release>.params.json / .input.json, verbatim from each release;
                           nfcore_catalogue.tsv: every nf-core pipeline (name, release, description), for gaps
  skills/                  planner skills: one SKILL.md per pipeline, plus sc-downstream
  references/              scripts that add entries to the reference catalogue
  tests/                   unit tests of the gates, the agents (with a scripted model), projects and the lab
                           (self-contained)
  lab/                     the EXPERIMENTAL lab (phase 11): not used by geth plan / geth run
    lab.sh                 geth lab: design, judge, show, list, build (arm B), build-c (arm C), stop
    jobs.nf                the lab tools' scheduler jobs: LAB_INSPECT, MAKE_SUBSET, TEST_STEP, LINT_PIPELINE,
                           TEST_PIPELINE, and arm C's full run
    bin/                   lab_job.sh (starts one of those jobs), lab_checks.py (design format), lab_inspect.py, lab_build.py (arm B/C bookkeeping),
                           lab_step_check.py (static check), lab_sandbox.sh and lab_nf_sandbox.sh (the
                           sandboxes for agent-written code), lab_h5ad.py, lab_subset_step.py
    skills/                sc-design-lab (design), sc-build-lab (Python steps), nf-build-lab (Nextflow)
bench/                     benchmarks: data staging, bench loops, baselines without agents, scorers;
                           bench/lab/ for the lab (designs, builds, judges, sandbox escape tests)
docs/                      this documentation; docs/history/ holds the development record
spikes/                    the first feasibility experiments (frozen)
```

## The run folder

Everything about one analysis lives in `$GETH_RUNS_DIR/<name>`. Geth never writes elsewhere, apart from
Nextflow's cache (and, for a project's reference step, the reference catalogue). The files below are the interface between the CLI, the agents, the gates and the
person.

| File | Written by | Content |
|---|---|---|
| `question.txt`, `data_dir.txt` | planner stage | the request and the data folder |
| `plan_pipeline.txt`, `plan_samplesheet.csv`, `plan_params.json`, `plan_rationale.txt` | `SUBMIT_PLAN` (`save-plan`) | the plan |
| `plan_contrasts.csv`, `plan_profile.txt`, `plan_upstream.txt` | `SUBMIT_PLAN` | downstream pipelines only |
| `plan_barcodes.csv` | `SUBMIT_PLAN` | multiplexed scrnaseq only: the Cell Ranger multi barcodes sheet |
| `plan_check.txt` | `SUBMIT_PLAN` | the plan check result |
| `plan_questions.md`, `plan_model.txt` | planner stage | the planner's questions and the answers; the model that planned (and its cost, if paid) |
| `.checked/` | `CHECK_PLAN` | the last plan version that passed the check during planning (fallback) |
| `APPROVED` | `geth approve` | approver, time, SHA-256 of every plan file |
| `gate_state.json` | `record` | the last accepted attempt and the error that may justify the next change |
| `attempt_N/` | `run_nfcore.sh` | `samplesheet.csv`, `params.submitted.json`, `params.json` (normalised), `gate.txt`, `check.txt`, `nextflow.log`, `error.txt` (and `contrasts.csv` or `barcodes.csv`, `samplesheet.tsv`, `prelude.config`; `STOPPED` when `geth stop` ended it: such an attempt does not count towards the limit of 5) |
| `analysis_N/` | `sc_analyse.sh` | toolbox analyses: `design.submitted.txt`, `design.json`, `diagnostics.json`, `summary.txt`, figures, `processed.h5ad` |
| `nfcore/` | `run_nfcore.sh` | launch folder of the nested nf-core run (its `.nextflow/` and log) |
| `results/`, `work/` | nf-core | the pipeline's outputs and work folder |
| `outcome.txt` | `SUBMIT_OUTCOME` | the operator's or analyst's outcome, checked against the pipeline's log or the analysis |
| `annotations.txt` | `SAVE_ANNOTATIONS` | single-cell cluster annotations |
| `report.md`, `report_check.txt` | `SUBMIT_REPORT` | the checked report |
| `geth_<stage>.log`, `harness_trace_<stage>.jsonl`, `.harness/` | the agents | log; every model answer and tool call (never the key); scratch files |
| `geth_work/`, `.harness/jobs/` | Nextflow | the tools' scheduler jobs: work folder, one launch folder per job |
| `.geth_<stage>.pid` | `geth` | present while a stage works on the run (`geth list`, `geth stop`): host, pid, driver slots |
| `geth_version.txt` | `record_version` (`driver_slots.sh`) | one line per agent stage: stage, date, Geth release and commit ("with local changes" if the clone differed); also in project and lab folders |

Because the folder holds the whole state, `geth run` resumes after an interruption: Nextflow `-resume`
in `nfcore/`, attempt numbering continues, and the gate state persists.

**Writing the report again.** `geth report` runs the reporter alone (`harness.report`): the plan from the
`plan_*` files, the outcome from `outcome.txt`, then the reporter and its checked `SUBMIT_REPORT`. No pipeline is launched and no
attempt is used; the previous `report.md` and `report_check.txt` are kept as `report.<date>.*`.

**Resume and input paths.** Nextflow's cache knows an input file by its path, size and date. Each attempt
copies the samplesheet and second sheet into `attempt_N/`, so `run_nfcore.sh` launches with the identical
copy of the latest completed attempt (`stable()`): a process that reads a sheet (scrnaseq's Cell Ranger multi
barcodes) is not redone. One unexplained miss remains: on `sc_rat_ocm`, a launch right after a stopped
attempt redid Cell Ranger multi once, although its cache key was unchanged; later launches reused it.

**Stopping.** `geth stop` (`stop_driver.sh`) reads the live `.geth_*.pid` files and walks the process tree
below each pid (sandbox included: apptainer's PID namespace is visible from the host). It stops the Geth
command first, so no further stage starts, then sends SIGTERM to every Nextflow driver in the tree at once:
each cancels its own scheduler jobs. After `GETH_STOP_GRACE` seconds the rest of the tree gets SIGTERM, then
SIGKILL. Last, it deletes any job of the user whose working folder (`qstat -j`: `cwd`) is inside the run
folder. It appends `stopped by geth stop` to the stage's log, which `geth list` shows.

## Lifecycle of an analysis

### Plan (`geth plan` → `harness.plan`)

1. The CLI creates the run folder and starts the planner stage. The stage checks the site settings, the
   model allowlist (`llm.py`), and that `run_dir` lies under `GETH_RUNS_DIR`.
2. The **planner** agent receives the question, the data folder and, for `--from`, the upstream run. It
   has these tools:

   | Tool | What it does |
   |---|---|
   | `LIST_FILES` | `find`, depth 3, under `GETH_DATA_ROOT` only |
   | `READ_TEXT` | first 8 kB of a text file, or 8 decompressed lines of a `.gz`, under `GETH_DATA_ROOT` only |
   | `LIST_REFERENCES` | prints every catalogue `README.txt` |
   | `INSPECT_READS` | read lengths (and the first bases) of a FASTQ, measured rather than guessed |
   | `PIPELINE_OPTIONS` | the pinned release's parameter schema: its sections, a section's options, or a search |
   | `ASK_USER` | questions to the scientist: in the terminal, or a stand-in answering from `--answers` (at most 2 rounds of 5) |
   | `CHECK_PLAN` | `geth_checks.py check-plan`; also saves passing versions to `.checked/` |
   | `SC_INSPECT` | follow-up of a scrnaseq run only: per-cell QC distributions of an `.h5ad` (a job, through `jobs.nf`) |

   It also gets **skills**: one per pipeline. It must call `CHECK_PLAN` until it prints
   `PLAN CHECK: OK`, and fix or explain every `WARNING:` line (`plan_warnings()`: samples of the
   delivery's tables that appear nowhere in the plan; a 10x chemistry the delivery never states, or GEM-X
   planned as v3; read checks such as primers or barcode read length). Warnings never block a plan.
3. The planner submits with `SUBMIT_PLAN`. The samplesheet, parameters and the second sheet
   (`contrasts_lines`: contrasts, or the multiplexed samples) are **lists of lines**. `SUBMIT_PLAN` runs
   `geth_checks.py save-plan`, which re-checks the plan and writes the `plan_*` files; a refusal goes back
   to the planner. If the planner ends without an accepted submission, the last version in `.checked/` is
   used, and the rationale says so.

### Approve (`geth approve`)

`geth approve` refuses a plan that fails the check. Otherwise `geth_checks.py approve` writes
`APPROVED`, with the SHA-256 of every plan file, and resets `gate_state.json`. Every later read of the approved plan (`approved_plan()`) re-hashes
the files. A file edited after approval makes every gate call fail until a person approves again.

### Run (`geth run` → `harness.run`)

1. The stage reads the approved `plan_*` files and gives them to the **operator**, or to the **analyst**
   when the pipeline is `sc_downstream`.
2. The operator's tool is `RUN_NFCORE`, which runs `run_nfcore.sh`. Called with only the pipeline, it runs
   the approved plan as approved; after a failure, the operator passes in full only what it changes (the
   whole samplesheet, or all the parameters). Each call is one attempt, in a new `attempt_N/`:
   1. Refuse run folders outside `GETH_RUNS_DIR`, and pipelines not in the registry.
   2. **Plan-diff gate** (`geth_checks.py gate`), described below. A refusal is reported as
      `STATUS: REFUSED`, and nothing is launched.
   3. **Plan check** (`check-plan`) of the submitted attempt. A failure is recorded as a `check` error,
      so the next attempt may fix exactly that.
   4. Resources: `test.config` for inputs under 2 GB on a reference under 500 MB, `production.config`
      otherwise (a human genome needs large jobs whatever the read count).
   5. Per-pipeline runtime (`geth_checks.py runtime`): Nextflow version, Java, extra config,
      environment, TSV input, `--max_*` limits.
   6. Launch from `nfcore/`, with `-resume`.
   7. Print a digest: status, outdir, warnings, or an error report extracted from the Nextflow log plus
      the failed task's stderr. Then `record` the attempt: `ok`, `check` or `nextflow`.

   The tool **always exits 0**: a failure is text the operator can act on. The operator may call
   `RUN_NFCORE` at most 3 times; the launcher refuses a 6th attempt in any case.
3. `SUBMIT_OUTCOME` writes `outcome.txt`. It refuses a claim that the last launched attempt's log
   contradicts (success without "Pipeline completed successfully", or failure with it). The number of
   attempts is the number of `RUN_NFCORE` calls Geth saw, not the model's count.
4. The **reporter** calls `COLLECT_RESULTS` (`collect_results.py`): ready-to-copy, rounded, labelled
   tables, so that the model never does arithmetic. It then writes the report.
5. `SUBMIT_REPORT` runs `check_report.py`. Every number in the report must match a fact, at the
   precision written and allowing for scales of 1, 100, 0.01, 10⁻³ and 10⁻⁶. Integers ≤ 20 are not
   checked: they are counts of samples, files or attempts. Facts are the collected results, the raw QC
   values, the plan, the question and the number of attempts. Links must appear in the facts.
   Untraced numbers or links go back to the reporter **once**, to correct; after that the report is saved
   with a warning section. A report the reporter writes as plain text counts as its submission.

### The plan-diff gate

`gate()` compares an attempt with the approved plan, and with the last accepted attempt held in
`gate_state.json`:

- **Pipeline:** must stay as approved.
- **Design:** frozen. The registry's `design` columns are compared as a sorted multiset: sample names,
  file assignments, and for chipseq the replicate and control links. For downstream pipelines,
  `design = None` freezes every column of the observations sheet, plus the contrasts and the analysis
  profile. The registry's `design_params` (scrnaseq: `protocol`, `aligner`) and the second sheet (the
  multiplexed samples of a Cell Ranger multi plan) are frozen too. Each violation is described per file
  (`design change: sample of X.fastq.gz changed ...`).
- **Other samplesheet columns** (e.g. `strandedness`) may change only if the previous error mentions
  the column by name.
- **Parameters:**
  - After a *plan-check* error, a parameter the check rejected as unknown may be removed. It may also be
    renamed to one of the names the check suggested, keeping its value. Any other change needs the
    error to mention the parameter, and nothing else may be added.
  - After a *pipeline* error, a parameter may be added, removed or changed only if the error mentions
    it by name.
  - Before any error, the approved plan must be launched unchanged.

These rules come from real failures. In early tests a smaller model, acting as operator, split
technical replicates into separate samples, and answered a parameter error by inventing two other
parameters. Both cases are now unit tests.

### The single-cell path

For `sc_downstream`, the **analyst** uses `SC_ANALYSE`, which runs `sc_analyse.sh` as a job in the
CellTypist container (`sc_job.sh` through `jobs.nf`):

1. The first analysis must run the approved design unchanged.
2. Exactly one revision may follow. It may change only tunable keys (`SC_TUNABLE`: QC thresholds,
   doublet rate or threshold, HVGs, neighbours, Leiden resolutions) and needs a `justification=` line
   that cites a diagnostic (`SC_DIAGNOSTIC_TERMS`). A revision may name only the keys it changes:
   `geth_checks.py sc-merge` applies it to the approved design.
3. The input matrix, normalisation, marker panel and annotation model stay frozen.

**CellBender after Cell Ranger multi.** nf-core runs CellBender on each library's raw matrix and on each
sample's. Only the library runs are valid: a sample's raw matrix lacks the library's empty droplets, so
CellBender keeps empty droplets as cells. `collect_results.py` tabulates every run from its `*_metrics.csv`
and splits each library run's `*_cell_barcodes.csv` by Cell Ranger's `sample_filtered_barcodes.csv`. The
plan check refuses a sample's own `*_cellbender_filter_matrix.h5ad` as toolbox input.

The toolbox prints **FLAGS**:

- fewer than 85% of cells kept
- a doublet rate outside a third to three times the expected rate
- a cluster with less than 60% CellTypist agreement (when the design has a model)
- a cluster with fewer than 10 cells

The analyst must address each flag or explain why it needs no change. It then annotates every cluster,
saves the annotations with `SAVE_ANNOTATIONS`, and gives them with its `SUBMIT_OUTCOME`. A success claim must
name an analysis that succeeded (`analysis_N/SUCCEEDED`): a refused or failed revision does not undo an
earlier analysis.

## The agents

| Agent | Tools | Skills | Turns | Final tool |
|---|---|---|---|---|
| `planner` | `LIST_FILES`, `READ_TEXT`, `LIST_REFERENCES`, `INSPECT_READS`, `PIPELINE_OPTIONS`, `ASK_USER`, `CHECK_PLAN` (+ `SC_INSPECT` on a scrnaseq follow-up) | every pipeline skill (+ `sc-downstream` on a scrnaseq follow-up) | 25 | `SUBMIT_PLAN` |
| `operator` | `RUN_NFCORE`, `PIPELINE_OPTIONS` | none | 10 | `SUBMIT_OUTCOME` |
| `analyst` | `SC_ANALYSE`, `SAVE_ANNOTATIONS` | `sc-downstream` | 8 | `SUBMIT_OUTCOME` |
| `reporter` | `COLLECT_RESULTS` | none | 6 | `SUBMIT_REPORT` |
| `coordinator` (projects) | plan: the planner's read-only tools, `ASK_USER`, `LIST_CAPABILITIES`, `SEARCH_NFCORE`, `FIND_GENOME`, `CHECK_STEPS`; review: `READ_STEP`; summary: `READ_STEP` | none | 30, 12, 12 | `SUBMIT_STEPS`, `DECIDE`, `SUBMIT_REPORT` |

The lab's agents (designer, judge, engineers, reviewer) are described [below](#the-lab-experimental-phase-11).

The loop (`agent.py`) keeps the agents honest about what it cannot check itself:
- a tool never kills the agent: any failure comes back as text;
- the agent ends only when its final tool accepts the answer; when its turns run out, one last turn is
  offered to call the final tool;
- when a check refuses the same thing three times, the agent is told to stop resubmitting and to ask or
  explain; at six, the loop ends;
- every request, answer and tool call goes to `harness_trace_<stage>.jsonl` (never the API key).

The model client (`llm.py`) speaks OpenAI-compatible chat completions, or the Responses API that GPT-6
models need for tools with reasoning. It retries, and counts tokens, cost and time. A model a person chooses
for one command (`--model <name>` on `geth plan`, `run`, `report`, `legion new`, `legion run` and `lab`;
`model_client()` reads `GETH_MODEL_*`, set by `use_model` in `driver_slots.sh`) needs its prices and a budget.
Before each request, `_room()` estimates its input cost and caps the output tokens so that the request cannot
cross the budget; a request with too little room left is not sent. A command that starts several stages has a
total (`--budget`, `model_total`): `paid_stage_start` gives each stage what is left, and refuses the stage that
would find nothing; `paid_stage_end` adds what it spent to the spend file (the client writes its running usage to
`GETH_MODEL_USAGE_FILE`, so a stopped stage is counted too). Commands started by `geth legion run` inherit the
total; the runner pauses the project when it is spent (`BudgetSpent`, exit 4) and leaves what it stopped to do. Instructions state
what success looks like ("never claim success unless the tool printed STATUS: SUCCESS").

**Skills** are Markdown files with a YAML header (`name`, `description`). The planner loads the one it
needs. A skill covers four things:

- when to use the pipeline
- the samplesheet columns and rules (technical replicates, single- and paired-end data, lanes)
- the parameters that matter, with safe defaults
- the typical failure causes

Keep skills short (30 to 50 lines) and factual. The plan check, not the skill, is the safety net.

## The pipeline registry

`REGISTRY` in `geth/bin/geth_checks.py` is the single source of truth about pipelines:

| Field | Meaning |
|---|---|
| `revision` | the pinned release; schemas are named `<pipeline>-<revision>.*.json` |
| `design` | samplesheet columns frozen after approval; `None` means every column |
| `key` | column(s) that identify a row, usually its first file; a tuple means the first non-empty |
| `required_params` | parameters the plan must set (schema `required` flags are unreliable: profiles and defaults fill many) |
| `downstream`, `profiles` | follow-up pipeline: takes contrasts and an analysis profile from this allowlist |
| `toolbox` | Geth's own single-cell toolbox, validated against `SC_MENU` instead of a schema |
| `star` | STAR version of the release: a reused `star_index` must have been built with it |
| `nextflow` | Nextflow version for the nested run (`NXF_VER`) |
| `java` | Java major version for the nested run, resolved from `GETH_JAVA<n>_HOME` |
| `nxf_env` | extra environment for the nested run, e.g. `NXF_SYNTAX_PARSER=v1` |
| `extra_config` | a config from `geth/conf/` added to the nested run |
| `input_format` | `tsv`: the samplesheet is converted before launch (eager) |
| `legacy_limits` | pass `--max_cpus/--max_memory/--max_time` (pre-`resourceLimits` templates) |
| `design_params` | parameters that describe the data, frozen by the gate like the design columns |
| `follows` | a follow-up: the pipeline whose finished run it builds on (projects check that order) |
| `second_sheet` | a second plan sheet: its file (`plan_contrasts.csv`, `plan_barcodes.csv`), the nf-core parameter `run_nfcore.sh` passes it as, and its name in messages. Internally it travels as "contrasts" (`--contrasts`, `contrasts_lines`) |

**Data-dependent memory.** `geth_checks.py resources` writes an extra config for jobs whose memory depends on
the data: Kraken2 loads its whole index in RAM, so taxprofiler's Kraken2 jobs ask for the index size plus a
margin. `reference-size` sets the resource caps: small inputs on a large genome or database get the
production caps.

**Index reuse.** A registered index has a `geth_index.json` next to it: tool, version, the FASTA and GTF it
was built from, and how it was built (`geth/references/register_star_index.sh`). The catalogue README gets
a `STAR index:` line, which the planner sees through `LIST_REFERENCES`, and the rnaseq and scrnaseq skills
say when to use it. `check_star_index()` refuses three cases: an index without `geth_index.json`, a STAR
version other than the registry's `star`, and a plan whose `fasta` or `gtf` differ from the recorded ones. A
STAR index stores the annotation's transcript and gene models, so STARsolo counts and Salmon's transcriptome
BAM depend on it.

**Multiplexed 10x.** `check_multiplexing()` reads the delivery's own text (`delivery_texts()`: README,
tables and the facility's HTML report, from the FASTQ folder up to two levels above, never above
`GETH_DATA_ROOT`). Signs of OCM, CellPlex or Flex refuse a plain scrnaseq plan: only `aligner=cellrangermulti`
with a barcodes sheet separates the samples of a library. The sheet is checked with the rules of
the release's `cellranger_multi_barcodes` schema (header, ids without spaces, a description, OCM barcodes
OB1–OB4) plus Geth's own: library names from the samplesheet, one barcode kind per library, a `cmo`
library for CellPlex, the probe set for Flex. In HTML only the strong
markers count (`10xOCM`, CellPlex, CMO301...), since reports carry boilerplate.

Pipeline-specific rules live in `EXTRA_CHECKS`, one function per pipeline taking the rows and params.
Examples: tumour/normal status in sarek, IP-to-control links in chipseq, the UDG treatment and its
parameter in eager. `INPUT_SPECS` replaces the samplesheet schema for releases that ship none, or an
outdated one (nanoseq, eager).

## Adding a pipeline

1. **Pick the release** and check that it runs at your site without agents:
   ```bash
   bench/baseline.sh <pipeline> <revision>     # its own test profile, with the site's profile
   ```
   If it fails on a modern Nextflow, look at how chipseq, nanoseq and eager are handled
   ([pipelines](pipelines.md#pipelines-with-their-own-runtime)).
2. **Store its schemas**, verbatim:
   ```bash
   r=https://raw.githubusercontent.com/nf-core/<pipeline>/<revision>
   curl -fsSL $r/nextflow_schema.json     -o geth/schemas/<pipeline>-<revision>.params.json
   curl -fsSL $r/assets/schema_input.json -o geth/schemas/<pipeline>-<revision>.input.json
   ```
   If the release has no input schema, describe the samplesheet in `INPUT_SPECS`.
3. **Register it** in `REGISTRY`: `revision`, `design`, `key`, and any runtime fields.
4. **Add its checks** to `EXTRA_CHECKS`. Write down the mistakes a planner could make that the schema
   does not catch, such as a control that is not a row of the sheet, or a mode that needs a parameter.
   Each check returns plain-English problems; the planner reads them.
5. **Write the skill** `geth/skills/nfcore-<pipeline>/SKILL.md` (the planner finds it by its folder), with
   its section "Ask when the delivery does not say". Then add the pipeline to the planner's instruction in
   `geth/harness/plan.py`.
6. **Results** (optional): add a collector to `collect_results.py`. Without one, the report gets the
   generic summary: MultiQC general statistics and the results folders.
7. **Unit tests** in `geth/tests/test_geth_checks.py`: a valid sheet passes, and each typical mistake
   is caught. Use placeholder files, as the existing tests do.
8. **Validate with agents.** Build a realistic delivery: raw files named as a facility would, and a
   free-text README. Run plan-only repeats, then a full run, and add a scorer to `bench/eval_plan.py`.

## The single-cell toolbox

`geth/bin/sc_downstream.py` runs in the pinned image
`depot.galaxyproject.org/singularity/celltypist:1.7.1--pyhdfd78af_2` (Scanpy 1.12.4, CellTypist 1.7.1).

- `inspect <h5ad>` prints per-cell distributions of counts, genes and mitochondrial percentage, and
  MAD-based outlier counts. The planner calls it before choosing thresholds.
- `run <h5ad> <design.json> <outdir>` runs the whole analysis:
  1. QC filters
  2. Scrublet doublets
  3. normalisation and log1p
  4. highly variable genes
  5. PCA
  6. neighbours and UMAP
  7. Leiden clustering at each resolution
  8. markers
  9. CellTypist annotation, optionally with majority voting; none when the design has no model (a species
     CellTypist does not cover: the analyst names clusters from the markers). Mitochondrial genes are those
     named `MT-*`, or, for species without the prefix (chicken), `ND1`…`CYTB`

  It writes `processed.h5ad`, `diagnostics.json`, figures and a text summary with FLAGS.

The design menu (`SC_MENU`: key → type, range or choices, required) is the only interface: agents never
write code. When `doublets.threshold=auto`, the threshold is the minimum between the two modes of the
simulated doublet-score histogram. That is Scrublet's own method, reimplemented because the container
lacks scikit-image. Caches (numba, matplotlib, CellTypist) go to the task folder, because home folders
are often read-only in jobs.

## Site configuration internals

- `env.sh` is the only place that reads `site/site.env`. Everything else reads environment variables. The
  agents read the model settings in `harness/llm.py`; `geth/nextflow.config` turns the folders into
  `params.data_root`, `params.runs_dir` and `params.references` for the tools' scheduler jobs.
- `env.fish` does not re-implement `env.sh`: it imports the changes `env.sh` makes in bash
  (`geth/bin/env_export.sh`). Fish completions are in `geth/completions/geth.fish`; update them when a
  command or option changes.
- The agents' tools run as subprocesses of the stage and inherit its environment, so `run_nfcore.sh` and the
  checks see the site settings. Scheduler jobs do not: `jobs.nf`'s `SC_ANALYSE` exports `GETH_REFERENCES`
  itself, and the containers get `-B` binds for the three Geth folders.
- **The site's task prelude survives a pipeline's own `beforeScript`.** An institutional profile often
  loads the container engine in `process.beforeScript` (Eddie: `module load apptainer`). A pipeline that
  sets `beforeScript` for one process replaces it there (scrnaseq 4.2.0's `CELLRANGER_MULTI`: the job
  failed with `env: 'apptainer': No such file or directory`). Before each launch, `run_nfcore.sh` reads
  the resolved configuration (`nextflow config -flat`, about 3 seconds) and `geth_checks.py keep-prelude`
  writes `attempt_N/prelude.config`, which runs the site's prelude first for each such selector.
- Scripts that may run as scheduler jobs (`bench/stage_*.sh`, `geth/references/*.sh`) find Geth through
  `GETH_HOME` when it is set. A job runs a copy of the script, so `$0` does not lead back to the
  repository.

## Tests

```bash
python3 geth/tests/test_geth_checks.py -v      # the gates: 60 tests, under a second, no site needed
python3 geth/tests/test_collect_results.py -v  # result summaries and the report check
python3 geth/tests/test_lab_build.py -v        # the lab's bookkeeping (arms B and C) and the shell quoting
python3 geth/tests/test_harness.py -v          # the agent loop, the planner's tools (scripted model), prose
python3 geth/tests/test_harness_run.py -v      # operator, analyst and reporter: outcome and report fences
python3 geth/tests/test_harness_lab.py -v      # the lab's agents: design check, notes and review
python3 geth/tests/test_project.py -v          # projects: the step check, approval, the runner (stand-in commands)
nextflow lint geth/jobs.nf geth/lab/jobs.nf
for f in env.sh geth/geth geth/lab/lab.sh geth/bin/*.sh geth/lab/bin/*.sh geth/references/*.sh bench/*.sh bench/lab/*.sh; do bash -n "$f"; done
fish -n env.fish geth/completions/geth.fish
geth doctor                                    # with a site: also probes the agent sandbox
```

The unit tests replay real failures: the smaller model's design changes, an edited plan after approval,
swapped contrasts, wrong single-cell designs, and a results summary that crashed on samplesheets
without a `sample` column. Their fixtures are placeholders written to a temporary
folder, so the tests run anywhere.

A useful trick for launcher changes: put a stub `nextflow` that prints its arguments first on `PATH`.
Then run `run_nfcore.sh` on a copy of an approved plan, and compare the command line with a real
launch.

## Benchmarks

| Script | What it does |
|---|---|
| `bench/stage_testdata.sh` | Two small deliveries from nf-core test data, with free-text READMEs: yeast bulk RNA-seq (mixed SE/PE, technical replicates), mouse 10x scRNA-seq (two samples, lanes). |
| `bench/stage_public.sh` | Real-size public data: airway (GSE52778, 24 GB), PBMC 1k v3 (5 GB), GRCh38, CellTypist immune models. |
| `bench/stage_deliveries.sh` | Seven realistic deliveries for the pipelines added in 1.4 (chipseq, atacseq, methylseq, ampliseq, nanoseq, eager, isoseq), built from nf-core test data. Files are renamed the way a facility would deliver them, with a free-text README and a sample table, and the traps are realistic: re-sequenced lanes, input controls shared per culture, facility IDs that are not valid sample names, a pooled Nanopore FASTQ. |
| `bench/bench_plan.sh <tag> <repeats> <delivery>...` | Plan-only repeats, each plan scored by `eval_plan.py`. Nothing is approved or run. |
| `bench/bench_run.sh <tag> <run>:<dataset>[:<planned run>]...` | Approves already-planned benchmark runs (or copies of another run's plan) and runs them end to end, scored by `eval_run.py`: success, honest outcome, report traced, pipeline and agent minutes. |
| `bench/bench_report.sh <tag> <finished run>...` | The reporter alone, on copies of finished runs (results hard-linked): numbers traced, sections, minutes. |
| `bench/stage_sparse.sh` | The same deliveries with a one-line README; `bench/facts/` holds what a stand-in scientist knows (`GETH_BENCH_TESTDATA=testdata_sparse GETH_BENCH_ANSWERS=yes`). |
| `bench/stage_broken.sh <tag>` | A delivery no allowed fix can repair (one FASTQ cut short), for the operator's honesty. |
| `bench/stage_chicken.sh` | A chicken germline delivery for sarek: three birds of DDBJ PRJDB17746, 2 million read pairs each, one bird on two lanes; plus the GRCg7b genome, known variants and VEP cache. |
| `bench/stage_index_tests.sh` | Airway and PBMC subsets, used to test STAR index reuse quickly. |
| `bench/snapshot.sh` | Freezes the last commit in `$GETH_WORK_ROOT/snapshots/<commit>`, so a long benchmark runs on fixed code while development goes on. A script that bash is executing must never be edited. |
| `bench/bench.sh <tag> <repeats> [bulk] [sc]` | plan → approve → run → score on the test deliveries. |
| `bench/bench_sc.sh <tag> <repeats> <upstream run>` | Agent-designed single-cell analyses on a finished scrnaseq run, scored. |
| `bench/baseline.sh <pipeline> [<revision>]` | A pipeline's own test profile, without agents. |
| `bench/baseline_airway_de.sh` | The hand-made textbook DE analysis of airway that Geth's DE runs are compared with. |
| `bench/eval_plan.py <run> <dataset>` | Scores a plan against the known truth: `bulk`, `sc`, `airway`, `pbmc`, `airway_de`, and the seven deliveries. Each scorer was checked with a hand-written correct plan (full marks, passes the plan check) and with injected mistakes. |
| `bench/eval_run.py <run> <dataset> <plan_s> <run_s>` | Plan score, design kept in every launched attempt, success, report check, attempts and refusals. For `airway_de`, the overlap with the baseline and the known dexamethasone genes. |
| `bench/eval_sc.py <run>` | Expected PBMC populations and markers, CellTypist agreement, QC sanity. |
| `bench/stage_projects.sh` | Deliveries for projects: yeast RNA-seq and ATAC-seq together, yeast RNA-seq without its reference, human small RNA (a gap). |
| `bench/bench_project.sh <tag> <repeats> <scenario>...` | Project plans only (`geth legion new`), scored by `eval_project.py` against the right steps of each scenario. |
| `bench/bench_project_run.sh <tag> <name>:<scenario>...` | Projects end to end, every approval automatic (benchmark data only): where each step ended and the project report's check. |

Results are appended as JSON lines to `$GETH_BENCH_DIR/<tag>.jsonl`. Benchmarks approve plans
automatically: use public data only.

## The legion: projects (geth legion)

A project is a list of steps towards one question, in `$GETH_RUNS_DIR/projects/<name>/`. Geth's agents never
run a step themselves: `geth_project.py` (no model) checks and runs them, and the coordinator
(`harness/project.py`) only decides, at three points.

1. **Plan** (`geth legion new`): the coordinator reads the delivery with the planner's read-only tools, plus
   `LIST_CAPABILITIES` (generated from the registry and the skills), `SEARCH_NFCORE` and `FIND_GENOME`
   (Ensembl's REST API). It ends with `SUBMIT_STEPS`. Each step has an `id`, a `kind`, its own `question` and
   `after` (the ids of earlier steps it builds on):
   - `pipeline`: a registry pipeline. A follow-up (`follows` in the registry) must come after exactly one step
     of that pipeline; a pipeline on sequencing data builds on no analysis step, and its `data` is a folder of
     the delivery (a relative path is inside it).
   - `reference`: `species`, `assembly`, `release`, verified against Ensembl's FTP (genome FASTA and GTF, with
     their sizes), refused when the catalogue already has the entry.
   - `gap`: a `suggestion`, and `nfcore` if a real nf-core pipeline would do it (refused if Geth runs it).
   - `lab`: only when the project was created with `--lab`, from one scrnaseq or sc_downstream step's count
     matrix, or from a delivery that is one `.h5ad`.
   At most 8 steps. `steps_check.txt` holds the result; `APPROVED` the approver and the SHA-256 of `steps.json`.
2. **Run** (`geth legion run`, `geth_project.py run`): the steps in order. A pipeline step is planned with
   `geth plan` (or `--from` its upstream step's run) into `<project>-<step>`; the runner stops (exit 2) until a
   person approves that plan; then `geth run`. A reference step runs `stage_ensembl.sh` through
   `GETH_DOWNLOAD_SUBMIT`. A lab step links the count matrix and a README into `lab_<step>/`, adds it to
   `GETH_LAB_DATA` for that step, runs `geth lab design`, waits for `approve-lab`, then `geth lab build`. A step
   whose `after` did not finish is not started. Everything is derived from the folders, so a stopped project
   resumes where it was.
3. **Review**, after each finished (or failed) step: `DECIDE` continue, stop, or revise. A revision must keep
   the steps that have started exactly as they were; it goes to `steps.proposed.json` and needs approval (exit 3).
4. **Summary**: `SUBMIT_REPORT` writes `report.md`, checked by `check_report.check_against` against the facts of
   every finished step's run, what the steps' reports quoted, and a lab step's result tables.

The coordinator runs as an agent stage (sandboxed, no driver slot), with the project's step runs and lab runs
mounted read-only (`--step_run`). `geth_project_<mode>.log` and `harness_trace_<mode>.jsonl` record each decision; `log.md`
records the run in plain words.

## The lab (experimental, phase 11)

`geth lab` (in `geth/lab/`) tests whether agents can design, and later build, a coherent single-cell
downstream analysis. It is **not for real analyses**. It is kept apart from Geth's workflow:

- its own command (`geth/lab/lab.sh`), agents (`geth/harness/lab.py`) and jobs (`geth/lab/jobs.nf`)
- its file tools only reach the benchmark folders (`GETH_LAB_DATA`, by default `$GETH_DATA_ROOT/testdata`),
  so the truth used for scoring (`$GETH_WORK_ROOT/lab_truth/`) stays out of reach
- runs go to `$GETH_RUNS_DIR/lab/`, and every file it writes is marked EXPERIMENTAL

`geth lab list` shows every lab run, its arm and its state; `geth lab show <name>` prints a design or a
build.

Arm A (`geth lab design`) asks a designer agent for a structured design and runs nothing:
- **steps:** nine required steps, each written as `step | method | tool | key parameters | why`
- **statistics:** one line per comparison: `comparison | unit of replication | test or model | design formula | multiple testing`
- **expected results**

`lab_checks.py` checks the format only. `bench/lab/eval_design.py` scores the science against what a
coherent analysis of each benchmark must do. Its main test is Kang et al. 2018 (8 donors, control vs IFN-β),
where the condition must be tested per cell type with donors as replicates (pseudobulk). The scorer was
checked on a coherent design (20/20) and on a naive one (7/20). Arm A runs with the best-practice skill
`sc-design-lab` (A1) and without it (A0), to separate what the model knows from what the skill tells it.

Arm B (`geth lab build <design run> <name>`) has agents write the code of a checked design, and runs it:

1. **Engineer** (skill `sc-build-lab`): writes one Python script per step with `WRITE_STEP`, and tests each
   on a 3,000-cell subset with `TEST_STEP` (an SGE task), the first from the subset and every other from the
   previous step's test output. When all pass, it saves the spec (`step | cpus | memory GB | minutes`) with
   `SAVE_SPEC`.
2. **Reviewer:** reads the design, the scripts and their test outputs (`READ_BUILD`, read-only) and answers
   `approve` or `revise` with one line per required change. A `revise` starts a second engineer round
   (at most two).
3. **Geth** renders `pipeline/main.nf` from the spec, with a frozen copy of the tested scripts, and runs it on
   the full data as SGE jobs (`results/<NN>_<step>/`).

The rules live in deterministic code, not in the prompts:
- **Sandbox** (`geth/lab/bin/lab_sandbox.sh`): every agent-written script runs in the pinned lab image with
  `apptainer exec --containall`. Its only writable folder (also its home) is `/work`; `/in` holds the script,
  the input and the models, read-only. `--net --network none` removes the network, and the environment is
  clean (no keys). Only regular files come back, never links. `bench/lab/sandbox_test.sh` runs an escape
  test (network, host folders, secret-like variables, writes and links) on the machine where it runs.
- **Static check** (`lab_step_check.py`): an import allowlist, no `eval`/`exec`, no process or file-system
  calls, no absolute paths, and `sys.argv` for input and output. It catches misuse early; the sandbox is what
  enforces the rules.
- **Bookkeeping** (`lab_build.py`): each test records fingerprints of the script and its input. The spec is
  accepted only when every step passed, in order, on its current code, and the results contract holds:
  `obs["cell_type"]` in the last output, and `de_results.tsv` or `markers.tsv` with
  `cell_type, gene, log2fc, padj`. The renderer refuses code that changed after its test.
- **Agent text** reaches the shell only inside single quotes, with each `'` written as `'\''`, and
  `lab_build.py` checks every name and path again.

`bench/lab/reference/kang2018/` holds hand-written reference steps that exercise the whole path and give a
baseline: 86% agreement with the published cell types, and the interferon response in all 8 cell types tested.
`bench/lab/eval_build.py` (run by `score_build.sh`, inside the image) scores a build:
- execution: steps, rounds, review verdict, tests and refusals
- Kang: agreement with the published labels, and interferon-stimulated genes up in each cell type
- PBMC: populations found and their canonical markers

`bench/lab/bench_build.sh` runs the benchmark.

`geth lab judge <name> <design run> <design run> ...` (phase 11.5) gives several designs of the same request,
labelled A, B, C, to a judge agent. The judge checks them against the data and writes the best one, with the
same format and check. `bench/lab/bench_judge.sh` scores it against its inputs.

Arm C (`geth lab build-c <design run> <name>`) has the engineer write the whole pipeline: `main.nf` and
Python scripts in `bin/`. Its tools:
- `WRITE_FILE` saves `main.nf` or `bin/<name>.py`, with the static check for Python
- `LINT_PIPELINE` runs `nextflow lint`
- `TEST_PIPELINE` runs the whole pipeline on the subset
- `READ_PROJECT` shows the project and the last test
- `SAVE_PIPELINE` accepts the pipeline only after a passing test on the current files, with the results
  contract: `final.h5ad` and the tables in `params.outdir`

A Nextflow script is code that runs in its driver, so an agent-written pipeline never runs as a normal
driver. `geth/lab/bin/lab_nf_sandbox.sh` runs driver and tasks together in the sandbox, as one SGE job:
- the project, input and models read-only; Java and Nextflow bound in read-only
- offline, with no network
- the local executor, with Geth's config applied last: no containers, no conda

`bench/lab/sandbox_test.sh --nextflow` runs a Groovy escape test in the driver itself. The full run uses the
frozen project (`pipeline_c/`), in one sandboxed job that retries with more memory.

## Agents in a container (phase 12)

With `GETH_AGENT_SANDBOX=yes`, `sandboxed` in `geth/bin/driver_slots.sh` starts every agent stage through
`geth/bin/agent_sandbox.sh`; this covers `geth plan`, `geth run` and `geth report`, the coordinator of
`geth legion`, and every `geth lab` stage.
The jobs the agents' tools start (nf-core pipelines, toolbox and lab jobs) are launched from inside. The wrapper:
- mounts, read-write, only the run folder, `NXF_HOME` and `GETH_AGENT_SANDBOX_RW`
- mounts, read-only, Geth, this run's data folder (the driver's `--data_dir`, or `data_dir.txt`), the
  catalogue, the lab images, Java, the Nextflow launcher and the SGE client. Each folder is mounted at the
  path the settings use, even behind a symbolic link
- passes the scheduler's ports, which the container cannot read from the host's `/etc/services`
- writes every other setting to a private env file (single-quoted values), and passes the API key through
  `APPTAINERENV_<key variable>` only (and the key of a model chosen with `--model`, if it has its own)
- turns the site's task prelude (`. /etc/profile.d/modules.sh; module load ...`) into a no-op inside; jobs run
  on the worker nodes as usual

Local tools then run inside the container. A tool that needs apptainer itself, such as `LINT_PIPELINE`, must
be a scheduler job. Every agent stage runs under `timeout` (`stage_limit`): a hung agent must not hold its
driver slot. The run folder's `.agent_home` records that the agents were sandboxed; `geth status` and
`geth lab show` report it.

## Lessons from Nextflow's agent preview (Geth 1.x: Nextflow 26.10.2, nf-agent 0.2.0)

Geth 1.x ran its agents on this preview. Geth 2.0 left it: the typed final answer took two thirds of the
planning time and could not be checked by a tool, and the agents' tools needed one process each. What it
taught still shapes the harness:


- Record fields need concrete generic types: `List<String>`, not `List`.
- Tool inputs cannot be `Path`. Pass absolute paths as `String`, and bind folders into containers
  (`containerOptions "-B ..."`).
- A failing tool task kills the agent. Tools must exit 0 and report failures as text.
- Structured output mangles JSON nested inside a text field. Hand over lists of lines, or let a tool
  save the data (`SAVE_ANNOTATIONS`).
- Name every record field in the prompt.
- The agent runs inside the driver JVM. On a cluster, the driver must run where jobs can be submitted;
  keep its JVM small (`GETH_DRIVER_CPUS`, `-Xmx4g`).
- A nested `nextflow run` inside a local task must use its own launch folder, or `-resume` picks up
  the parent's session lock.

## Conventions

- **Shell:** `set -uo pipefail`. Tools never fail: they print `STATUS: ...` lines.
- **Python:** standard library only, 3.9+. The toolbox is the exception: it runs in its container.
- **Agents' text shown to people** goes through `harness/prose.py` (`prose` in the shell scripts): one
  sentence per line, wrapped to the terminal. Files keep the text as the agent wrote it.
- **Progress in the terminal.** When the command's output is a terminal, `agents()` (and the lab's `lab_stage`)
  pass `--progress`: the stage gives its agent a `TerminalProgress` (`harness/ask.py`), which writes one line per
  tool call to `/dev/tty` (the stage's stdout is its log), the check verdicts, and for long tools a line refreshed
  every 30 seconds (`run.pipeline_progress()`: tasks from the attempt's Nextflow log and trace). Give a new tool a
  label there.
- **Paths:** absolute, compared as text, resolved to real paths by `env.sh`.
- **Never** print, log or commit the API key, or put it on a command line.
- **Git flow:** `master` holds tagged releases (`vX.Y.Z`); work happens in `develop`, with features on
  `feature/*`. A `release/X.Y.Z` branch bumps `VERSION`, is merged into `master` and tagged, then merged
  back into `develop`; `hotfix/*` branches come from `master`.

## Limitations and roadmap

- Validated with agents on real-size data for four analysis types. The planner of the other pipelines is
  validated on test-size deliveries only.
- One organism and one experiment per plan. A project (`geth legion`) splits a delivery with several data
  types into steps, but not several organisms.
- Only STAR indexes can be registered for reuse so far (`geth/references/register_star_index.sh`); other
  aligners' indexes (Salmon, Bowtie2, BWA, Bismark...) are still built by each run.
- sarek is tested on livestock germline calling only (no GATK bundle for human, no somatic calling yet);
  mag without GTDB-Tk and CheckM2 databases; taxprofiler with Kraken2 and Bracken, not MetaPhlAn.
- The single-cell analyst's revisions were refused on format until 2.0; it now revises when a flag calls
  for it, once.
- Agent-written analyses and pipelines exist only in the experimental lab (phase 11), on benchmark data.
  `geth plan` and `geth run` use the pinned, vetted pipelines and toolbox only.
- In the agent sandbox, pulling a pipeline image that is not yet cached is untested.
