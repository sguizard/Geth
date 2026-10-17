# Geth

LLM agents that **plan, run, fix and report** routine nf-core analyses (bulk RNA-seq, scRNA-seq) on the
University of Edinburgh's **Eddie** cluster, using Nextflow's `agent` primitive (≥ 26.10) and the
University's free ELM model **Qwen 3.5 397B**. Deterministic gates around every agent action keep the
experimental design and the reported numbers honest.

Progress page: <https://claude.ai/artifact/T3ApkP9kZzudYe7X1vFAnH> (source: `docs/progress.html`).

## Use
```bash
source env.sh
geth/geth plan <data_dir> "<question>" <name>   # planner agent writes a plan into $PERSEUS_VEIL/geth/runs/<name>
geth/geth plan --from <run> "<question>" <name> # follow-up of a finished run: differential expression (rnaseq run)
                                                #   or an agent-designed single-cell analysis (scrnaseq run)
geth/geth show <name>                           # review it; edit plan_samplesheet.csv / plan_params.json if needed
geth/geth approve <name>                        # a person approves (refused if the plan fails the plan check)
geth/geth run <name> [--detach]                 # operator + reporter agents; --detach for multi-hour runs
geth/geth status <name>                         # outcome, attempts, report check; report in runs/<name>/report.md
```
Data folders and the reference catalogue (`$PERSEUS_VEIL/references`, filled with
`geth/references/stage_ensembl.sh`) must be under `/exports/eddie/scratch/sguizard/Perseus_Veil`.

## How it works
| Step | Agent / gate | What it does |
|---|---|---|
| plan | **planner** (tools: list/read files, reference catalogue, `CHECK_PLAN`; nf-core skills) | picks rnaseq or scrnaseq for new data, or differentialabundance on a finished rnaseq run; writes samplesheet (or observations + contrasts + analysis profile), params and rationale |
| | plan check (`geth_checks.py`) | samplesheet and params against the pinned pipeline schemas; files exist and are really gzip; the last checked plan is kept as fallback |
| approve | **a person** | approval hashes the plan files; any later edit needs a new approval |
| run | **operator** (tool `RUN_NFCORE`) | launches the approved plan; on failure changes only what the error names |
| | **analyst** (single-cell designs; tools `SC_ANALYSE`, `SAVE_ANNOTATIONS`) | runs the approved design on Geth's Scanpy/CellTypist toolbox, answers each diagnostic flag, may revise tunable keys once with a justification, annotates clusters |
| | plan-diff gate | sample names and files can never change; other changes only where the previous error points |
| | nf-core + roslin profile | SGE jobs (`-P roslin_alaw3_grp`), apptainer, resumable; resources picked by input size; CellBender on the `gpu` queue (`-l gpu=1`) |
| report | **reporter** (tool `COLLECT_RESULTS`) | Markdown report from rounded, labelled result tables |
| | report check | every number and link must trace to the results, otherwise the report carries a warning |

Geth's driver: Nextflow 26.10.2 + nf-agent 0.2.0. Single-cell toolbox: CellTypist 1.7.1 container (Scanpy 1.12.4).

## Pipelines
Each pipeline is pinned, has a planner skill (`geth/skills/`), schema-driven and pipeline-specific plan checks
(`geth/bin/geth_checks.py`), and runs with its own Nextflow when its template needs it. "Test profile" = the
pipeline's own test run on Eddie with `-profile test,roslin` (`bench/baseline.sh`).

| Pipeline | Version | Nested Nextflow | Test profile on Eddie | Validated with agents |
|---|---|---|---|---|
| rnaseq | 3.27.0 | 26.10.2 | ✅ 234 tasks | ✅ test data + airway (real size) |
| scrnaseq | 4.2.0 | 26.10.2 (+ GPU CellBender) | ✅ 19 tasks | ✅ test data + PBMC 1k v3 |
| differentialabundance | 2.0.0 | 26.10.2 | ✅ (airway baseline) | ✅ airway DE |
| sc_downstream (Geth toolbox) | 1.0.0 | — | — | ✅ PBMC 1k v3 designs |
| isoseq | 3.0.1 | 26.10.2 | ✅ 45 tasks | not yet |
| ampliseq | 3.0.0 | 26.10.2 | ✅ 126 tasks | not yet |
| methylseq | 4.2.0 | 26.10.2, legacy config parser | ✅ 35 tasks | not yet |
| chipseq | 2.1.0 | 26.10.2, legacy config parser | ✅ 202 tasks | not yet |
| atacseq | 2.1.2 | 26.10.2, legacy config parser | ✅ 256 tasks | not yet |
| nanoseq | 3.1.0 | 23.10.4, singularity engine | ✅ 26 tasks | not yet |
| eager | 2.5.3 (DSL1) | 22.10.8 + Java 17, singularity engine, TSV input | ✅ 26 tasks | not yet |
| sarek, taxprofiler, mag | 3.10.0, 2.0.1, 5.5.0 | 26.10.2 | parked: need the existing database copies | — |
Regression tests: `python3 geth/tests/test_geth_checks.py`.

## Layout
| Path | What |
|---|---|
| `env.sh` | Source first: PATH clean-up, pinned Nextflow, `NXF_SGE_PROJECT=roslin_alaw3_grp`, free-model allowlist |
| `geth/` | The tool: `geth` CLI, `main.nf` (agents and tools), `bin/` (gates, nf-core launcher, results, report check), `skills/`, `schemas/`, `conf/`, `references/` |
| `bench/` | Benchmark loop and scorers (`bench.sh`, `eval_plan.py`, `eval_run.py`), public-data staging job |
| `spikes/` | Feasibility spikes 1–3 (frozen record) and their `RESULTS.md` |
| `FEASIBILITY.md` | Feasibility decision and results since |

## Rules baked in
- Only the free ELM model Qwen 3.5 397B; the key is read from `$ELM_API_KEY` and never written anywhere.
- The Nextflow drivers run on node1q01 (compute nodes cannot submit SGE jobs) with ≤ 4 CPUs in total;
  all heavy work goes to SGE.
