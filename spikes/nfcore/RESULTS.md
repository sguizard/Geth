# Spike 3 — agentic nf-core runs (2026-10-16)

Workflow: `geth/main.nf` (Nextflow 26.10.2, `nf-agent@0.2.0`, driver on node1q01, nf-core jobs on SGE via `-profile roslin`).
Agents: **planner** (tools `LIST_FILES`, `READ_TEXT`, skills `nfcore-rnaseq`/`nfcore-scrnaseq`) → **operator**
(tool `RUN_NFCORE`, ≤ 3 attempts, resumable) → **reporter** (tool `COLLECT_RESULTS`).
Pinned pipelines: nf-core/rnaseq 3.27.0, nf-core/scrnaseq 4.2.0.

Test deliveries (`stage_testdata.sh`), built from nf-core test data as raw folders + free-text metadata:
- **bulk_yeast** — 11 FASTQs from 7 runs → 5 biological samples; 2 technical-replicate pairs to merge; mixed SE/PE;
  strandedness undocumented; custom reference.
- **sc_mouse_chr19** — 10x 3' v2, 2 samples, one split over 2 lanes; mouse chr19 reference.

## Baselines (no agents): `-profile test,roslin`
| Pipeline | Tasks | Result |
|---|---|---|
| nf-core/rnaseq 3.27.0 | 234 | completed, 0 failed |
| nf-core/scrnaseq 4.2.0 | 19 | completed, 0 failed |

→ Eddie + roslin profile + Nextflow 26.10.2 run both pipelines; failures in agentic runs are attributable to agents.

## Planner only (`--plan_only true`), 3 repeats × model × dataset, scored by `eval_plan.py`
Checks: pipeline choice, samplesheet columns/rows/grouping/layout/strandedness/paths, reference params,
**every param key exists in the pinned pipeline schema**.

| | Qwen3.5-397B | Mistral-Small-4 |
|---|---|---|
| bulk: perfect plans | **3/3** (13/13) | 0/3 (8, 12, 12 /13) |
| sc: perfect plans | **3/3** (12/12) | 0/3 (10, 11, 11 /12) |
| wall time per plan | 77–177 s | 14–17 s |

Mistral errors: dropped `sample` from the CSV header (1×); pipeline named `single_cell` (1×); invented or
obsolete params in every plan (`strandedness` as a param, `skip_qcach`, `max_cpus`/`max_memory`,
`skip_qcaggregate`, `skip_bioconductor`). Sample grouping itself was right in 5/6.
Qwen: all plans perfect; one rationale text mislabelled a paired-end run as single-end (samplesheet itself correct).
Typical planner trajectory: `LIST_FILES` → `READ_TEXT` README + metadata (parallel) → `activate_skill` → answer.

**Lesson:** nf-core only *warns* on unknown params, so invented params silently do nothing. `run_nfcore.sh` now
rejects unknown params against the pinned schema (with "did you mean" hints) before launching, and refuses
any pipeline other than rnaseq/scrnaseq and any run dir outside `Perseus_Veil/spikes/nfcore/runs/`.

## Full runs (plan → run on SGE → fix/retry → report), 1 per model × dataset
| Run | Plan | Attempts | Pipeline | Design kept | Report | Wall time |
|---|---|---|---|---|---|---|
| bulk · Qwen | invented `strandedness` param | 2 (guard → fixed) | ✅ | ✅ | faithful; 2 minor slips | 7.3 min |
| sc · Qwen | perfect | 1 | ✅ | ✅ | faithful; mislabels R1/R2 as lanes | 8.1 min |
| bulk · Mistral | invented `strandedness` param | 2 (guard → fixed) | ✅ | ❌ **operator split a technical replicate into a fake `REP3`, unreported** | wrong numbers (×1000 read counts, "6 samples" vs 5 listed), inverted reasoning | 4.6 min |
| sc · Mistral | typo `skip_qcach` | 2 (guard → fixed) | ✅ | ✅ | numbers right; fabricated issue link, self-contradiction | 5.5 min |

Wall time = whole Geth run (3 agents + nf-core on SGE) on the test data.

### What worked
- 4/4 runs reached a successful nf-core run with **zero human intervention**; every failure was caught by the
  param guard and fixed by the operator in one retry ("did you mean" hints are enough).
- Agents waited fine on long tool tasks (nested nf-core run of several minutes inside a tool call).
- Qwen reports cite only tool numbers and add sensible domain context (subset reference ⇒ low gene count/mapping).

### What failed / must change for v1
1. **Silent design corruption (Mistral operator)**: rewrote the samplesheet on its first call without any error
   prompting it, turning technical replicates into biological ones, and did not report it.
   → The operator must not resubmit the samplesheet freely: Geth should diff every attempt against the approved
   plan and refuse (or ask a human) when sample grouping or files change; params changes must be limited to keys
   named in the error.
2. **Unrequested param changes** (Mistral set `unstranded_threshold` 0.2) → same diff rule.
3. **Report hallucinations** (Mistral: scale errors, fake link; Qwen: minor mislabels) → have `COLLECT_RESULTS`
   emit pre-formatted, rounded tables that the reporter must copy, and run a numeric cross-check of the report
   against the tool output before publishing.
4. Even Qwen invented a param once in 4 plans → the schema guard is mandatory, not optional.
5. Infra bug found and fixed: nested nf-core run must use its own launch dir (else `-resume` grabs the
   Geth driver's locked session).
