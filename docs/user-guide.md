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
- **the organism**, and anything unusual: library kit, strandedness, 10x chemistry version, spike-ins

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
- Planning takes a few minutes. Nothing runs on your data yet: the planner only lists files and reads
  text.

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
- **Plan check**: Geth's automatic check of the plan against the pipeline. It should say
  `PLAN CHECK: OK`.

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

**What happens during the run:**

- The **operator agent** launches the pipeline with the approved plan. The pipeline submits its jobs to
  the cluster, or runs them on the machine.
- If the pipeline fails, the operator reads the error, and may change **only what the error points to**,
  for example a parameter the pipeline rejected. It then resumes the run. It can never change your
  samples, their names, the files or the comparisons. Geth refuses such attempts.
- After at most a few attempts, it stops and reports the problem instead of guessing.
- The **reporter agent** writes the report from the pipeline's results.

If the run was interrupted, for example because the machine rebooted, run `geth run my_analysis` again.
It resumes where it stopped.

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
- a CellTypist annotation model from the reference catalogue

Review the thresholds: does the design keep a sensible fraction of your cells? Review also the marker
panel and the annotation model.

During the run, the analyst agent looks at the diagnostics: cells kept, doublet rate, cluster sizes,
markers, and agreement with CellTypist. It may revise the tunable values once, with a written
justification. It then names each cluster from its markers. A cluster where markers and CellTypist
disagree is labelled "uncertain".

The annotation model must match your tissue and species. Available models are listed at
<https://www.celltypist.org/models>; ask for one to be added to the catalogue if needed.

## Managing your analyses

- `geth list` shows every analysis and its state: planned, approved, running, succeeded or failed.
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
| `... changed after approval` | You (or someone) edited a plan file: review it, then `geth approve` again. |
| The run failed | `geth status` lists the attempts. `report.md` explains the failure. The error of each attempt is in `attempt_N/error.txt`, and the pipeline's log in `attempt_N/nextflow.log`. |
| The report says some numbers could not be traced | Check those numbers against the results before using them. |

## Good to know

- Geth **never modifies or deletes your data**. It reads your files and writes only in its own runs folder.
- The agents can read files only inside the data area. They can start only the supported pipelines, at
  their tested versions, and only after your approval.
- Geth uses only the language model(s) your site allows.
