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
| 1.5 | smoke test of the site configuration: yeast bulk test delivery, then a single-cell design on the PBMC run | 2 | 13/13 checks; design passes | both succeeded; 7/7 PBMC populations, 12/12 clusters annotated, 100% agreement with CellTypist. 81% of cells kept: the designer chose stricter QC than the benchmark's 85% target, and the analyst did not revise | yes | 42/42 and 88/88 |

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

Their plan checks are unit-tested.

## The planner on realistic deliveries

`bench/stage_deliveries.sh` builds one delivery per pipeline above from nf-core test data. The files are
renamed the way a sequencing facility would deliver them, and each delivery has a free-text README and a
sample table. Each also holds a trap that real deliveries hold:

| Delivery | What the planner must work out |
|---|---|
| chipseq_spt5 | Two time points of a Spt5 ChIP, two cultures each, and one input DNA per culture: group the replicates, and link each ChIP to the input of its own culture. |
| atacseq_osmotic | Two conditions, two replicates each; one library sequenced on two lanes; the mitochondrial contig name. |
| methylseq_wgbs | One bisulfite library on three lanes; no library-preparation preset. |
| ampliseq_16s | Primers given in the README; two sequencing runs; facility sample numbers that are not valid sample names; metadata that cannot be used as is. |
| nanoseq_barcoded | One pooled FASTQ to demultiplex; the kit's commercial name, not the demultiplexer's; replicates as barcodes. |
| eager_mammoth | Two libraries with different sequencers (colour chemistry), layouts and UDG treatments. |
| isoseq_brain | Raw subreads with their index, primers, and a reference subset with its annotation. |

Plans were scored check by check against the known design (`bench/eval_plan.py`, 9 to 13 checks per
delivery), 3 plan-only repeats each:

| Delivery | Round 1 | Round 2 |
|---|---|---|
| methylseq_wgbs, eager_mammoth, isoseq_brain | 3/3 fully correct each | not needed |
| atacseq_osmotic | 2/3 (one guessed `mito_name=M`; the contig is `MT`) | 3/3 |
| ampliseq_16s | 2/3 (one used metadata whose IDs match no sample name: the run would fail) | 3/3 |
| chipseq_spt5 | 2/3 (one made every library its own sample: replicates never grouped) | 3/3 |
| nanoseq_barcoded | 0/3 (commercial kit name `EXP-NBD104` instead of qcat's `NBD103/NBD104`) | 3/3 |

Every plan of round 1 passed the plan check, so the failures showed what the check could not see. Before
round 2:
- **Three new plan checks:**
  - `mito_name` must be one of the reference FASTA's contigs (they are listed when it is not)
  - ampliseq metadata IDs must be the sample names, and the metadata category one of its columns
  - Nanopore barcode kits must use qcat's names
- **Two skills clarified:** the Nanopore skill's own example used a commercial kit name. The ChIP-seq
  skill now says that `sample` is the condition, not the library.

## Full runs of the new pipelines (version 1.6)

One fully correct plan per delivery was approved (benchmark data) and run end to end:
- the operator launched the nf-core pipeline
- the reporter wrote the report
- the report check traced its numbers

| Pipeline | First run | After the fixes below | Report numbers traced |
|---|---|---|---|
| atacseq, methylseq, eager | succeeded, 1 attempt | not needed | 2/3, 13/13, 33/33 |
| chipseq | failed after 3 attempts | succeeded, 1 attempt | 2/3 |
| ampliseq | failed after 2 attempts | succeeded, 1 attempt | 47/47 |
| nanoseq | failed after 3 attempts | succeeded, 1 attempt | 18/18 |
| isoseq | failed after 3 attempts | succeeded, 1 attempt | 21/24 |

What the first runs showed, and what changed:
- **chipseq**
  - The plan's input rows had dropped their trailing empty fields. Samplesheets are now written with
    every column on every row.
  - preseq failed on the tiny data. The operator proposed `skip_preseq`, but the gate refused it because
    the error named the process, not the parameter. `skip_<step>` is now accepted when the error names
    the step.
- **nanoseq**
  - The plan lacked `skip_quantification` for DNA. The operator then **changed the protocol from DNA to
    cDNA** to silence the error, and the gate allowed it because the error mentioned "protocol".
  - Parameters that describe the data (protocol, library presets, primers) are now frozen like sample
    names.
  - The plan check requires the RNA-only steps to be skipped for DNA.
- **ampliseq**
  - The release requires `config_profile_name`, which only nf-core's test profile sets. Geth now sets it.
  - The operator passed the site profile as an analysis profile. Upstream pipelines now refuse one.
- **isoseq**
  - With the default 40 CCS chunks, most chunks of the small input were empty and the merge step failed.
    The plan check requires `chunk_ccs` of 5 or fewer for inputs under 2 GB.
  - The operator relaunched twice unchanged. A third identical launch is now refused.

## Index reuse (version 1.6)

The GRCh38 STAR index built by the PBMC run (29 GB, about 30 minutes) was registered in the catalogue.
- **Planner:** in 6/6 plans on two subset deliveries (airway, PBMC), it set `star_index` to the
  registered index, with its FASTA and GTF.
- **Runs:** both succeeded without building an index. The airway run took 53 minutes, mostly queue waits
  for full-size jobs; the PBMC run took 12 minutes.

## Not yet tested

- Messy deliveries beyond the test sets: inconsistent file names, missing metadata, several organisms or
  batches.
- Repeatability at scale: one full run per real-size dataset so far, with planner repeats on top.
- Other models, and other sites. The site configuration makes this possible; results are welcome.
- Language-model availability and rate limits under sustained use.

The full development record, phase by phase, is in [history/feasibility.md](history/feasibility.md).
