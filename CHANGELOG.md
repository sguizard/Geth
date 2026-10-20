# Changelog

Releases are tagged on `master` (`vX.Y.Z`). Validation details are in [docs/validation.md](docs/validation.md).

## 1.9.1 (2026-10-20)

From comparing the user's rerun of their multiplexed delivery with their own analysis
([validation](docs/validation.md#multiplexed-single-cell-libraries-version-19)).

- **CellBender in the report:** every CellBender run (expected and kept cells, counts removed). For Cell
  Ranger multi, the library runs are split by sample (these match the user's own analysis to within 1%),
  and the report says the per-sample runs are not valid (a sample's raw matrix lacks the library's empty
  droplets).
- The plan check refuses a sample's own CellBender matrix as input of a single-cell follow-up; the
  skills say which matrices to use with multiplexed libraries.
- Report check: both ends of a range are checked ("990-1,218" was read as 990 and 218); dates are ignored.
- Plan warning about missing samples: whole names only (a short name could match inside a file path).

## 1.9.0 (2026-10-19)

From the first real-data analysis run by a user alone: a 10x On-Chip Multiplexing delivery that Geth
planned as plain 10x ([validation](docs/validation.md#multiplexed-single-cell-libraries-version-19)).

- **Multiplexed single-cell libraries** (OCM, CellPlex, Flex): the plan check reads the delivery's README,
  tables and facility report. If they show multiplexing, it refuses a plan that does not use Cell Ranger
  multi with a barcodes sheet (`plan_barcodes.csv`, shown by `geth show`). The sheet is checked and frozen
  at approval like the samplesheet. The scrnaseq skill has a section on them. Validated on a rat OCM test
  delivery: plans 13/13, 13/13, 12/13; full run succeeded, four samples split; 72/75 report numbers traced.
- **Plan warnings** (they never block a plan): samples listed in the delivery that appear nowhere in the
  plan; a 10x chemistry the delivery never states; GEM-X data planned as v3. The skill no longer assumes
  v3.
- **`geth stop <name>` and `geth lab stop <name>`:** stop a planning or a run, its Nextflow drivers and its
  cluster jobs. `geth run` resumes; an attempt ended this way does not count towards the limit.
- **Cell Ranger multi on Eddie:** a pipeline's own `beforeScript` for a process no longer drops the site's
  (`module load apptainer`); Geth puts it back at launch, for every pipeline.
- Reports summarise Cell Ranger multi: per sample, per library, and the cells of each barcode.

## 1.8.0 (2026-10-18)

- **Phase 11 closed** ([validation](docs/validation.md)). With skills, Qwen 3.5 designs coherent single-cell
  analyses and builds them correctly, as Python steps or as a Nextflow pipeline: 14 of 15 builds
  deliverable, as long as a reviewer agent checks them. The lab stays experimental.
  - **One agent or a team:** a lone engineer would have shipped 6 of 12 builds correct; with a reviewer,
    11 of 12 were deliverable and the last was refused.
  - **A crowd:** three designs and a judge match the best design but never beat it (`geth lab judge`,
    `bench/lab/bench_judge.sh`).
- **`geth doctor` checks the agent sandbox:** it starts a probe sandbox and checks Java, Nextflow, the
  scheduler and the key inside it, and that other runs are hidden.
- A stage stopped by its time limit says so, with the setting to raise.
- **Documentation brought up to date with the code**, with a "where to start reading" path in the developer
  guide.

## 1.7.0 (2026-10-18)

- **Agents in a container (phase 12):** with `GETH_AGENT_SANDBOX=yes`, every agent driver runs in apptainer on
  the submit host (`geth/bin/agent_sandbox.sh`).
  - It keeps the network and can still submit jobs.
  - It sees only its run folder, Nextflow's home and the image cache (read-write), plus Geth, its run's data
    and the catalogue (read-only).
  - The API key reaches the agents through the environment only.
  - Validated with rnaseq, nanoseq and eager full runs and a lab design; on by default in the Eddie example.
  - `geth status` and `geth lab show` say whether the agents were sandboxed.
- **Time limits for agent stages:** `GETH_AGENT_TIMEOUT`, `GETH_ENGINEER_TIMEOUT`, `GETH_RUN_TIMEOUT`.
- **Geth lab, arm C (experimental):** `geth lab build-c`. Agents write the whole Nextflow pipeline; its driver
  runs only in the sandbox, as one job with no network. 6 of 6 builds were deliverable once the image held
  what the designs need ([validation](docs/validation.md)).
- **Lab image:** now with scikit-image (Scrublet's automatic threshold) and scikit-misc (seurat_v3). Image
  paths are set once in `env.sh` (`GETH_LAB_IMAGE`, `GETH_AGENT_IMAGE`).
- **Lab reviews:** every review submission is kept (`review_<n>_history.txt`).

## 1.6.0 (2026-10-18)

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
- **Geth lab, arm B (experimental):** `geth lab build` has an engineer agent write a checked design as Python
  steps, tested on a subset in a sandbox (no network, no host files, no keys), and a reviewer agent check them;
  Geth then runs the steps on the full data from a pipeline it renders itself. With the coding skill, 8 of 9
  builds were deliverable and matched a hand-written reference; without it, 2 of 6
  ([validation](docs/validation.md)).
- `bench/snapshot.sh` runs benchmarks on a frozen commit.
- **fish support:** `source env.fish` gives fish the same environment as `env.sh` (it imports what
  `env.sh` exports), with tab completion of commands, run names, lab runs and options.

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
