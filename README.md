# Geth

Feasibility study: can LLM agents backed by the University's **free ELM models** plan, run, debug and report
routine nf-core analyses (bulk RNA-seq, scRNA-seq) on **Eddie**, using Nextflow's `agent` primitive (≥ 26.10)?

## Layout
| Path | What |
|---|---|
| `env.sh` | Source first in every shell/job: strips forbidden PATH entries, pins `NXF_VER=26.10.2`, sets `NXF_SGE_PROJECT=roslin_alaw3_grp` (nf-core `roslin` profile), free-model allowlist |
| `spikes/elm/` | Spike 1 — ELM API capability probe (`elm_probe.py`), compute-node network check (`netcheck.sge`), `RESULTS.md` |
| `spikes/nf-agent/` | Spike 2 — Nextflow agents on ELM: `hello/`, `qc-tool/` (agent → FastQC tool on SGE), `RESULTS.md` |
| `spikes/nfcore/geth/` | Spike 3 — Geth workflow: planner → operator → reporter agents over pinned nf-core/rnaseq 3.27.0 and nf-core/scrnaseq 4.2.0 |
| `spikes/nfcore/` | Test-data staging, `run_geth.sh` launcher, `eval_plan.py` scorer, `RESULTS.md` |

Runtime data (work dirs, test data, run folders) live in `/exports/eddie/scratch/sguizard/Perseus_Veil`.

## Run
```bash
source env.sh
spikes/nfcore/stage_testdata.sh                                   # once
spikes/nfcore/run_geth.sh bulk qwen my_run                        # full run: plan → nf-core on SGE → report
spikes/nfcore/run_geth.sh sc mistral my_plan --plan_only true     # planner only
```
Outputs in `$PERSEUS_VEIL/spikes/nfcore/runs/<name>/`: `plan_*`, `attempt_N/` (samplesheet, params, Nextflow log),
`results/`, `outcome.txt`, `report.md`.

## Rules baked in
- Only `Qwen/Qwen3.5-397B-A17B-FP8` and `mistralai/Mistral-Small-4-119B-2603` (free) — every entry point refuses other models.
- The Nextflow driver runs on the submit host (node1q01) with `-XX:ActiveProcessorCount=2`; all heavy work goes to SGE (`-P roslin_alaw3_grp`).
- The ELM key is read from `$ELM_API_KEY` and never written to disk, logs or job environments.
