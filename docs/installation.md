# Installation

Installing Geth means three things: cloning the repository, installing Nextflow, and describing your site
in **one file**, `site/site.env`. That file covers where data and results live, which language model to
use, and how jobs run. This page walks through it. Every setting is described in
[configuration](configuration.md).

If someone in your team already installed Geth, you only need step 5 and the [user guide](user-guide.md).

## Requirements

| What | Version | Notes |
|---|---|---|
| Linux with bash | | Developed on Rocky/RHEL 9. macOS is untested. |
| Java | 17 or later | Tested with 21. Needed by Nextflow. |
| Nextflow | 26.10.2 | Any recent launcher works: Geth pins the version it runs (`NXF_VER`), for its own jobs (written with typed processes) and for each nf-core pipeline. |
| Container engine | apptainer or singularity | Tested with apptainer 1.4.4. nf-core pipelines also run with docker or podman, but Geth's single-cell toolbox needs apptainer or singularity. |
| Python | 3.9 or later | Standard library only. |
| git | | To clone Geth. |
| A language model | OpenAI-compatible API | The model must handle tool calls. Validated with Qwen3.5-397B-A17B; GPT-6 models work through the Responses API. |
| Internet access | from the machine that runs `geth` | For nf-core pipelines (GitHub), containers and the model endpoint. |
| Disk space | tens of GB per analysis | About 35 GB for a human bulk RNA-seq analysis of 8 samples while it runs. The `work/` folder can be deleted afterwards. |

Optional:

- **A job scheduler** (SGE, Slurm, PBS, LSF, ...). Geth runs fine on a single machine, but real-size
  analyses need a cluster. If your institution has a profile in
  [nf-core/configs](https://github.com/nf-core/configs), use it: it already describes your scheduler and
  container setup.
- **A GPU** for CellBender (ambient RNA removal in single-cell RNA-seq). Without one, CellBender runs on
  CPUs, more slowly.

**Where Geth runs on a cluster.** The `geth` command runs its agents (small Python processes) and starts
Nextflow drivers, which submit jobs. Run Geth on a machine that can submit jobs, often a login node or an
interactive session. Each driver is limited to 2 CPUs (`GETH_DRIVER_CPUS`); during an nf-core run, one driver
runs: the pipeline's. All heavy work goes to the scheduler.

## 1. Get Geth

```bash
git clone https://github.com/sguizard/Geth.git
cd Geth
```

## 2. Install Nextflow

```bash
curl -s https://get.nextflow.io | bash      # creates ./nextflow
mkdir -p ~/bin && mv nextflow ~/bin/        # any folder on your PATH
```

Geth sets `NXF_VER=26.10.2`, so Nextflow downloads that exact version on first use (for Geth's own jobs;
each nf-core pipeline gets the version it needs).

## 3. Give Geth access to a language model

Geth talks to any **OpenAI-compatible** chat endpoint, for example:

- a university or company gateway
- a local [vLLM](https://docs.vllm.ai) server
- a commercial provider

The API key is never written in a file inside Geth. Export it in your shell profile (`~/.bashrc`):

```bash
export GETH_LLM_API_KEY=...        # or any variable name; see GETH_LLM_API_KEY_VAR
```

Use a strong model. Geth's agents plan whole analyses, and the validation results are for
**Qwen3.5-397B-A17B**. Geth refuses to start with any model that is not in `GETH_LLM_ALLOWED_MODELS`. If
your key could also reach paid models, the allowlist keeps Geth on the ones you chose.

A site may also offer a stronger, paid model for one command at a time (`geth plan --model sol`,
`geth legion new --model sol`, `geth lab ... --model sol --budget 0.50`). Each such model is defined in the
site file with its prices and a budget, and Geth never sends a request that could cross the budget
([configuration](configuration.md#language-model)).

## 4. Describe your site

Copy the template, or the example closest to your setup, to `site/site.env`. This file is not committed
to git.

```bash
cp site/site.env.example site/site.env                  # documented template
# or
cp site/examples/local.env site/site.env                # one machine, no scheduler, apptainer
cp site/examples/eddie.env site/site.env                # SGE cluster with an nf-core institutional profile and GPUs
```

Then edit it. You need to make four decisions:

1. **Where Geth keeps its files.** `GETH_WORK_ROOT` holds the runs, the reference catalogue and the
   Nextflow cache, and by default the data. Agents can only list and read files under `GETH_DATA_ROOT`,
   which defaults to `GETH_WORK_ROOT`. Put your data folders there, or point `GETH_DATA_ROOT` at the
   folder that holds them.
2. **Which model.** Set `GETH_LLM_BASE_URL`, `GETH_LLM_MODEL` and `GETH_LLM_ALLOWED_MODELS`, and set
   `GETH_LLM_API_KEY_VAR` if your key is in another variable.
3. **How jobs run.**
   - `GETH_NF_CONFIG` is a Nextflow config for Geth's own jobs: the single-cell toolbox's steps and the
     lab's tests.
   - `GETH_NFCORE_PROFILE` is the profile given to every nf-core pipeline: your nf-core institutional
     profile, or simply `apptainer`, `singularity` or `docker`.
   - On a cluster, the simplest config for Geth's own jobs includes your institutional profile, like
     `site/examples/eddie.config` does.
4. **GPU.** Set `GETH_GPU=yes` if CellBender can use a GPU. On SGE you also need a small config that sends
   GPU tasks to the right queue (example: `site/examples/eddie-gpu.config`).
5. **Genome downloads in projects.** `geth legion` can download a missing genome from Ensembl. On a cluster
   where downloads must run on a transfer queue, set `GETH_DOWNLOAD_SUBMIT` to the command that submits
   one and waits for it (see [configuration](configuration.md#nextflow-and-jobs)).

[Configuration](configuration.md) explains each setting and gives a Slurm example.

## 5. Load Geth in your shell

```bash
source /path/to/Geth/env.sh
```

Add this line to your `~/.bashrc` to make the `geth` command available in every shell. `env.sh` loads
`site/site.env`. To use another site file, set `GETH_SITE_ENV=/path/to/other.env` before sourcing it.

With fish, source `env.fish` instead (add it to `~/.config/fish/config.fish`):

```fish
source /path/to/Geth/env.fish
```

`env.fish` runs `env.sh` in bash and copies the result into fish, so the site file stays a bash file and
both shells get the same settings. It also loads tab completion for `geth`: commands, run names (with
their pipeline), projects, lab runs (with their arm), and options such as `--from`, `--answers`, `--yes`,
`--detach`, `--model` and `--lab`.

## 6. Fill the reference catalogue

The reference catalogue is a folder of reference genomes, annotations and annotation models. The planner
uses it when a delivery has no reference of its own. Each entry is a folder with a `README.txt` that the
planner reads. Two scripts add entries. They download, so on a cluster run them where downloads are
allowed:

```bash
# A genome and its annotation from Ensembl (primary assembly when available), checksums verified:
geth/references/stage_ensembl.sh homo_sapiens GRCh38 116 "Homo sapiens (human)"
geth/references/stage_ensembl.sh mus_musculus GRCm39 116 "Mus musculus (mouse)"

# CellTypist models for single-cell cell-type annotation (https://www.celltypist.org/models):
geth/references/stage_celltypist.sh celltypist_immune_v2 "Homo sapiens (human)" "human immune cells" \
    Immune_All_Low Immune_All_High
```

For DNA variant calling with nf-core/sarek on any Ensembl species, add the species' known variants and VEP
annotation cache to its genome entry. This also writes the uncompressed FASTA that sarek needs:

```bash
geth/references/stage_ensembl.sh gallus_gallus bGalGal1.mat.broiler.GRCg7b 116 "Gallus gallus (chicken)"
geth/references/stage_ensembl_variation.sh gallus_gallus bGalGal1.mat.broiler.GRCg7b 116
```

For metagenomic profiling (nf-core/taxprofiler), register the databases you already have. Nothing is copied:
the catalogue entry points to the folder and holds a ready-made databases sheet:

```bash
geth/references/register_database.sh kraken2_standard_20250402 kraken2 /shared/k2_standard_20250402 \
    "Kraken2 standard 2025-04-02: RefSeq archaea, bacteria, viral, plasmid, human, UniVec_Core"
```

To add your own reference, create a folder in `$GETH_REFERENCES` with the files and a `README.txt` that
says what they are, using absolute paths:

```
Species: Danio rerio (zebrafish)
Assembly: GRCz11 (Ensembl release 116, primary assembly)
Genome FASTA: /data/geth/references/danio_rerio_GRCz11_ens116/Danio_rerio.GRCz11.dna.primary_assembly.fa.gz
Annotation GTF: /data/geth/references/danio_rerio_GRCz11_ens116/Danio_rerio.GRCz11.116.gtf.gz
```

**Reuse genome indexes.** Building a STAR index for a mammalian genome takes about 30 minutes and 30 GB of
disk for every RNA-seq or single-cell run. Once one run has built it, register it in the catalogue, and the
planner reuses it in later runs. The index is in the run's `work/` folder, or in `results/` when the plan set
`save_reference=true`:

```bash
geth/references/register_star_index.sh homo_sapiens_GRCh38_ens116 \
    $GETH_RUNS_DIR/my_pbmc/results/star/genome_generate/star "nf-core/scrnaseq 4.2.0"
```

The script hard-links the index into the catalogue entry, so it takes no extra space on the same file system.
It records the STAR version and the entry's FASTA and GTF. The plan check accepts a reused index only for
pipelines with the same STAR version and plans with the same FASTA and GTF.

## 7. Check the installation

```bash
geth doctor
```

`geth doctor` checks the following and says what to fix:

- the folders and the reference catalogue
- Nextflow, Java, the container engine and Python
- the Nextflow settings and the GPU settings
- that the model endpoint accepts your key and serves your model; the key goes in a request header and is
  never printed

The last line should be `Geth is ready.`

## 8. A first analysis on test data (optional, about 15 minutes)

Two small public deliveries, built from nf-core test data, are a quick end-to-end test of the whole
setup:
- yeast bulk RNA-seq, with mixed single- and paired-end runs
- mouse 10x single-cell RNA-seq, chromosome 19 only

```bash
bench/stage_testdata.sh                                   # about 120 MB under $GETH_DATA_ROOT/testdata
geth plan $GETH_DATA_ROOT/testdata/bulk_yeast \
    "Quantify gene expression so that we can compare wild type with the RAP1 conditions." first_test
geth show first_test
geth approve first_test
geth run first_test
```

The [user guide](user-guide.md) explains each step.

## 9. Optional: contain the agents

To run the agents in a container, which sees only each run, its data and the reference catalogue
([configuration](configuration.md#agents-container-and-time-limits)), pull the small agent image once, on a
machine with internet access (on a cluster, a transfer or staging queue):

```bash
apptainer pull $GETH_WORK_ROOT/geth/containers/geth_agent_54cf9ab304820814.sif \
    oras://community.wave.seqera.io/library/python_findutils_coreutils_gawk_pruned:54cf9ab304820814
```

Then, in `site/site.env`:

```bash
export GETH_AGENT_SANDBOX=yes
export GETH_AGENT_SANDBOX_RW=/path/to/apptainer_cache   # the image cache your Nextflow config uses, if any
```

`geth doctor` then starts a probe sandbox and checks Java, Nextflow, the scheduler and the key inside it,
and that other runs are hidden.

The experimental lab (`geth lab`) needs its analysis image too:

```bash
apptainer pull $GETH_WORK_ROOT/geth/containers/geth_lab_sc_8ead628d7c7c6607.sif \
    oras://community.wave.seqera.io/library/python_scanpy_celltypist_pydeseq2_pruned:8ead628d7c7c6607
```

## Updating Geth

```bash
cd /path/to/Geth && git pull
geth doctor
```

Releases are tagged on the `master` branch, and `geth version` prints the version you run. A new release
may pin newer pipeline versions, so finish runs that are already approved before updating.

## Uninstalling

Delete the Geth folder and `GETH_WORK_ROOT`, after keeping any results you need. Then remove the
`source .../env.sh` line from your shell profile.
