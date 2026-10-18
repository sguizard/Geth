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

### Germline calling and metagenomics

Three more deliveries, on references and databases shared on the site, run the same way:
- **chicken_wgs** (nf-core/sarek): three chickens, one on two lanes; Ensembl 116 known variants and VEP cache
- **taxprofiler_reads** (nf-core/taxprofiler): two gut metagenomes, one sequenced in two paired-end runs and a
  single-end one; the shared Kraken2/Bracken standard database
- **mag_gut** (nf-core/mag): two mouse gut metagenomes, one on two lanes; no host genome, no GTDB-Tk database

| Pipeline | Planner (3 repeats) | Full run, after the fixes | Report numbers traced |
|---|---|---|---|
| sarek | 16, 16, 15 of 16 | succeeded, 1 attempt, 46 min | 42/42 |
| taxprofiler | 13/13 three times | succeeded, 1 attempt, 6 min | 79/79 |
| mag | 11/11 three times | succeeded, 1 attempt | 37/37 |

The one planner miss left `joint_germline` unset (each chicken genotyped alone). Each pipeline's first full run
failed, each on a gap in Geth:
- **sarek:** the skill said to give the known-variants VCF as both `dbsnp` and `known_indels`; sarek stages
  them together and the same file name collides. The skill now says `dbsnp` only, and the plan check refuses
  the same file twice. The operator's fixes (dropping a parameter, adding `baserecalibrator` to `skip_tools`)
  were refused because the gate only accepted changes to parameters the error named; it now also accepts
  changing a file the error names, and skipping a tool it names.
- **taxprofiler:**
  - Merging the runs of a sample needs one endedness, unless read pairs are merged first. The error was
    missed by Geth's error digest, which now catches nf-core's own `ERROR:` lines; the plan check requires
    pair merging in that case.
  - The second run showed that taxprofiler needs different `db_name`s for the kraken2 and bracken rows of
    one database. The registration script gave both the same name; it no longer does, and the plan check
    refuses it. The operator tried to switch off Bracken and the profile standardisation instead: the gate
    refused both, rightly, since they would have dropped analyses the plan asked for.
- **mag:**
  - ALE crashes on these tiny assemblies. The gate refused `skip_ale` because step names under 4 letters
    did not count. A 3-letter step now counts when the error names it as a word, not inside a file name.
  - The first successful run's report had no numbers: Geth had no results summary for mag. It now gives
    assemblies (QUAST, reads mapped back) and bins per sample and binner.

## Index reuse (version 1.6)

The GRCh38 STAR index built by the PBMC run (29 GB, about 30 minutes) was registered in the catalogue.
- **Planner:** in 6/6 plans on two subset deliveries (airway, PBMC), it set `star_index` to the
  registered index, with its FASTA and GTF.
- **Runs:** both succeeded without building an index. The airway run took 53 minutes, mostly queue waits
  for full-size jobs; the PBMC run took 12 minutes.

## Geth lab, arm A: agents designing single-cell analyses (experimental, version 1.6)

Can a designer agent write a coherent single-cell downstream analysis? Arm A asks for a structured design
(steps, statistics, expected results, rationale) and runs nothing. Each design is scored by
`bench/lab/eval_design.py`; the answers are kept out of the agent's reach.
- **Kang 2018** (20 checks): PBMCs of 8 donors, control and interferon-beta stimulated, with demuxlet
  calls. The question: which genes respond in each cell type? The cell labels are removed. The matrix is
  already filtered and has no mitochondrial genes.
- **PBMC 1k** (12 checks): the CellBender matrix of Geth's PBMC run (1,351 cells). The question: which
  cell types, and their markers?
- **A1** gives the designer a best-practice skill (`geth/lab/skills/sc-design-lab`); **A0** does not.

| Arm | Kang 2018 (out of 20) | PBMC 1k (out of 12) |
|---|---|---|
| A1, with the skill | 19, 19, 18, 18, 18, 17 (mean 18.2) | 12, 12, 12, 12, 12, 11 (mean 11.8) |
| A0, no skill | 15, 15, 16 (mean 15.3) | 11, 11, 10 (mean 10.7) |

Two designs ended on a tool error (below) and are left out: one per arm.

**With the skill**, every design:
- kept the demuxlet singlets instead of running a doublet detector
- tested conditions on pseudobulk counts per cell type and donor (pyDESeq2, `~ donor + condition`), with
  Benjamini-Hochberg correction
- integrated across donors or conditions (Harmony) on Kang, and not on the single PBMC sample
- predicted the interferon-stimulated genes (IFIT1, ISG15, MX1), with the strongest response in monocytes

On PBMC every design set data-driven QC (MAD rules per metric). One also added a 25% mitochondrial cap,
after noticing that 5% of the cells are near-empty with over 95% mitochondrial reads.

**Without the skill**, the Kang designs:
- tested conditions with MAST and donor as a random effect instead of pseudobulk (2/3). This accounts for
  donors, but it is the weaker choice in published benchmarks.
- did not notice that the matrix has no mitochondrial reads (3/3)
- skipped integration across conditions (2/3)

**Both arms** annotated with a CellTypist model alone, without checking canonical markers. This happened
in all Kang designs and in 4 of the 9 PBMC designs. Kang designs also rarely listed the expected cell types.
That check may be too strict for a question about the interferon response.

The first round exposed four faults in the lab harness, all fixed:
- `--lab_skill false` reached Nextflow as the text "false", which is true in Groovy. The first six "A0"
  designs had the skill too; they are counted as A1 above.
- The file tools failed on a misspelt path, which ended the run, instead of answering "not found".
- The scorer read numbers quoted in a step's reason as cut-offs.
- The scorer did not recognise `pca_umap` as PCA.

**Conclusion:** with the skill, Qwen 3.5 designs analyses that follow current best practice and avoid
pseudoreplication. Without it, the designs remain plausible but statistically weaker. Arms B and C (agents
writing and running the analysis code, in a sandbox) wait for a go.

## Geth lab, arm B: agents write the analysis code (experimental, version 1.6)

`geth lab build` takes a checked arm A design (with the skill) and has two agents implement it:
- **the engineer** writes one Python script per step and tests each on a 3,000-cell subset in the sandbox
- **the reviewer** reads the scripts and their test outputs, and approves or asks for changes (two rounds at most)

Geth then runs the steps on the full data. A build is **deliverable** only if the reviewer's last verdict
is "approve". The engineer has a coding skill (`sc-build-lab`, arm B1) or none (B0); both build the same
three Kang designs. Every agent-written step ran in the sandbox: no network, no host files, no keys.

**Kang 2018** (published cell types; the interferon response per cell type). A reference build of
hand-written steps, through the same path, gives the bar: 86.3% agreement with the published cell types,
and the response in 8/8 cell types tested.

| Arm | Round | Design | Review | Failed subset tests | Cell types right | Cell types with the response | What went wrong |
|---|---|---|---|---|---|---|---|
| B1 | 1 | 1 | approve | 0 | 86.0% | 6/7 | |
| B1 | 1 | 2 | approve | 1 | 86.1% | 8/8 | |
| B1 | 1 | 3 | approve | 1 | 81.7% | 6/6 | |
| B1 | 2 | 1 | **revise** | 1 | 86.0% | 0/7 | pseudobulk summed the wrong cells (positions from a subset, matrix of the whole) |
| B1 | 2 | 2 | approve | 0 | 85.9% | 8/8 | |
| B1 | 2 | 3 | approve | 3 | 82.0% | 6/6 | |
| B0 | 1 | 1 | **revise** | 23 | 76.7% | 26/40 | DESeq2 model without the donor (`~ condition`); genes written as Ensembl IDs |
| B0 | 1 | 2 | **revise** | 15 | 85.1% | 12/19 | DE limited to the 2,000 variable genes |
| B0 | 1 | 3 | **revise** | 5 | 82.1% | 1/8 | an unpaired t-test written by hand instead of pyDESeq2 ("a simplified version") |
| B0 | 2 | 1 | approve | 10 | 81.7% | 13/16 | |
| B0 | 2 | 2 | **revise** | 15 | 83.0% | 12/16 | DE limited to the 2,000 variable genes |
| B0 | 2 | 3 | approve | 4 | 82.0% | 7/8 | gave a step 8 GB for 10.4 GB; ran once Geth retried with more memory |

- **With the skill, 5 of 6 builds were deliverable; without it, 2 of 6.** Deliverable builds match the
  reference: 81.7–86.1% of cells labelled as published, and the response in monocytes and in nearly every
  cell type tested.
- **Without the skill, the engineer slips on library APIs, then quietly falls back** to a weaker method:
  an old pyDESeq2 argument that drops the donor, a hand-written t-test, a gene subset that removes most genes
  from the test. It failed 12 subset tests per build on average, against 1 with the skill.
- **The reviewer approved no defective build, and flagged every one**, naming the step and the fix.
  The engineer then fixed the problem in some builds, but not in these five within two rounds.
- A build took 16 to 97 minutes from design to full results, SGE queue time included.

The first round exposed faults in the harness, all fixed before round 2:
- the reviewer's verdict was read from its final structured answer, which leaked commentary ("The model
  failed to output valid JSON") into the issues and turned approvals into "revise"; it now submits its
  verdict with a tool
- the results contract did not say gene symbols, nor how to report markers per cluster
- the scorer did not translate Ensembl IDs

After round 2, the rendered pipelines retry a step killed for memory or time with twice, then four times,
the resources; and the agents substitute a Python method for an R tool a design names (the image has no R).

**PBMC 1k** (the expected populations and their canonical markers; B1 only). Round 2 was invalidated by a
fault in the contract: it asked for gene symbols "as the var names", but this matrix's var names are
Ensembl IDs, so the reviewer and the spec check pulled in opposite directions. After the fix (round 3):

| Design | Annotation model in the design | Review | Populations found | Canonical markers | Cells kept | Caught by the reviewer in round 1, then fixed |
|---|---|---|---|---|---|---|
| 1 | broad (Immune_All_High) | approve | 5 | 3/4 | 78.5% | mitochondrial genes looked up by Ensembl ID, so no cell had any |
| 2 | fine (Immune_All_Low) | approve | 7 | 6/6 | 96.2% | 30 principal components where the design said 50 |
| 3 | broad (Immune_All_High) | approve | 5 | 4/5 | 85.4% | markers on normalised values and per cell type, where the design said raw counts and per cluster |

All three were deliverable. A broad model cannot separate CD4 from CD8 T cells or the two monocyte types,
so those designs find 5 populations. Design 1's mitochondrial rule (3 MADs above the median, no cap) removes
21% of the cells: strict for this sample, but what the design asked for.

**Conclusion:** with the coding skill, Qwen 3.5 builds working, correct analyses from a checked design in
most cases (8 of 9 builds deliverable). The reviewer is what makes the result trustworthy: it flagged every
defect the scores revealed, from a missing donor term to a mitochondrial lookup on the wrong identifiers,
and it approved no build whose results scored wrong. Without the skill the code is weaker and the engineer often cannot fix what the
reviewer finds (2 of 6). Arm C (agents writing the Nextflow themselves) waits for a go.

## Geth lab, arm C: agents write the Nextflow pipeline too (experimental, version 1.7)

`geth lab build-c` has the engineer write the whole pipeline: `main.nf` and Python scripts in `bin/`.
It tests the pipeline on the subset, the reviewer reads it, and Geth runs the frozen project on the full data.
A Nextflow script is code that runs in its driver, so an agent-written pipeline never runs as a normal driver:
- **Driver and tasks run inside the sandbox** (`geth/lab/bin/lab_nf_sandbox.sh`), as one SGE job.
- **Nothing gets out:** no network, no host files, no keys, no scheduler. Java and Nextflow are bound in
  read-only; the local executor and Geth's config apply last (no containers, no conda).
- **Escape test:** a Groovy escape test run by the driver itself passed on node1q01 and on a worker node. It
  tried Java networking, host folders, environment keys, writes outside its folder, `qsub` and links
  (`bench/lab/sandbox_test.sh --nextflow`).

The engineer has both skills (`sc-build-lab`, `nf-build-lab`). A hand-written reference project through the
same path labels 90.9% of the Kang cells as published and finds the interferon response in 7/7 cell types.
That is the same code as arm B's reference, which scored 86.3%; clustering and integration vary between runs.

| Dataset | Design | Review | Scripts | Failed subset tests | Result | Time |
|---|---|---|---|---|---|---|
| Kang | 1 | approve (round 1) | 5 | 0 | 86.0% of cells right; response in 5/5 cell types | 27 min |
| Kang | 2 | approve (round 1) | 6 | 0 | 86.1%; 5/5 | 8 min |
| Kang | 3 | approve (round 1) | 9 | 2 | 83.0%; 7/7 | 34 min |
| PBMC | 1 | approve (round 1) | 8 | 4 | 5 populations, markers 3/4, 96.1% of cells kept | 23 min |
| PBMC | 2 | approve (round 2) | 9 | 4 | 6 populations, markers 4/5, 77.9% kept | 18 min |
| PBMC | 3 | approve (round 2) | 10 | 9 | 5 populations, markers 4/4, 77.9% kept | 27 min |

All six were deliverable. The engineer's first `main.nf` passed lint every time. Every Kang pipeline used
pseudobulk sums of raw counts with `~ donor + condition`.

The PBMC rows are a second run: the first three PBMC builds were not approved, because of the image. scanpy's
Scrublet with its automatic threshold needs scikit-image, so the doublet steps failed silently or were dropped.
`seurat_v3` variable genes, which a design asked for, need scikit-misc. The reviewer flagged both, and a real
QC bug too: `|` where the filter needed `&`. The image now has both packages, and the coding skill says so,
for these reruns.

**Conclusion:** with its skills, Qwen 3.5 writes a working, correct Nextflow pipeline from a checked design, as
reliably as it writes arm B's step scripts. The reviewer stays the safeguard. The image must hold what
best-practice designs ask for: a missing package turned into silent failures, not errors.

## Agents in a container (phase 12, version 1.7)

With `GETH_AGENT_SANDBOX=yes`, every agent driver runs inside apptainer on the machine Geth runs on: the
planner, operator, reporter and the lab's agents (`geth/bin/agent_sandbox.sh`). The driver keeps the network,
because its agents call the model service, and it can still submit scheduler jobs.

| Check | Result |
|---|---|
| `qsub` from inside the container | works (the SGE client is mounted read-only; the ports come from the host's `/etc/services`, which the container does not see) |
| The model service from inside, key only in the environment (`APPTAINERENV_`) | HTTP 200; the key is in no command line and no file |
| What a driver sees | its run folder, Nextflow's home and the image cache (read-write); Geth, its run's data folder, the catalogue, Java, Nextflow (read-only). Hidden: the lab's scoring truth, other runs, other deliveries, the home folder, group storage |
| Lab design (PBMC), driver sandboxed | design check OK, 11/12; its inspection job was submitted from inside |
| Yeast RNA-seq plan, approve, run, all sandboxed | plan 13/13; run succeeded in 1 attempt, the nested nf-core driver submitting its 215 jobs from inside; 42/42 report numbers traced |
| nanoseq (Nextflow 23.10.4, singularity engine) and eager (Nextflow 22.10.8, Java 17), sandboxed | PENDING |

Getting there took four faults, all fixed:
- the site's settings file switched the sandbox off over the environment, so two early "sandboxed" tests
  were not (the run folder now records it, and `geth status` says so)
- `NXF_OPTS` was mangled by apptainer's env-file format (it reads single quotes, not `\` escapes)
- the site's task prelude (`module load`) failed inside: it is a no-op there
- a symbolic link (`/exports/applications`): mounted at its resolved path, the scheduler's client was missing
  from `PATH`

A failed tool once left the designer agent hanging for an hour; agent stages now run under time limits.
Not tested: pulling a pipeline image that is not yet in the cache, from inside the sandbox.

## Not yet tested

- Messy deliveries beyond the test sets: inconsistent file names, missing metadata, several organisms or
  batches.
- Repeatability at scale: one full run per real-size dataset so far, with planner repeats on top.
- Other models, and other sites. The site configuration makes this possible; results are welcome.
- Language-model availability and rate limits under sustained use.

The full development record, phase by phase, is in [history/feasibility.md](history/feasibility.md).
