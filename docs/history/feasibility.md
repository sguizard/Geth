# Geth — feasibility decision (2026-10-16)

**Question:** can free University ELM models drive Nextflow agents that plan, run, fix and report routine
nf-core analyses on Eddie, cheaply and reliably?

**Answer: GO, with Qwen3.5-397B as the default model and deterministic guards around every agent action.**
Mistral-Small-4 is only fit for narrow, mechanical steps.

## Evidence (details in `spikes/*/RESULTS.md`)
| Step | Result |
|---|---|
| ELM API | OpenAI-compatible; both free models do tool calls, JSON-schema output and ~130k-token prompts. Compute nodes can reach ELM. |
| Nextflow `agent` (26.10.2, nf-agent 0.2.0) | Works with ELM. Agent → process tool → SGE job (`-P roslin_alaw3_grp`) verified. Preview limits: no `Path` tool inputs, a tool failure kills the agent. |
| nf-core baselines (no agents) | rnaseq 3.27.0 (234 tasks) and scrnaseq 4.2.0 (19 tasks) pass with `-profile roslin`. |
| Planner, 3 repeats/model/dataset | Qwen **6/6 perfect** plans (technical-replicate merging, mixed SE/PE, lanes, 10x v2, references). Mistral 0/6 (invented params, broken header, wrong pipeline name). |
| Full runs, 2 datasets × 2 models | **4/4 pipelines succeeded, 0 human interventions**, 4.6–8.1 min wall time each on test data. Qwen runs: correct design and faithful reports. Mistral bulk run: **operator silently corrupted the design**; reports contain numeric errors. |
| Cost | Tokens: free (ELM). Compute: normal Eddie jobs, ~same as running the pipeline by hand. Driver: ≤ 4 CPUs on node1q01. |

## Must-haves for v1 (lessons learned)
1. **Deterministic guards, not trust**: schema check of params (done), allowlisted pipelines/revisions/paths (done),
   and a **plan-diff gate** — any attempt that changes sample grouping/files or params not named by the error is
   refused or sent to a human.
2. **Human approval of the plan** before launch for real data (samplesheet + params + rationale shown together).
3. **Reports from structured facts**: tool emits rounded, ready-made tables; a checker verifies every number in the
   report exists in the tool output; no links/URLs unless provided by tools.
4. Qwen for planner/operator/reporter. Disable Qwen thinking only where speed matters and accuracy is not at stake.
5. Pin Nextflow (26.10.x) and `nf-agent` plugin versions — the agent API is a preview and will change.

## Not yet tested (risks)
- Real-size data (hours-long runs, SGE queue waits, out-of-memory/time failures needing resource fixes).
- Messier deliveries (inconsistent file names, missing metadata, multiple organisms/batches).
- Repeatability at scale: only 1 full run per model × dataset (planner: 3 repeats).
- Downstream analysis (DE with nf-core/differentialabundance, clustering/annotation) — where the scientific
  judgement, and so the risk, is highest.
- ELM availability/rate limits under sustained use (no rate-limit headers observed).

## Results since the decision (Qwen 3.5 only)
| Version | Data | Runs | Correct plan | Pipeline success | Design kept | Report numbers traced |
|---|---|---|---|---|---|---|
| v1.0 | test bulk yeast | 3 | 3/3 | 3/3 | 3/3 | 138/139 |
| v1.0 | test scRNA mouse chr19 | 3 | 1/3 | 1/3 | no wrong launch | 36/38 |
| v1.1 | test scRNA + bulk | 4 | 4/4 | 4/4 | 4/4 | 146/146 |
| v1.1 | **airway** (GSE52778, 8 samples, GRCh38) | 1 | 12/12 checks | ✅ 287 tasks, 2 h 08 from approval to report, 23 CPU-h | ✅ | 64/64 |
| v1.1 | **PBMC 1k v3** (10x, GRCh38) | 1 | 12/12 checks | ✅ 15 tasks, 67 min, 1,120 cells | ✅ | 28/28 |
| v1.2 | **airway DE** (differentialabundance on airway_1) | 1 (+2 plan-only) | 3/3 plans 12/12 | ✅ 12 min; identical to hand-made baseline (650 DE genes, Jaccard 1.0); 7/7 known dex genes up | ✅ | 26/26 |
| v1.3 | **PBMC 1k v3 + CellBender on GPU** (pbmc_2) | 1 | 12/12 checks | ✅ 20 tasks; CellBender on the gpu queue (node1o16, `--cuda`, 6.6 min) | ✅ | 38/38 |
| v1.3 | **agent-designed scRNA downstream** on pbmc_2 (3 repeats) | 3 | 3/3 designs pass the check | ✅ 7/7 expected PBMC populations each; analyst labels = CellTypist broad types for 100% of cells; doublets 0.8% (auto threshold) | n/a | 291/291 |

v1.0 scRNA failures: the structured hand-off mangled JSON parameters nested in a text field; fixed in v1.1
by handing lists to Geth and keeping the last checked plan. Real-size planner behaviour: stray unpaired-read
files left out, lanes merged, index reads ignored, reference picked from the catalogue, all unprompted.
A Salmon index job killed by SGE (exit 140) was retried by nf-core itself; no agent action was needed.

## Proposed next steps
1. ~~Plan-diff gate + plan approval; repeats~~ done (v1, v1.1).
2. ~~One real-size public dataset per pipeline~~ done (airway, PBMC 1k v3).
3. ~~Differential expression for bulk~~ done (v1.2.0): airway, identical to the baseline, 7/7 known dex genes.
4. ~~Single-cell clustering/annotation on PBMC 1k v3~~ done (v1.3.0): agents design and run it on a vetted toolbox.
5. Reuse built indexes across runs (STAR index for GRCh38 took 26 min and 65 GB per run).
5b. ~~More pipelines~~ v1.4.0: 10 more nf-core pipelines with skills and checks; 7 pass their test profiles on Eddie
   (older templates run with their own Nextflow: legacy config parser, 23.10.4, or 22.10.8 for DSL1 eager);
   sarek/taxprofiler/mag wait for the existing databases. Next: planner tests on realistic deliveries per pipeline.
6. Frontier-style "agent writes the pipeline" only once 3-4 are reliable.
