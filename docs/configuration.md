# Configuration

Everything that depends on your site lives in one file, `site/site.env`. That covers paths, the language
model, how jobs run, GPUs and Java. Geth's code holds no site-specific values.

## How the settings are loaded

```
source env.sh
  -> sources site/site.env   (or the file named by GETH_SITE_ENV)
  -> fills in defaults, resolves folders to their real paths, loads modules
  -> exports everything
       |-- geth/harness ............ the agents read the model, endpoint and key name from the environment
       |-- geth/bin/sc_job.sh,
       |   geth/lab/bin/lab_job.sh . add -c $GETH_NF_CONFIG to the tools' scheduler jobs (jobs.nf)
       |-- geth/nextflow.config .... reads the folders from the environment, for those jobs
       `-- geth/bin/run_nfcore.sh .. adds the profile and configs below to each nf-core run
```

`site/site.env` is a bash file sourced by `env.sh`, so it can use `$HOME`, `$USER` and `$GETH_HOME` (the
Geth folder). It is listed in `.gitignore`, along with `site/*.local.*` files, because it holds personal
paths and project codes. Never put an API key in it: the file names the variable that holds the key.

Several sites or set-ups can sit side by side:

```bash
GETH_SITE_ENV=$HOME/geth-gpu-node.env source /path/to/Geth/env.sh
```

## Settings

### Storage

| Variable | Default | Meaning |
|---|---|---|
| `GETH_WORK_ROOT` | **required** | Geth's working area. |
| `GETH_DATA_ROOT` | `$GETH_WORK_ROOT` | Agents may only list and read files under this folder. Your data folders must be inside it, and so must upstream runs used for follow-up analyses. |
| `GETH_RUNS_DIR` | `$GETH_WORK_ROOT/runs` | One folder per analysis ("run"). Must be inside `GETH_DATA_ROOT` for follow-up analyses. |
| `GETH_REFERENCES` | `$GETH_WORK_ROOT/references` | The reference catalogue: one folder per entry, each with a `README.txt`. |

Existing folders are resolved to their real path (symbolic links followed). Geth compares paths as
text, so `/home/me/geth` and its real location `/exports/home/me/geth` must not both appear.

### Language model

| Variable | Default | Meaning |
|---|---|---|
| `GETH_LLM_BASE_URL` | **required** | OpenAI-compatible endpoint, e.g. `https://llm.example.org/v1` or `http://localhost:8000/v1`. |
| `GETH_LLM_MODEL` | **required** | Model used by every agent, unless a person chooses another for one command (`--model`, below), e.g. `Qwen/Qwen3.5-397B-A17B-FP8`. |
| `GETH_LLM_ALLOWED_MODELS` | `$GETH_LLM_MODEL` | Space- or comma-separated allowlist. Geth refuses to start with any other model. |
| `GETH_LLM_API_KEY_VAR` | `GETH_LLM_API_KEY` | Name of the environment variable that holds the key. Export the key in your shell profile. |
| `GETH_MODEL_<NAME>_MODEL` | none | A model a person may choose for one command with `--model <name>`: `geth plan`, `geth legion new` (the coordinator), and `geth lab` (with `--budget <USD>`, a total for the command). With it: `_PRICES` ("input,cached input,output", USD per million tokens), `_BUDGET_USD` (the most one agent stage may spend; a request that would cross it is not sent), and optionally `_API` (`responses` for OpenAI GPT-6 models, which need it for tools with reasoning), `_REASONING`, `_BASE_URL` and `_API_KEY_VAR` (default: the site's model service and key). `GETH_PLANNER_<NAME>_*` (the 2.0.0 name) is read too. |

`env.sh` unsets `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `ANTHROPIC_API_KEY`, so no tool can pick up
another provider's key by accident.

### Nextflow and jobs

| Variable | Default | Meaning |
|---|---|---|
| `GETH_NXF_VER` | `26.10.2` | Nextflow version for Geth's own jobs (exported as `NXF_VER`); they use typed processes, tested on 26.10. Pipelines that need an older Nextflow get their own (see [pipelines](pipelines.md)). |
| `NXF_HOME` | `$GETH_WORK_ROOT/nextflow` | Nextflow's cache: pipelines, plugins, launchers. |
| `GETH_NF_CONFIG` | none | Nextflow config for **Geth's own jobs** (its tools' scheduler jobs): executor, containers. See below. |
| `GETH_NFCORE_PROFILE` | none | Profile(s) given to **every nf-core run**: an institutional profile from nf-core/configs, or a container profile such as `apptainer`, `singularity` or `docker`. |
| `GETH_NFCORE_CONFIG` | none | Extra config for every nf-core run, applied last, so it wins. Use it for resource limits, queues, or anything your profile lacks. |
| `GETH_MODULES` | none | Environment modules to load, e.g. `"java/21 apptainer/1.4"`. |
| `GETH_DRIVER_CPUS` | `2` | CPUs that each Nextflow driver JVM may use. Outside scheduler jobs, `env.sh` sets `NXF_OPTS` (`-Xmx4g`, active processor count). |
| `GETH_DOWNLOAD_SUBMIT` | none (on this machine) | How a project's reference step downloads a genome (`geth/references/stage_ensembl.sh`): a command that runs the script and waits for it, e.g. `qsub -sync y -q <transfer queue> -P <project> -cwd -j y -l h_rt=02:00:00 -v GETH_HOME=$GETH_HOME`. Pass `GETH_HOME` only, never the whole environment (`-V`): it holds the API key. |
| `GETH_MAX_DRIVERS` | `0` (no limit) | Nextflow drivers allowed at once on this machine: a run uses 1 (the pipeline's), a lab stage 1 (its jobs'), a plan none (1 for a single-cell follow-up); `geth report` none. A command that would exceed it waits for a free slot. On a shared login node, set it so that drivers × `GETH_DRIVER_CPUS` stays within your allowance. |

### Lab (experimental)

| Variable | Default | Meaning |
|---|---|---|
| `GETH_LAB_DATA` | `$GETH_DATA_ROOT/testdata` | The only folders the lab's agents may read (`:`-separated). A `geth legion` project allowed to use the lab (`--lab`) adds its lab step's own input folder. |
| `GETH_LAB_IMAGE` | `$GETH_WORK_ROOT/geth/containers/geth_lab_sc_8ead628d7c7c6607.sif` | The pinned image agent-written code runs in (arms B and C): scanpy 1.11.5, celltypist 1.7.1, pydeseq2 0.5.4, harmonypy 0.0.10, scikit-image, scikit-misc, from Seqera Containers (`oras://community.wave.seqera.io/library/python_scanpy_celltypist_pydeseq2_pruned:8ead628d7c7c6607`). |
| `GETH_LAB_MODELS` | `$GETH_REFERENCES/celltypist_immune_v2` | CellTypist models copied into each step's sandbox. |

### Agents: container and time limits

A sandboxed agent sees its run's own data folder, not the whole data area. Keep `GETH_DATA_ROOT` a folder
that holds only deliveries (not the whole `GETH_WORK_ROOT`), and plan each analysis on its own delivery folder.

| Variable | Default | Meaning |
|---|---|---|
| `GETH_AGENT_SANDBOX` | `no` | `yes` runs every agent stage (`geth plan`, `geth run`, `geth report`, `geth lab`) inside apptainer on the machine Geth runs on. The stage keeps the network (its agents call the model service) and can submit scheduler jobs. It sees, read-write, only its run folder, Nextflow's home and `GETH_AGENT_SANDBOX_RW`; read-only, Geth, this run's data folder, the reference catalogue, Java, Nextflow and the scheduler's client. The API key reaches the agents through the environment, never a command line or a file. |
| `GETH_AGENT_SANDBOX_RW` | none | `:`-separated folders the agents may write, e.g. the image cache your Nextflow config uses. |
| `GETH_AGENT_SANDBOX_RO` | none | `:`-separated folders the agents may read, e.g. shared databases that reference catalogue entries point to (a Kraken2 database outside the catalogue). Without it, a plan using them fails the check inside the sandbox: "db_path does not exist". |
| `GETH_AGENT_TIMEOUT` | `2h` | Time limit for a planning, design or review stage (`timeout` syntax: `30m`, `2h`). |
| `GETH_ENGINEER_TIMEOUT` | `4h` | Time limit for a lab engineer stage. |
| `GETH_RUN_TIMEOUT` | `72h` | Time limit for `geth run` (the whole pipeline run, retries included). |
| `GETH_TEXT_WIDTH` | the terminal's width, at most 100 | Width of the agents' text as Geth shows it (`geth show`, `geth status`, `geth legion show`, `geth lab show`, the questions, the logs): one sentence per line, wrapped. The files keep the agents' text as written. |
| `GETH_STOP_GRACE` | `120` | Seconds `geth stop` gives the Nextflow drivers to cancel their scheduler jobs before it ends them. |
| `GETH_AGENT_IMAGE` | `$GETH_WORK_ROOT/geth/containers/geth_agent_54cf9ab304820814.sif` | The image the agents run in: Python 3.12 and the usual command-line tools (`oras://community.wave.seqera.io/library/python_findutils_coreutils_gawk_pruned:54cf9ab304820814`). |

Anything else your institutional profile reads from the environment goes in `site.env` too, for example
`NXF_SGE_PROJECT` for a profile that passes a project code to `qsub -P`.

### GPU

| Variable | Default | Meaning |
|---|---|---|
| `GETH_GPU` | `no` | `yes`: nf-core/scrnaseq runs with nf-core's `gpu` profile, so CellBender uses a GPU, unless the plan skips CellBender. |
| `GETH_GPU_CONFIG` | none | Extra config added when the GPU is used: how your scheduler reaches a GPU. |

nf-core marks GPU tasks with the `process_gpu` label and the `accelerator` directive. Some Nextflow
executors turn `accelerator` into a GPU request; grid executors such as SGE ignore it. On those, a
small config must send `process_gpu` tasks to a GPU queue. `site/examples/eddie-gpu.config` does this
for an SGE site.

### Older pipelines

| Variable | Default | Meaning |
|---|---|---|
| `GETH_JAVA17_HOME` | none | Java 17 home. nf-core/eager 2.5.3 (DSL1) runs with Nextflow 22.10.8, which needs Java 17 or older. |
| `GETH_CONTAINER_CACHE` | none | Image cache for the pipelines that run with the singularity engine (eager, nanoseq). |

### Developers

| Variable | Default | Meaning |
|---|---|---|
| `GETH_BENCH_DIR` | `$GETH_WORK_ROOT/bench` | Benchmark results (`bench/*.sh`). |
| `GETH_BASELINES_DIR` | `$GETH_WORK_ROOT/baselines` | Baseline runs without agents (`bench/baseline*.sh`). |
| `GETH_PLANNER_ASK` | `file` with `--answers`, else `terminal` in a terminal, else `none` | Who answers the agents' questions in `geth plan` and `geth legion new`: `terminal`, `file`, `none` (the agent proceeds on its assumptions), or `off` (no questions at all). Benchmarks set it. |
| `GETH_BENCH_TESTDATA`, `GETH_BENCH_ANSWERS`, `GETH_BENCH_BUDGET_USD` | `testdata`, `no`, none | `bench/bench_plan.sh`: the deliveries' folder (`testdata_sparse` for the sparse ones), a stand-in answering from `bench/facts/`, and the most a benchmark with a chosen model may spend. |

## Geth's own jobs: `GETH_NF_CONFIG`

Most of Geth's tools are tiny and run inside the agents' stage: listing files, checks, launching nf-core. The
nf-core pipelines submit their own jobs. A few tools are real jobs:

- the single-cell toolbox's inspection (16 GB) and analysis (4 CPUs, 32 GB, up to 4 h), through `geth/jobs.nf`,
  in a container (`depot.galaxyproject.org/singularity/celltypist:1.7.1`), so they need apptainer or singularity;
- the lab's inspection, subsets, step tests, pipeline lint and tests, and arm C's full run, through `geth/lab/jobs.nf`.

`GETH_NF_CONFIG` tells Nextflow how to run them. (A `geth legion` reference download is not a Nextflow job: it
runs as `GETH_DOWNLOAD_SUBMIT` says.)

**One machine** (`site/examples/local.config`):

```groovy
process.executor = 'local'
apptainer {
    enabled    = true
    autoMounts = true
}
```

**A cluster with an nf-core institutional profile** (`site/examples/eddie.config`). Include the profile
and you are done:

```groovy
includeConfig 'https://raw.githubusercontent.com/nf-core/configs/master/conf/<your_profile>.config'
```

**A Slurm cluster without a profile.** This template is untested; adapt the partition and the cache:

```groovy
process {
    executor = 'slurm'
    queue    = '<partition>'
}
apptainer {
    enabled    = true
    autoMounts = true
    cacheDir   = '/path/to/apptainer_cache'
}
```

## nf-core runs: profiles and configs

For each launch, `geth/bin/run_nfcore.sh` builds:

```
nextflow run nf-core/<pipeline> -r <pinned revision>
    -profile <GETH_NFCORE_PROFILE>[,<analysis profile>][,gpu]
    [-c <GETH_GPU_CONFIG>]                       scrnaseq with CellBender, when GETH_GPU=yes
    [-c geth/conf/<pipeline-specific config>]    e.g. the singularity engine for eager and nanoseq
    -c geth/conf/test.config | production.config
    [-c <GETH_NFCORE_CONFIG>]                    applied last: the site wins
    -params-file attempt_N/params.json --input attempt_N/samplesheet.csv
    --outdir <run>/results -w <run>/work -resume
```

- **Resource caps by input and reference size.** Inputs under 2 GB on a reference under 500 MB get
  `test.config` (at most 4 CPUs, 16 GB and 4 h per task) so that small jobs start quickly. Everything else
  gets `production.config` (at most 16 CPUs, 128 GB and 48 h). That includes small inputs on a large
  genome, an iGenomes genome or a prebuilt index, because STAR alone needs about 32 GB for a human genome.
  To match your nodes, set `process.resourceLimits` in `GETH_NFCORE_CONFIG`, as in
  `site/examples/local-nfcore.config`.
- **Analysis profile.** Downstream pipelines take one, e.g. `rnaseq` for differentialabundance. The
  planner chooses it from an allowlist.
- **Per-pipeline runtime.** A few older pipelines run with their own Nextflow version, config parser or
  container engine. Geth handles that; see [pipelines](pipelines.md).

## Example site files

| File | For |
|---|---|
| `site/site.env.example` | The documented template. |
| `site/examples/local.env` + `local.config` + `local-nfcore.config` | One machine, no scheduler, apptainer. |
| `site/examples/eddie.env` + `eddie.config` + `eddie-gpu.config` | The University of Edinburgh's Eddie cluster: SGE, the nf-core `roslin` profile, GPUs for CellBender. A worked example of a cluster site. |

## Security notes

- **The API key** is read only from the variable named by `GETH_LLM_API_KEY_VAR`. It is never written to
  a file, printed or passed on a command line. If your scheduler can copy your whole environment into
  jobs (`qsub -V`, Slurm's default `--export=ALL`), the key travels with it, so prefer job scripts that
  do not need it.
- **Data confinement.** The file-listing and file-reading tools refuse paths outside `GETH_DATA_ROOT`. The
  launcher refuses run folders outside `GETH_RUNS_DIR`. Single-cell annotation models must come from the
  reference catalogue: they are Python pickles, so loading one runs code.
- **Model allowlist.** The site's model must be in `GETH_LLM_ALLOWED_MODELS`, or no agent starts. Another
  model is used only when a person chooses it for one command (`--model`), only if the site defines it
  (`GETH_MODEL_<NAME>_*`), and only within its budget: a request that could cross the budget is not sent.
