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
| plan | **planner** (tools: list/read files, reference catalogue, `CHECK_PLAN`; nf-core skills) | picks rnaseq or scrnaseq, writes samplesheet + params + rationale |
| | plan check (`geth_checks.py`) | samplesheet and params against the pinned pipeline schemas; files exist and are really gzip; the last checked plan is kept as fallback |
| approve | **a person** | approval hashes the plan files; any later edit needs a new approval |
| run | **operator** (tool `RUN_NFCORE`) | launches the approved plan; on failure changes only what the error names |
| | plan-diff gate | sample names and files can never change; other changes only where the previous error points |
| | nf-core + roslin profile | SGE jobs (`-P roslin_alaw3_grp`), apptainer, resumable; resources picked by input size |
| report | **reporter** (tool `COLLECT_RESULTS`) | Markdown report from rounded, labelled result tables |
| | report check | every number and link must trace to the results, otherwise the report carries a warning |

Pinned: Nextflow 26.10.2, nf-agent 0.2.0, nf-core/rnaseq 3.27.0, nf-core/scrnaseq 4.2.0.

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
