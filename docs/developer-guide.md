# Developer guide

How Geth works inside, how to change it, and how to add a pipeline. It assumes you know Nextflow and
nf-core, and have read the [introduction](introduction.md).

## Design in one paragraph

Geth is a **Nextflow workflow whose steps are agents**, built on Nextflow 26.10's `agent` primitive
(plugin `nf-agent`). Each agent gets an instruction, a few **tools**, optionally **skills**, and returns a
typed **record**. A tool is a Nextflow process, so a tool can run locally or as a scheduler job like any
task. Around the agents sit **deterministic gates** written in plain Python (`geth_checks.py`). The gates
validate every plan against the pinned pipeline's own schemas, freeze the approved design, and decide
which changes a retry may make. A finished report is checked number by number against the results. The
agents decide; the gates verify; a person approves.

## Where to start reading

Follow one analysis through the code, in the order things happen:

1. `geth/geth`: the commands. `geth plan` and `geth run` both end in `nf()`, which starts
   `geth/main.nf` with a mode. Each driver goes through `sandboxed` (`geth/bin/driver_slots.sh`), inside
   the agent sandbox when the site asks for it.
2. `geth/main.nf`, from the bottom: the `workflow` block picks the mode. Read the `planner` agent above it:
   its instruction, its tools and its record. Each tool is a short `process` (`LIST_FILES`, `CHECK_PLAN` ...).
3. `geth/bin/geth_checks.py`: what the tools call. `REGISTRY` describes every pipeline; `check_plan` is the
   plan check; `approve` fingerprints the plan; `gate` is the plan-diff gate the operator meets on every
   launch.
4. `geth/bin/run_nfcore.sh`: the operator's only way to start a pipeline, with the gate before and the error
   digest after.
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
  geth                     the command line: plan, show, approve, run, status, list, stop, doctor, version, lab
  main.nf                  the workflow: records, tools (processes), agents, bookkeeping, workflow block
  nextflow.config          Geth's own settings, read from the environment (model, endpoint, folders)
  bin/                     on the tasks' PATH (Nextflow adds a pipeline's bin/ automatically)
    geth_checks.py         the gates: registry, plan check, save-plan, approve, plan-diff gate, record
    run_nfcore.sh          RUN_NFCORE tool: one gated, resumable nf-core launch per call
    sc_downstream.py       the single-cell toolbox (inspect / run), executed in the CellTypist container
    sc_analyse.sh          SC_ANALYSE tool: one gated toolbox analysis per call
    collect_results.py     ready-to-copy result tables for the reporter
    check_report.py        traces every number and link of the report to the facts
    geth_doctor.sh         installation checks (geth doctor)
    driver_slots.sh        driver slots (GETH_MAX_DRIVERS), stage time limits, the sandboxed() launcher
    stop_driver.sh         geth stop / geth lab stop: ends a run's drivers, processes and scheduler jobs
    agent_sandbox.sh       runs an agent driver in a container (GETH_AGENT_SANDBOX, phase 12)
    env_export.sh          env.fish helper: what env.sh changes in the environment, as NUL-separated records
  completions/geth.fish    fish tab completion (loaded by env.fish)
  conf/                    configs added to nf-core runs: resource caps, legacy singularity engine
  schemas/                 <pipeline>-<release>.params.json / .input.json, verbatim from each release
  skills/                  planner skills: one SKILL.md per pipeline, plus sc-downstream
  references/              scripts that add entries to the reference catalogue
  tests/                   unit tests of the gates and of the lab's bookkeeping (self-contained)
  lab/                     the EXPERIMENTAL lab (phase 11): not used by geth plan / geth run
    lab.sh                 geth lab: design, judge, show, list, build (arm B), build-c (arm C), stop
    main.nf                designer, judge, engineer, reviewer agents and their tools
    bin/                   lab_checks.py (design format), lab_inspect.py, lab_build.py (arm B/C bookkeeping),
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
Nextflow's cache. The files below are the interface between the CLI, the agents, the gates and the
person.

| File | Written by | Content |
|---|---|---|
| `question.txt`, `data_dir.txt` | workflow (plan mode) | the request and the data folder |
| `plan_pipeline.txt`, `plan_samplesheet.csv`, `plan_params.json`, `plan_rationale.txt` | `SAVE_PLAN` (`save-plan`) | the plan |
| `plan_contrasts.csv`, `plan_profile.txt`, `plan_upstream.txt` | `SAVE_PLAN` | downstream pipelines only |
| `plan_barcodes.csv` | `SAVE_PLAN` | multiplexed scrnaseq only: the Cell Ranger multi barcodes sheet |
| `plan_check.txt` | `SAVE_PLAN` | the plan check result |
| `.checked/` | `CHECK_PLAN` | the last plan version that passed the check during planning (fallback) |
| `APPROVED` | `geth approve` | approver, time, SHA-256 of every plan file |
| `gate_state.json` | `record` | the last accepted attempt and the error that may justify the next change |
| `attempt_N/` | `run_nfcore.sh` | `samplesheet.csv`, `params.submitted.json`, `params.json` (normalised), `gate.txt`, `check.txt`, `nextflow.log`, `error.txt` (and `contrasts.csv` or `barcodes.csv`, `samplesheet.tsv`) |
| `analysis_N/` | `sc_analyse.sh` | toolbox analyses: `design.submitted.txt`, `design.json`, `diagnostics.json`, `summary.txt`, figures, `processed.h5ad` |
| `nfcore/` | `run_nfcore.sh` | launch folder of the nested nf-core run (its `.nextflow/` and log) |
| `results/`, `work/` | nf-core | the pipeline's outputs and work folder |
| `outcome.txt` | `SAVE_OUTCOME` | the operator's or analyst's structured outcome |
| `annotations.txt` | `SAVE_ANNOTATIONS` | single-cell cluster annotations |
| `report.md`, `report_check.txt` | `FINALIZE_REPORT` | the checked report |
| `geth_<mode>.log`, `geth_trace_<mode>.txt`, `.nextflow.log*`, `geth_work/` | Nextflow | Geth's own driver: log, task trace, work folder |
| `.geth_<mode>.pid` | `geth` | present while a driver works on the run (`geth list`, `geth stop`): host, pid, driver slots |

Because the folder holds the whole state, `geth run` resumes after an interruption: Nextflow `-resume`
in `nfcore/`, attempt numbering continues, and the gate state persists.

**Stopping.** `geth stop` (`stop_driver.sh`) reads the live `.geth_*.pid` files and walks the process tree
below each pid (sandbox included: apptainer's PID namespace is visible from the host). It stops the Geth
command first, so no further stage starts, then sends SIGTERM to every Nextflow driver in the tree at once:
each cancels its own scheduler jobs. After `GETH_STOP_GRACE` seconds the rest of the tree gets SIGTERM, then
SIGKILL. Last, it deletes any job of the user whose working folder (`qstat -j`: `cwd`) is inside the run
folder. It appends `stopped by geth stop` to the stage's log, which `geth list` shows.

## Lifecycle of an analysis

### Plan (`geth plan` → `main.nf --mode plan`)

1. The CLI creates the run folder and starts Geth's workflow. The workflow block checks the site
   settings, the model allowlist, and that `run_dir` lies under `GETH_RUNS_DIR`.
2. The **planner** agent receives the question, the data folder and, for `--from`, the upstream run. It
   has these tools:

   | Tool | What it does |
   |---|---|
   | `LIST_FILES` | `find`, depth 3, under `GETH_DATA_ROOT` only |
   | `READ_TEXT` | first 8 kB of a text file, or 8 decompressed lines of a `.gz`, under `GETH_DATA_ROOT` only |
   | `LIST_REFERENCES` | prints every catalogue `README.txt` |
   | `SC_INSPECT` | per-cell QC distributions of an `.h5ad` (a job) |
   | `CHECK_PLAN` | `geth_checks.py check-plan`; also saves passing versions to `.checked/` |

   It also gets **skills**: one per pipeline. It must call `CHECK_PLAN` until it prints
   `PLAN CHECK: OK`, and fix or explain every `WARNING:` line (`plan_warnings()`: samples of the
   delivery's tables that appear nowhere in the plan; a 10x chemistry the delivery never states, or GEM-X
   planned as v3). Warnings never block a plan.
3. The planner answers with a `PlanProposal` record. The samplesheet, parameters and the second sheet
   (`contrasts_lines`: contrasts, or the multiplexed samples) come back as **lists of lines**: JSON nested
   in a text field was mangled by the structured-output step.
4. `SAVE_PLAN` runs `geth_checks.py save-plan`. It re-checks the answer and writes the `plan_*` files.
   If the final answer fails the check but a version in `.checked/` passed, it keeps the checked
   version and says so in the rationale.

### Approve (`geth approve`)

`geth approve` refuses a plan that fails the check. Otherwise `geth_checks.py approve` writes
`APPROVED`, with the SHA-256 of every plan file, and resets `gate_state.json`. Every later read of the approved plan (`approved_plan()`) re-hashes
the files. A file edited after approval makes every gate call fail until a person approves again.

### Run (`geth run` → `main.nf --mode run`)

1. The workflow reads the plan files into an `AnalysisPlan` record. It hands the record to the
   **operator**, or to the **analyst** when the pipeline is `sc_downstream`.
2. The operator's only tool is `RUN_NFCORE`, which runs `run_nfcore.sh`. Each call is one attempt, in a
   new `attempt_N/`:
   1. Refuse run folders outside `GETH_RUNS_DIR`, and pipelines not in the registry.
   2. **Plan-diff gate** (`geth_checks.py gate`), described below. A refusal is reported as
      `STATUS: REFUSED`, and nothing is launched.
   3. **Plan check** (`check-plan`) of the submitted attempt. A failure is recorded as a `check` error,
      so the next attempt may fix exactly that.
   4. Resources: `test.config` for inputs under 2 GB on a reference under 500 MB, `production.config`
      otherwise (a human genome needs large jobs whatever the read count).
   5. Per-pipeline runtime (`geth_checks.py runtime`): Nextflow version, Java, extra config,
      environment, TSV input, `--max_*` limits.
   6. Launch from `nfcore/`, with `-resume`. Geth's own driver runs in the run folder, so a separate
      launch folder keeps `-resume` from picking up the driver's session.
   7. Print a digest: status, outdir, warnings, or an error report extracted from the Nextflow log plus
      the failed task's stderr. Then `record` the attempt: `ok`, `check` or `nextflow`.

   The tool **always exits 0**. In the Nextflow agent preview, a failing tool task kills the agent, so
   failures are reported as text. The operator may call `RUN_NFCORE` at most 3 times; the launcher
   refuses a 6th attempt in any case.
3. `SAVE_OUTCOME` writes `outcome.txt` from the operator's `RunOutcome` record.
4. The **reporter** calls `COLLECT_RESULTS` (`collect_results.py`): ready-to-copy, rounded, labelled
   tables, so that the model never does arithmetic. It then writes the report.
5. `FINALIZE_REPORT` runs `check_report.py`. Every number in the report must match a fact, at the
   precision written and allowing for scales of 1, 100, 0.01, 10⁻³ and 10⁻⁶. Integers ≤ 20 are not
   checked: they are counts of samples, files or attempts. Facts are the collected results, the raw QC
   values, the plan, the question and the number of attempts. Links must appear in the facts.
   Untraced numbers or links add a warning section to `report.md`.

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
CellTypist container:

1. The first analysis must run the approved design unchanged.
2. Exactly one revision may follow. It may change only tunable keys (`SC_TUNABLE`: QC thresholds,
   doublet rate or threshold, HVGs, neighbours, Leiden resolutions) and needs a `justification=` line
   that cites a diagnostic (`SC_DIAGNOSTIC_TERMS`).
3. The input matrix, normalisation, marker panel and annotation model stay frozen.

The toolbox prints **FLAGS**:

- fewer than 85% of cells kept
- a doublet rate outside a third to three times the expected rate
- a cluster with less than 60% CellTypist agreement
- a cluster with fewer than 10 cells

The analyst must address each flag or explain why it needs no change. It then annotates every cluster
and saves the annotations with `SAVE_ANNOTATIONS`. Annotations are a tool call rather than a record
field, because the structured outcome dropped them.

## The agents

| Agent | Tools | Skills | maxIterations | Returns |
|---|---|---|---|---|
| `planner` | `LIST_FILES`, `READ_TEXT`, `LIST_REFERENCES`, `CHECK_PLAN`, `SC_INSPECT` | all 14 | 25 | `PlanProposal` |
| `operator` | `RUN_NFCORE` | none | 10 | `RunOutcome` |
| `analyst` | `SC_ANALYSE`, `SAVE_ANNOTATIONS` | `sc-downstream` | 8 | `RunOutcome` |
| `reporter` | `COLLECT_RESULTS` | none | 5 | Markdown (stdout) |

All agents use `openai/${params.model}` through the `agent` scope of `nextflow.config`: runner
`langchain4j`, base URL and key from the environment, 600 s request timeout. Prompts name every field of
the expected record, because models invent fields otherwise. Instructions state what success looks like
("never claim success unless the tool printed STATUS: SUCCESS").

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
5. **Write the skill** `geth/skills/nfcore-<pipeline>/SKILL.md`. Then add it to the planner's `skills`
   list, and the pipeline to the planner's instruction, in `main.nf`.
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
  9. CellTypist annotation, optionally with majority voting

  It writes `processed.h5ad`, `diagnostics.json`, figures and a text summary with FLAGS.

The design menu (`SC_MENU`: key → type, range or choices, required) is the only interface: agents never
write code. When `doublets.threshold=auto`, the threshold is the minimum between the two modes of the
simulated doublet-score histogram. That is Scrublet's own method, reimplemented because the container
lacks scikit-image. Caches (numba, matplotlib, CellTypist) go to the task folder, because home folders
are often read-only in jobs.

## Site configuration internals

- `env.sh` is the only place that reads `site/site.env`. Everything else reads environment variables.
  `geth/nextflow.config` turns them into `params.model`, `params.allowed_models`, `params.data_root`,
  `params.runs_dir` and `params.references`, and configures the `agent` scope.
- `env.fish` does not re-implement `env.sh`: it imports the changes `env.sh` makes in bash
  (`geth/bin/env_export.sh`). Fish completions are in `geth/completions/geth.fish`; update them when a
  command or option changes.
- The local tools (`executor 'local'`) inherit the driver's environment, so `run_nfcore.sh` and the
  checks see the site settings. Scheduler jobs do not: `SC_ANALYSE` exports `GETH_REFERENCES` itself,
  and the containers get `-B` binds for the three Geth folders.
- Scripts that may run as scheduler jobs (`bench/stage_*.sh`, `geth/references/*.sh`) find Geth through
  `GETH_HOME` when it is set. A job runs a copy of the script, so `$0` does not lead back to the
  repository.

## Tests

```bash
python3 geth/tests/test_geth_checks.py -v      # the gates: 40 tests, under a second, no site needed
python3 geth/tests/test_collect_results.py -v  # result summaries and the report check
python3 geth/tests/test_lab_build.py -v        # the lab's bookkeeping (arms B and C) and the shell quoting
nextflow lint geth/main.nf geth/lab/main.nf
for f in geth/geth geth/lab/lab.sh geth/bin/*.sh geth/lab/bin/*.sh bench/*.sh bench/lab/*.sh; do bash -n "$f"; done
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
| `bench/bench_run.sh <tag> <run>:<dataset>...` | Approves already-planned benchmark runs and runs them end to end, scored by `eval_run.py`. |
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

Results are appended as JSON lines to `$GETH_BENCH_DIR/<tag>.jsonl`. Benchmarks approve plans
automatically: use public data only.

## The lab (experimental, phase 11)

`geth lab` (in `geth/lab/`) tests whether agents can design, and later build, a coherent single-cell
downstream analysis. It is **not for real analyses**. It is kept apart from Geth's workflow:

- its own Nextflow workflow (`geth/lab/main.nf`) and command (`geth/lab/lab.sh`)
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

With `GETH_AGENT_SANDBOX=yes`, `sandboxed` in `geth/bin/driver_slots.sh` starts every agent driver through
`geth/bin/agent_sandbox.sh`; this covers `geth plan` and `geth run`, and every `geth lab` stage. The wrapper:
- mounts, read-write, only the run folder, `NXF_HOME` and `GETH_AGENT_SANDBOX_RW`
- mounts, read-only, Geth, this run's data folder (the driver's `--data_dir`, or `data_dir.txt`), the
  catalogue, the lab images, Java, the Nextflow launcher and the SGE client. Each folder is mounted at the
  path the settings use, even behind a symbolic link
- passes the scheduler's ports, which the container cannot read from the host's `/etc/services`
- writes every other setting to a private env file (single-quoted values), and passes the API key through
  `APPTAINERENV_<key variable>` only
- turns the site's task prelude (`. /etc/profile.d/modules.sh; module load ...`) into a no-op inside; jobs run
  on the worker nodes as usual

Local tools then run inside the container. A tool that needs apptainer itself, such as `LINT_PIPELINE`, must
be a scheduler job. Every agent stage runs under `timeout` (`stage_limit`): a hung agent must not hold its
driver slot. The run folder's `.agent_home` records that the driver was sandboxed; `geth status` and
`geth lab show` report it.

## Lessons from the Nextflow agent preview (26.10.2, nf-agent 0.2.0)

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
- **Paths:** absolute, compared as text, resolved to real paths by `env.sh`.
- **Never** print, log or commit the API key, or put it on a command line.
- **Git flow:** `master` holds tagged releases (`vX.Y.Z`); work happens in `develop`, with features on
  `feature/*`. A `release/X.Y.Z` branch bumps `VERSION`, is merged into `master` and tagged, then merged
  back into `develop`; `hotfix/*` branches come from `master`.

## Limitations and roadmap

- Validated with agents on real-size data for four analysis types. The planner of the other pipelines is
  validated on test-size deliveries only.
- One organism and one experiment per plan.
- Only STAR indexes can be registered for reuse so far (`geth/references/register_star_index.sh`); other
  aligners' indexes (Salmon, Bowtie2, BWA, Bismark...) are still built by each run.
- sarek is tested on livestock germline calling only (no GATK bundle for human, no somatic calling yet);
  mag without GTDB-Tk and CheckM2 databases; taxprofiler with Kraken2 and Bracken, not MetaPhlAn.
- The single-cell analyst is lenient: in the benchmark it answered every flag but never chose to
  revise a design.
- The agent API is a preview, so expect changes with new Nextflow releases.
- Agent-written analyses and pipelines exist only in the experimental lab (phase 11), on benchmark data.
  `geth plan` and `geth run` use the pinned, vetted pipelines and toolbox only.
- In the agent sandbox, pulling a pipeline image that is not yet cached is untested.
