# User guide

This guide takes you from a folder of sequencing files to a report, step by step. You need no
bioinformatics knowledge for the commands. You do need to know your experiment: which samples, which
conditions, what you want to compare.

**In short:**

```bash
geth plan /path/to/my_data "What I want to know" my_analysis   # Geth proposes a plan
geth show my_analysis                                          # you read it
geth approve my_analysis                                       # you agree to it
geth run my_analysis --detach                                  # Geth runs it
geth status my_analysis                                        # where it is; the report when done
```

## Before you start

- Geth must be installed and configured for your site. Run `geth doctor`: the last line should say
  `Geth is ready.` If it does not, see [installation](installation.md) or ask whoever installed Geth.
- If the `geth` command is not found, load Geth first: `source /path/to/Geth/env.sh`. Add that line to your
  `~/.bashrc` to have it every time. With fish: `source /path/to/Geth/env.fish` (it also gives tab
  completion of commands and run names).
- Geth can only read data inside its data area. To see where that is: `echo $GETH_DATA_ROOT`.

## Step 1: prepare the data folder

Put your files in one folder inside `$GETH_DATA_ROOT`, as you received them from the sequencing
facility. You don't need to rename anything. Then add a short text file, for example `README.txt` or
`samples.tsv`, that describes the experiment. **The planner reads every text file in the folder**, and a
good description gives a good plan.

Say, in plain words:

- **what the samples are**: conditions, treatments, time points, genotypes
- **replicates**: which samples are biological replicates, and which files are the same library
  sequenced twice (technical replicates or lanes)
- **pairing or batches**: e.g. "each donor gave one treated and one untreated sample"
- **the organism**, and anything unusual: library kit, strandedness, 10x chemistry version (e.g. GEM-X
  3' v4, Next GEM 3' v3.1), spike-ins
- **single-nucleus libraries**: say "single-nucleus" (or snRNA-seq) if the libraries hold nuclei rather
  than whole cells: their intronic reads must be counted
- **multiplexed single-cell libraries**: if several samples share one 10x library (On-Chip Multiplexing,
  CellPlex, Flex), say so, and give the table of which barcode (OB1, CMO301, BC001, ...) is which sample

Example folder:

```
my_data/
├── README.txt
└── fastq/
    ├── ctrl_1_S1_L001_R1_001.fastq.gz
    ├── ctrl_1_S1_L001_R2_001.fastq.gz
    ├── ...
    └── treat_3_S6_L002_R2_001.fastq.gz
```

and `README.txt`:

```
Human airway smooth muscle cells, untreated (ctrl) or treated with dexamethasone (treat) for 18 h.
Three donors: samples 1, 2 and 3 of each condition come from donors A, B and C.
Paired-end Illumina, TruSeq stranded mRNA. Each sample was sequenced on two lanes (L001, L002).
```

**Reference genome.** If the folder has no reference, the planner uses the reference catalogue. To see
which species and assemblies are available, run `ls $GETH_REFERENCES`. If yours is missing, ask whoever
installed Geth: one command adds it (see [installation](installation.md#6-fill-the-reference-catalogue)).
You can also put your own FASTA and GTF in the data folder and mention them in the README.

## Step 2: ask for a plan

```bash
geth plan /path/to/my_data \
    "Quantify gene expression so that we can compare treated and untreated cells." my_analysis
```

- The **question** says what you want, in your own words. Mention the comparison you care about and
  anything the folder does not say.
- The **name** (`my_analysis`) identifies this analysis from now on. Use letters, digits, `.`, `_` and
  `-`. Each analysis gets its own folder: `$GETH_RUNS_DIR/my_analysis`.
- Planning takes a few minutes. Nothing runs on your data yet: the planner only lists files, reads text and
  measures the reads.
- The planner **asks you what your files do not say**: for example the primers, which control goes with
  which sample, or whether a single-cell library holds several samples. In a terminal, it asks a few
  questions at a time. Each has numbered options and a recommended answer: press Enter to take it, type a
  number to pick an option, type your own answer, or `?` to see why it asks.
- For planning in the background, write what you know in a text file and add `--answers notes.txt`: a
  stand-in answers the planner from your notes, and says "I don't know" for anything they do not cover.
- Where the reads can tell, Geth checks your answers and the plan against them and warns about a mismatch:
  amplicon primers that do not start the reads, a 10x chemistry that does not match the barcode read length
  (v2: 26 bp; v3 and GEM-X v4: 28 bp), a read length that does not match the reads, an RRBS motif.
- For a poorly documented delivery, a stronger (paid) planner model can be switched on for one plan, if your
  site defines it: `geth plan ... --model sol`. It plans within a cost cap set by the site (Sol: usually about
  5 cents a plan, at most 50 cents), and `geth show` says which model planned and what it cost. Without
  `--model`, the site's free model plans.
- If Geth prints `Waiting for a free slot: 2 Nextflow driver(s) running ...`, other analyses are using the
  machine's share (your site sets how many may run at once, `GETH_MAX_DRIVERS`). Geth starts by itself as soon
  as one finishes; you can leave it waiting.

When it is done, Geth prints the plan, which is also what step 3 shows.

## Step 3: review the plan

```bash
geth show my_analysis
```

You will see:

- **Pipeline**: the nf-core pipeline chosen, for example `nf-core/rnaseq`.
- **Rationale**: why the planner set things up this way: how files were grouped into samples, files
  left out on purpose, and why each parameter is set.
- **Samplesheet**: one row per file (or pair of files) with its sample name.
- **Parameters**: pipeline settings, such as the reference genome and annotation, or the aligner.
- **Multiplexed samples** (single-cell only, when several samples share one library): which sample each
  barcode of a library holds.
- **Questions and answers**: what the planner asked you, and what you (or the stand-in) answered.
- **Command line Geth will run**: the full nf-core command, as it will be launched.
- **Plan check**: Geth's automatic check of the plan against the pipeline. It should say
  `PLAN CHECK: OK`. It may add `WARNING:` lines: things to check before you approve, for example samples
  listed in your README that appear nowhere in the plan, or a 10x chemistry the delivery does not state.

**What to check.** This is the moment where your knowledge of the experiment matters:

- [ ] The pipeline fits your data, e.g. bulk vs single-cell.
- [ ] Every sample is there, with a sensible name.
- [ ] Files that belong together are under the same sample name: lanes, or a library sequenced twice.
      Separate biological samples have different names.
- [ ] Files left out are left out on purpose, and the rationale says why.
- [ ] The reference genome and annotation match your organism.
- [ ] Nothing in the parameters surprises you.

**To change something,** edit the plan files in the run folder with any text editor, then run
`geth show` again to re-check:

| File | Holds |
|---|---|
| `plan_samplesheet.csv` | the samplesheet (or, for differential expression, the samples and their conditions) |
| `plan_params.json` | the parameters |
| `plan_contrasts.csv` | differential expression only: the comparisons |
| `plan_barcodes.csv` | multiplexed single-cell only: the samples of each library and their barcodes |

To start again instead, improve the README or the question, and plan under a new name.

## Step 4: approve

```bash
geth approve my_analysis
```

Geth shows the plan once more, checks it, and asks you to confirm. It refuses a plan that fails the
check. Approval records your user name and a fingerprint of every plan file. If you edit a plan file
afterwards, Geth notices and asks for a new approval.

## Step 5: run

```bash
geth run my_analysis --detach
```

`--detach` keeps the analysis running after you log out. Use it for anything but tiny test data. Real
analyses take from minutes to hours.

Follow the progress with:

```bash
geth status my_analysis      # outcome, attempts, report check
geth list                    # all your analyses and where they stand
```

`geth status` also says whether the agents ran in their sandbox (`agents: in the agent sandbox`), on
sites that use one.

**What happens during the run:**

- The **operator agent** launches the pipeline with the approved plan. The pipeline submits its jobs to
  the cluster, or runs them on the machine.
- If the pipeline fails, the operator reads the error, and may change **only what the error points to**,
  for example a parameter the pipeline rejected. It then resumes the run. It can never change your
  samples, their names, the files or the comparisons. Geth refuses such attempts.
- After at most a few attempts, it stops and reports the problem instead of guessing. Geth checks its
  outcome against the pipeline's own log: a run claimed to have succeeded (or failed) when the log says
  otherwise is refused.
- The **reporter agent** writes the report from the pipeline's results. Every number in it is checked
  against the results; numbers that cannot be traced go back to the reporter once, to correct, before the
  report is saved.
- In a terminal (without `--detach`), Geth shows what each agent does, one line per step, with the time.
  While the pipeline runs, its line is refreshed every 30 seconds with the tasks done, running or queued,
  and the latest one, for example:
  ```
    [0:42] operator: Running nf-core/rnaseq as approved … 87 tasks done, 12 running or queued; latest: STAR_ALIGN (N61311_Dex)
  ```
  The details are in `$GETH_RUNS_DIR/my_analysis/geth_run.log`.

If the run was interrupted, for example because the machine rebooted, run `geth run my_analysis` again.
It resumes where it stopped.

**To stop** a planning or a run yourself:

```bash
geth stop my_analysis
```

It stops the agents and the pipeline, and deletes the run's jobs on the cluster. It takes up to two
minutes, while the pipeline cancels its jobs. The work done so far is kept: `geth run my_analysis` resumes
the run later.

**To write the report again** (for example after a Geth update that summarises the results better), without
running the pipeline again:

```bash
geth report my_analysis
```

It takes a minute or two. The previous report is kept next to it, as `report.<date>.md`.

Each stage has a time limit, so a stuck agent cannot hold the machine forever: 2 hours for planning, 72 hours
for a run, by default. If a stage hits its limit, Geth says so; your site can raise the limits.

Typical times on a cluster, from approval to report:

| Analysis | Time |
|---|---|
| Bulk RNA-seq, 8 human samples, 24 GB of reads | about 2 hours |
| Single-cell RNA-seq, about 1,000 cells, 10x v3 | about 1 hour, including about 25 minutes to build the genome index |
| Differential expression on a finished RNA-seq run | about 15 minutes |
| Single-cell clustering and cell types | about 5 minutes |

## Step 6: read the results

Everything about the analysis is in its run folder, `$GETH_RUNS_DIR/my_analysis`:

| File or folder | What it is |
|---|---|
| `report.md` | The report: summary, samples, quality control, results, caveats and next steps. |
| `report_check.txt` | How many of the report's numbers were traced to the results, e.g. `64/64`. If some could not be traced, the report ends with a warning that lists them. |
| `results/` | The pipeline's own outputs: counts, plots, the MultiQC report (`results/multiqc/.../multiqc_report.html`), and so on. |
| `outcome.txt` | Whether the run succeeded, how many attempts it took, and any change made to the plan. |
| `plan_*` | The approved plan. |

The report is a summary written by a language model and then checked. It is not a substitute for looking
at the QC report and the results yourself.

## Follow-up analyses

A finished analysis can be the input of the next one: use `--from <analysis name>` instead of a data
folder.

### Differential expression, after bulk RNA-seq

```bash
geth plan --from my_analysis \
    "Which genes change with the dexamethasone treatment? Samples are paired by donor." my_analysis_de
```

The planner reads the first analysis (its plan and results) and proposes:

- an **observations sheet**: each sample with its condition, plus donor or batch if relevant
- **contrasts**: what is compared with what
- an analysis type: DESeq2 by default, optionally with gene-set analyses

When you review, check two things above all:

- **The direction of each contrast.** `reference` is the baseline (e.g. untreated) and `target` is the
  condition compared with it (e.g. treated). A positive log2 fold change means higher in the target.
- **Blocking.** For a paired design, e.g. the same donors in both conditions, the `blocking` column
  names the pairing variable.

### Cell filtering, clustering and cell types, after single-cell RNA-seq

```bash
geth plan --from my_pbmc \
    "Filter low-quality cells and doublets, cluster the cells and identify the cell types with their marker genes." my_pbmc_cells
```

The planner first measures your cells: counts, genes and mitochondrial fraction per cell. It then
proposes an **analysis design** from a fixed menu:

- quality-control thresholds
- doublet detection
- normalisation and clustering resolutions
- a panel of marker genes to display
- a CellTypist annotation model from the reference catalogue, if one fits your species and tissue

Review the thresholds: does the design keep a sensible fraction of your cells? Review also the marker
panel and the annotation model.

During the run, the analyst agent looks at the diagnostics: cells kept, doublet rate, cluster sizes,
markers, and agreement with CellTypist. It may revise the tunable values once, with a written
justification. It then names each cluster from its markers. A cluster where markers and CellTypist
disagree is labelled "uncertain".

The annotation model must match your tissue and species. Available models are listed at
<https://www.celltypist.org/models>; ask for one to be added to the catalogue if needed. CellTypist covers
human and mouse only: for another species (chicken, for example) the design has no model, and the clusters are
named from their markers alone. Give your known markers in the README or the question, so that the planner
puts them in the marker panel.

## The legion: several analyses towards one question

When a question needs more than one analysis, ask the legion for a **project**. The coordinator agent reads the
delivery and proposes the steps; each step is then done by the usual agents, and you approve as usual.

```bash
geth legion new /path/to/my_data "Which genes differ between the mutant and the wild type?" my_project
geth legion show my_project        # the steps and the coordinator's rationale
geth legion approve my_project
geth legion run my_project         # stops whenever a step's plan needs you
```

A step is one of:

- **a pipeline** on part of the delivery (a delivery may hold several kinds of data, e.g. RNA-seq and
  ATAC-seq: one step each);
- **a follow-up** on a finished step: differential expression after RNA-seq, cell types after single-cell;
- **a reference download**, when the catalogue has no genome for your species: the genome and annotation of
  the current Ensembl release, checked against Ensembl before you approve (`geth legion show` gives the
  download size), then downloaded as a job and added to the catalogue;
- **a gap**: something the question needs that no Geth pipeline does. The coordinator says what it is, which
  nf-core pipeline would do it if one exists (for example nf-core/smrnaseq for microRNAs), and what the
  finished steps hand over to it. Nothing is improvised.

In a terminal, `geth legion run` shows each event of the project with its time, and every agent at work: the
planner, the operator (with the pipeline's progress), the reporter and the coordinator. It plans the next step and
stops: `geth show my_project-<step>`, `geth approve
my_project-<step>`, then `geth legion run my_project` again. After each step the coordinator reads its report
and continues, stops, or proposes new steps, which you approve before anything runs. When every step is done,
it writes `report.md` in the project folder (`$GETH_RUNS_DIR/projects/my_project`): the answer to your
question from the steps' reports, every number checked against the steps' results. `geth legion list` shows
all projects; `geth legion stop my_project` stops the project and its running step.

Good to know about projects:

- `geth legion run my_project --detach` runs it in the background; follow it with `geth legion show my_project`
  (the log is `log.md` in the project folder).
- `--answers notes.txt` (with `new` and `run`) lets a stand-in answer the agents' questions from your notes, as
  in [step 2](#step-2-ask-for-a-plan); `geth legion new ... --model sol` uses a paid coordinator model, if your
  site defines one.
- If the coordinator stops the project (for example because a step's data look too thin) and you disagree,
  `geth legion run my_project --overrule` goes on with the approved steps. Your name is recorded in the log.

**The lab, on request.** With `geth legion new ... --lab`, a gap on a count matrix (`.h5ad`, from a
single-cell step or delivered) may become a **lab step**: lab agents design the analysis, you approve the design
(`geth lab show my_project-<step>-design`, then `geth legion approve my_project --lab <step>`), and they write,
test and run the code in a sandbox. This is EXPERIMENTAL: the results come from agent-written code, and the
report says so. Without `--lab`, such a step stays a gap.

## Managing your analyses

- `geth list` shows every analysis and its state: planned, approved, running, succeeded or failed.
- `geth stop my_analysis` stops a planning or a run (see [step 5](#step-5-run)).
- `geth report my_analysis` writes the report of a finished run again, from its results.
- `geth version` (or `geth --version`) prints the version of Geth you are using, with its commit: worth
  quoting when you report a problem. Each analysis also keeps the version that planned, ran and reported it
  (`geth_version.txt` in its folder): `geth show` says which Geth planned it, and `geth status` lists them all.
  "with local changes" means the code differed from that commit.
- **To change an analysis that already ran,** plan again under a new name. That keeps the history of
  what was run clear.
- **Disk space.** The `work/` folder inside a run holds the pipeline's intermediate files. It is large:
  tens of GB for a human dataset. Once you are happy with the results, you can delete it
  (`rm -r $GETH_RUNS_DIR/my_analysis/work`), along with `geth_work/`. The results and the report stay.
  Without `work/`, the run cannot be resumed.

## When something goes wrong

| You see | What to do |
|---|---|
| `geth: command not found` | `source /path/to/Geth/env.sh` (fish: `env.fish`) |
| `Agents can only read data under GETH_DATA_ROOT` | Move the data folder inside `$GETH_DATA_ROOT`. |
| `Planning failed: see .../geth_plan.log` | Often the model endpoint: run `geth doctor`. Otherwise look at the end of the log. |
| The plan check lists problems | Fix the plan files (the message says what is wrong), or plan again with a clearer README or question. |
| `the delivery describes multiplexed 10x libraries` | Several samples share each library: plan again, saying so in the question, or fix the plan as the message says (Cell Ranger multi and a `plan_barcodes.csv`). |
| `WARNING: ...` under the plan check | Not an error: check what it points to before approving. |
| The run is stuck, or you started the wrong one | `geth stop my_analysis` |
| `... changed after approval` | You (or someone) edited a plan file: review it, then `geth approve` again. |
| The run failed | `geth status` lists the attempts. `report.md` explains the failure. The error of each attempt is in `attempt_N/error.txt`, and the pipeline's log in `attempt_N/nextflow.log`. |
| The report says some numbers could not be traced | Check those numbers against the results before using them. |
| `Waiting for a free slot ...` | Other analyses are running; Geth starts by itself when one finishes. |
| `... stopped after its time limit ...` | The stage ran longer than your site allows. If it was making progress, ask for a higher limit, then run the same command again: a run resumes. |

## Good to know

- Geth **never modifies or deletes your data**. It reads your files and writes only in its own runs folder.
- The agents can read files only inside the data area. They can start only the supported pipelines, at
  their tested versions, and only after your approval.
- On sites that contain them (Eddie does), the agents run in a container that sees only your analysis, its
  data and the reference catalogue, and can write only in the analysis folder.
- Geth uses only the language model(s) your site allows.
