# Changelog

Releases are tagged on `master` (`vX.Y.Z`). Validation details are in [docs/validation.md](docs/validation.md).

## 1.6.0 (unreleased)

- **Planner benchmark on realistic deliveries** for isoseq, ampliseq, chipseq, atacseq, methylseq, nanoseq
  and eager (`bench/stage_deliveries.sh`, `bench/bench_plan.sh`, `bench/bench_run.sh`): 3/3 plans fully
  correct for every pipeline after one round of fixes.
- **New plan checks:**
  - ATAC-seq `mito_name` must be a contig of the reference FASTA, and is required when a mitochondrial
    contig exists
  - ampliseq metadata IDs must be the sample names
  - Nanopore barcode kits must use qcat's names
- **Clearer skills:** ChIP-seq (`sample` is the condition), Nanopore (kit names, groups), ampliseq
  (metadata), ATAC-seq (mitochondrial contig).
- **STAR index reuse:**
  - `geth/references/register_star_index.sh` registers a built index in the reference catalogue
  - the rnaseq and scrnaseq skills reuse it
  - the plan check refuses an index whose STAR version, FASTA or GTF does not match the plan
- The run scorer handles every pipeline.
- **Full agent runs of the seven new pipelines**, all succeeding after these fixes:
  - samplesheets keep every column
  - `skip_<step>` is accepted when the error names the step
  - parameters that describe the data are frozen
  - no analysis profile for upstream pipelines
  - a third identical launch is refused
  - ampliseq's `config_profile_name` is set by Geth
  - nanoseq DNA and isoseq chunking checks
  - the report check counts numbers from error reports
- **Resource caps** depend on the reference and database size too. A small input on a human genome gets
  full-size jobs.
- **nf-core/sarek for livestock germline calling** (chicken):
  - `geth/references/stage_ensembl_variation.sh` stages known variants, the VEP cache and an uncompressed
    FASTA
  - checks for VEP caches, known sites and FASTA compression
- **Metagenomics:**
  - `geth/references/register_database.sh` registers shared Kraken2 and MetaPhlAn databases without
    copying them
  - taxprofiler database checks, and Kraken2 memory sized to its index
  - mag refuses GTDB-Tk and CAT downloads
- **Full runs of chicken (sarek), taxprofiler and mag**, fixed after their first runs failed:
  - the gate accepts skipping a 3-letter step the error names (ALE), adding a tool the error names to
    `skip_tools`, and changing a file parameter whose file the error names
  - the error digest catches nf-core's own `ERROR:` lines
  - sarek refuses the same VCF as both `dbsnp` and `known_indels`
  - taxprofiler requires read pairs to be merged when run merging mixes single-end and paired-end runs
  - mag skips ALE on test-size data
- **Geth lab (experimental):** `geth lab design`, `show` and `list` for agent-designed single-cell analyses
  (phase 11, arm A), on benchmark data only. `geth list` shows real runs only and points to `geth lab list`.
- `bench/snapshot.sh` runs benchmarks on a frozen commit.

## 1.5.0 (2026-10-17)

- **One site configuration file** (`site/site.env`, from `site/site.env.example`): folders, language
  model, Nextflow config for Geth's own tasks, nf-core profile, GPU, Java 17, image cache. The code holds no
  site-specific values. Examples for a single machine and for an SGE cluster.
- `geth doctor` (installation and endpoint checks), `geth list`, `geth version`.
- Documentation for users and developers in `docs/`; generic README; GPL-3.0 licence.
- Results summary for every pipeline. Before, nanoseq and eager reports crashed, and other pipelines got an
  irrelevant summary.
- Self-contained unit tests; `geth/references/stage_celltypist.sh`; `bench/baseline_airway_de.sh`.

## 1.4.0 (2026-10-17)

- Skills, pinned schemas and plan checks for 10 more nf-core pipelines: sarek, isoseq, taxprofiler, mag,
  ampliseq, chipseq, atacseq, nanoseq, eager, methylseq.
- Per-pipeline runtime: legacy config parser, Nextflow 23.10.4 (nanoseq), Nextflow 22.10.8 + Java 17 and a
  TSV samplesheet (eager), singularity engine. Seven pipelines pass their own test profiles; sarek,
  taxprofiler and mag wait for their databases.

## 1.3.1 (2026-10-17)

- The single-cell toolbox scripts are tracked as executable.

## 1.3.0 (2026-10-17)

- CellBender on a GPU (nf-core `gpu` profile plus GPU routing for SGE).
- Agent-designed single-cell downstream analyses:
  - a Scanpy and CellTypist toolbox with a fixed design menu
  - an analyst agent allowed one justified revision, and diagnostic flags
  - cluster annotations saved through a tool
- Validated on PBMC 1k v3: 7/7 expected populations in 3/3 designs.

## 1.2.0 (2026-10-16)

- Follow-up analyses (`geth plan --from`): differential expression with nf-core/differentialabundance.
  On airway, the result is identical to a hand-made baseline: 650 DE genes, and 7/7 known dexamethasone
  genes up.

## 1.1.0 (2026-10-16)

- Plans handed over as lists (the structured output mangled JSON in text fields), with the last checked
  plan kept as a fallback.
- Reference catalogue; resources chosen by input size.
- Validated on real-size public data: airway (bulk RNA-seq) and PBMC 1k v3 (single-cell).

## 1.0.0 (2026-10-16)

- Plan, approve, run: a planner, an operator and a reporter agent.
- Plan check against the pinned schemas, approval with file fingerprints, the plan-diff gate, the report
  number check.

## 0.1.0 (2026-10-16)

- Feasibility spikes: the language-model endpoint, Nextflow agents calling cluster jobs, agentic nf-core
  runs. Verdict: go.
