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

## Proposed next steps
1. Implement the plan-diff gate + plan approval step; rerun the 4 full runs × 3 repeats (Qwen and Mistral).
2. Add one real (anonymised/public) dataset per pipeline, sized for a few hours of compute.
3. Add a DE stage (nf-core/differentialabundance) for bulk, then revisit the Frontier-style "agent writes the
   pipeline" idea only once v1 is reliable.
