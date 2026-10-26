# Changelog

Releases are tagged on `master` (`vX.Y.Z`). Validation details are in [docs/validation.md](docs/validation.md).

## Unreleased

- **A paid model everywhere.** `--model <name>` (a model the site defines, e.g. sol) now works on `geth run` and
  `geth report` too, and on `geth legion run` with `--budget <USD>`: every agent that command starts (the steps'
  planners, operators and reporters, the lab's agents, the coordinator's reviews and report) uses it, within that
  total. `geth plan` and `geth legion new` take `--budget` (another cap than the site's). Every stage's cost goes to
  `model_spend.txt`, counted even when the stage is stopped; `geth status`, `geth legion show` and `geth lab show`
  say what was spent. When a project's total is spent, it pauses (exit 4) and nothing it stopped counts as failed:
  run it again with a new budget.
- The coordinator knows that the single-cell toolbox analyses one count matrix per run (one sample, or all of a
  step's samples together), and that a lab step starts from the combined matrix with each cell's sample.

## 2.3.1 (2026-10-26)

- **Each analysis records which Geth made it.** Every agent stage adds a line to `geth_version.txt` in its run,
  project or lab folder: the stage, the time, Geth's release and commit, and "with local changes" when the code
  differed from that commit. `geth show` says which Geth planned the run, `geth status` lists every stage,
  `geth legion show` and `geth lab show` give the latest.
- `geth --version` (and `-V`) works like `geth version`, which now also says when the code has local changes.

## 2.3.0 (2026-10-26), a talkative legion; nuclei and chicken

- **`geth legion` says what it is doing.** In a terminal, every agent stage shows its steps as `geth plan` does,
  one line each with the time: the coordinator (reading the delivery, searching nf-core, checking the steps,
  deciding after a step, writing the report), the planner, the operator, the analyst, the reporter and the lab's
  agents, with the checks' verdicts. While a pipeline runs, its line is refreshed every 30 seconds with the tasks
  done, running or queued, and the latest. While the model answers, the clock keeps running, and after two
  minutes the line says how long it has been answering. The project's events and the lab build's rounds carry
  their time. Detached runs stay quiet (their logs have everything). Tested end to end on a yeast project.
- **Single-nucleus RNA-seq.** The plan check refuses a single-nucleus delivery (README: "single-nucleus",
  "snRNA-seq", "nuclei") counted without its intronic reads: STARsolo needs `star_feature=GeneFull`, kallisto
  `kb_workflow=nac`; Cell Ranger counts introns. The scrnaseq skill says so, and asks whether cells or nuclei.
- **Species without a CellTypist model** (chicken): the single-cell design may leave out `annotation.model`; the
  analyst then names clusters from their markers. A model of another species than the cells' (from the upstream
  run's reference) is refused. The toolbox finds the mitochondrial genes of species without the `MT-` prefix
  (`ND1`, `COX1`, `CYTB` ...), which it missed: their QC read 0%.

## 2.2.0 (2026-10-26), readable agents

- **Agents' text is readable in the terminal.** The plan's rationale, the questions, the coordinator's
  rationale and decisions, lab designs and reviews, run outcomes and the agents' messages in the logs are shown
  one sentence per line, wrapped to the terminal (at most 100 columns, `GETH_TEXT_WIDTH`), instead of one long
  line. Lists keep their markers, and tables are left as they are. The files keep the agents' text as written.
- `geth legion show` lists the coordinator's decisions after each step, with their reasons, and the project
  report when there is one.

## 2.1.2 (2026-10-25)

- **The documentation matches the code again.** Projects (`geth legion`) are in the introduction, installation
  and user guide (`--detach`, `--answers`, `--model`, `--overrule`); the configuration page describes how 2.x
  loads its settings, the chosen-model settings (`GETH_MODEL_<NAME>_*`), `GETH_DOWNLOAD_SUBMIT`,
  `GETH_PLANNER_ASK` and the benchmark variables; the developer guide covers the coordinator, the model budget
  and the project benchmarks; validation has the paid-model comparison (planner and lab).
- In the agent sandbox, a model chosen with `--model` that has its own key variable
  (`GETH_MODEL_<NAME>_API_KEY_VAR`) now gets its key: the sandbox read only the 2.0.0 name.
- Fish completion: `geth legion new / approve / run` options, `geth lab judge / build / build-c`, `--model` and
  `--budget`.
- The lab and run stages print their cost to 4 decimals (`model_spend.txt` had rounded it to 10 cents).
- `site.env.example` and the Eddie example use the `GETH_MODEL_SOL_*` names (the 2.0.0 names still work) and
  state the driver slots of 2.x; `geth status` and `geth lab show` say "agents: in the agent sandbox".
- Benchmarks: `bench_plan.sh` reads the chosen model's 2.1 name; the lab design scorer no longer takes a
  minimum number of cells per donor for cells as the unit of replication.

## 2.1.1 (2026-10-25)

- `geth legion run --detach` starts the project: the background run called the command by its old name, and with
  options it does not take (`--yes`, `--answers` and `--overrule` were lost).

## 2.1.0 (2026-10-25), the legion

- **`geth legion new / show / approve / run / list / stop`**: a project, several analyses towards one question. A
  coordinator agent reads the delivery and proposes the steps (pipelines, follow-ups, an Ensembl genome download
  when the catalogue lacks the species, gaps naming the nf-core pipeline that would fill them, and with `--lab`
  the experimental lab); you approve them, and every step's plan, as before. After each step it reads the report
  and continues, stops, or proposes new steps; at the end it writes the project report, number-checked against
  every step. `--overrule` lets you go on when it stops.
- Reference downloads run where the site allows them (`GETH_DOWNLOAD_SUBMIT`; on Eddie the staging queue).
- `geth lab ... --model <name> --budget <USD>`: the lab's agents with a model you choose, within a total.
  The budget is a hard cap: a request that could cross it is not sent.
- The operator can browse the pipeline's options, and may change an option that the error names (e.g. DESeq2's
  `nsub` -> `deseq2_vst_nsub`).
- `stage_ensembl.sh` finds annotations named with Ensembl Genomes' release (yeast).

## 2.0.1 (2026-10-23)

- **`geth run` of a differential expression follow-up works in the agent sandbox.** The run's launch-time plan
  check could not see the count matrix, which lives in the upstream run: only `geth plan --from` mounted it.
  The run and the report now mount the upstream run read-only too. (Found by a 2.1 project test; single-cell
  follow-ups were not affected, their toolbox jobs run outside the sandbox.)

## 2.0.0 (2026-10-23), codename Rannoch

**The agents run on Geth's own harness; Nextflow only runs the pipelines and the tools' jobs.** Geth 1.x's
agents ran on Nextflow's preview `agent` feature; every agent was moved and measured against its Nextflow
version first ([validation](docs/validation.md#geths-own-agent-harness-version-20-rannoch)).

- **The planner asks you** what the delivery does not say (in the terminal, a few questions at a time with a
  recommended answer; or a stand-in answering from `geth plan ... --answers notes.txt`). It browses the
  pipeline's options, measures read lengths, and the plan check compares the plan with the reads (primers,
  10x barcode read length, read length, RRBS motif). `geth show` prints the questions and answers and the
  full command line. Planning is about three times faster.
- **A paid planner model for one plan**, if the site defines it: `geth plan ... --model sol`, within a
  budget the site sets; `geth show` says which model planned and what it cost.
- **Outcomes are checked**: a run's claimed success or failure must match the pipeline's log (the
  single-cell analyst's, the analysis it names).
- **Reports are corrected before they are saved**: numbers that cannot be traced to the results go back to
  the reporter once. In the benchmark, every saved report traced all its numbers (Nextflow version: 10/16).
- The operator runs the approved plan without copying it; a run takes one driver slot instead of two, a plan
  or a report none.
- The single-cell analyst's revisions work: a revision may name only the keys it changes, and list values
  are read as lists (every revision had been refused on format).
- Results summary: MultiQC statistics from `multiqc_data.json` when the text table is missing (chipseq,
  atacseq; MultiQC 1.3x), and peak counts for chipseq and atacseq.
- The lab's agents run on the same harness; their jobs and the arm C full run go through `geth/lab/jobs.nf`.
- **Removed:** `geth/main.nf`, `geth/lab/main.nf` (the Nextflow agents), `GETH_LLM_PROVIDER`, and the
  `GETH_PLANNER` / `GETH_RUNNER` / `GETH_LAB_RUNNER` switches of the 2.0 preview. Runs planned with 1.x can
  be run and reported with 2.0.

## 1.9.3 (2026-10-21)

- **Agent sandbox: shared databases are visible.** A reference catalogue entry may point to a database
  outside the catalogue (on Eddie, the shared Kraken2 database in the shared reference data). The sandbox
  did not mount it, so every sandboxed taxprofiler plan failed the check ("db_path does not exist").
  `GETH_AGENT_SANDBOX_RO` lists such folders; they are mounted read-only. Found by the Rannoch planner
  benchmark.

## 1.9.2 (2026-10-20)

- **`geth report <name>`:** the reporter writes the report of a finished run again from its results, in
  about a minute, without launching the pipeline. The previous report is kept as `report.<date>.md`.
- **Resume no longer redoes Cell Ranger multi:** each attempt copied the barcodes sheet to a new path, and
  Nextflow's cache knows input files by path, so `geth run` on a finished multiplexed run redid Cell Ranger
  (about 10 hours on the user's data). Attempts now launch with an earlier attempt's identical sheets.
- `geth status` shows the running attempt as running (it said "launched: failed").
- The report warns not to use `combined_cellbender_filter_matrix.h5ad` with multiplexed libraries.

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
