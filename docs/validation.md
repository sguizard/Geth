# Validation

What has been tested, how it was scored, and what the results were. All runs used public data on the
reference site: an SGE cluster, with apptainer and the nf-core institutional profile. The model was
**Qwen3.5-397B-A17B (FP8)**, unless stated otherwise. The scripts are in `bench/` (see the
[developer guide](developer-guide.md#benchmarks)).

## How runs are scored

- **Plan.** The plan is compared with the known truth of the dataset, check by check:
  - the right pipeline
  - one sample per biological sample, with technical replicates and lanes merged
  - stray files left out and index reads ignored
  - the treatment visible in the sample names
  - valid parameters, and the right reference from the catalogue
  - for differential expression: the contrast direction, blocking on donor, the same annotation as the
    upstream run
- **Run.**
  - the pipeline finished, with its outputs
  - the approved design was kept in every launched attempt
  - the number of attempts, and how many the plan-diff gate refused
- **Report.** The share of the report's numbers that `check_report.py` traced to the results.
- **Science**, where a known answer exists:
  - **differential expression:** overlap with a hand-made baseline analysis, and the known
    dexamethasone-induced genes
  - **single-cell:** the expected PBMC populations with their canonical markers, and agreement with
    CellTypist

## Choosing the model

Early feasibility tests compared the two models available for free on the reference site's gateway,
with 3 planner repeats per model on each of 2 test deliveries:

| Model | Correct plans | Full runs |
|---|---|---|
| Qwen3.5-397B-A17B | **6/6** (technical replicates merged, mixed single- and paired-end, lanes, 10x v2, references) | 2/2 succeeded, design kept, faithful reports |
| Mistral Small 4 (119B) | 0/6 (invented parameters, broken header, wrong pipeline name) | 2/2 pipelines finished, but in the bulk run the operator silently changed the design, and the reports had numeric errors |

That second row is why Geth has a plan-diff gate and a report check, and why it uses one strong model
for every agent.

## Results

| Version | Data | Runs | Plan | Pipeline | Design kept | Report numbers traced |
|---|---|---|---|---|---|---|
| 1.0 | yeast bulk RNA-seq (nf-core test data) | 3 | 3/3 correct | 3/3 | 3/3 | 138/139 |
| 1.0 | mouse 10x scRNA-seq, chr19 (nf-core test data) | 3 | 1/3 correct | 1/3 | no wrong launch | 36/38 |
| 1.1 | the same two test deliveries | 4 | 4/4 | 4/4 | 4/4 | 146/146 |
| 1.1 | **airway** bulk RNA-seq (GSE52778): 8 samples, 24 GB, GRCh38 | 1 | 12/12 checks | 287 tasks, 2 h 08 from approval to report | yes | 64/64 |
| 1.1 | **PBMC 1k v3** (10x Genomics), GRCh38 | 1 | 12/12 checks | 15 tasks, 67 min, 1,120 cells | yes | 28/28 |
| 1.2 | **airway differential expression**, on the airway run | 1 (+2 plan only) | 3/3 plans, 12/12 checks each | 12 min. **Identical to the hand-made baseline**: the same 650 DE genes (Jaccard 1.0), and 7/7 known dexamethasone genes up | yes | 26/26 |
| 1.3 | **PBMC 1k v3 with CellBender** on a GPU | 1 | 12/12 checks | 20 tasks; CellBender on a GPU in 6.6 min | yes | 38/38 |
| 1.3 | **agent-designed single-cell analysis** of that run | 3 | 3/3 designs pass the check | each found 7/7 expected PBMC populations; labels agree with CellTypist's broad types for 100% of cells; doublets 0.8% (automatic threshold) | n/a | 291/291 |

The known dexamethasone genes are DUSP1, FKBP5, KLF15, PER1, TSC22D3, ZBTB16 and CRISPLD2. The expected
PBMC populations are CD4 T, CD8 T, NK, B, CD14 monocytes, FCGR3A monocytes and dendritic cells.

**What failed, and what changed.**

- **Version 1.0, single-cell.** The planner's structured answer nested JSON parameters inside a text
  field, and that field was mangled on the way. Version 1.1 hands parameters over as lists of lines, and
  keeps the last checked version of the plan as a fallback.
- **Real-size behaviour seen without prompting.** The planner left out stray unpaired-read files. It
  merged lanes, ignored index reads, and picked the reference from the catalogue. A job the scheduler
  killed (exit 140) was retried by nf-core itself, and no agent action was needed.

## Pipelines without agents

Each additional pipeline was run on its own test profile at the reference site, with Geth's runtime
settings (`bench/baseline.sh`):

| Pipeline | Tasks | Runtime |
|---|---|---|
| isoseq 3.0.1 | 45 | Nextflow 26.10.2 |
| ampliseq 3.0.0 | 126 | Nextflow 26.10.2 |
| methylseq 4.2.0 | 35 | legacy config parser |
| chipseq 2.1.0 | 202 | legacy config parser |
| atacseq 2.1.2 | 256 | legacy config parser |
| nanoseq 3.1.0 | 26 | Nextflow 23.10.4, singularity engine |
| eager 2.5.3 | 26 | Nextflow 22.10.8 + Java 17, singularity engine |

Their plan checks are unit-tested. Planner benchmarks on realistic deliveries for these pipelines are the
next step.

## Not yet tested

- Messy deliveries beyond the test sets: inconsistent file names, missing metadata, several organisms or
  batches.
- Repeatability at scale: one full run per real-size dataset so far, with planner repeats on top.
- Other models, and other sites. The site configuration makes this possible; results are welcome.
- Language-model availability and rate limits under sustained use.

The full development record, phase by phase, is in [history/feasibility.md](history/feasibility.md).
