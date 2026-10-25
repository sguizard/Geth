# Introduction

Geth turns a question in plain language and a folder of sequencing data into a finished
[nf-core](https://nf-co.re) analysis with a short, checked report.

Language-model agents do the parts of a routine analysis that usually take a bioinformatician's time:

- reading what was delivered: file names, README and metadata files
- choosing the pipeline, writing the samplesheet and setting the parameters
- launching the run and fixing what goes wrong
- summarising the results for the person who asked

A person approves every plan before anything runs. Deterministic checks stand between the agents and
your data and results, so a model mistake is caught rather than trusted.

```
  data folder + question
          |
    planner agent ------ reads the folder, picks the pipeline, checks its own plan
          |
    the plan: samplesheet, parameters, rationale
          |
    YOU review and approve  (geth show / geth approve)
          |
    operator agent ----- launches the pinned nf-core pipeline; if it fails, changes only
          |              what the error names, and resumes
    reporter agent ----- writes the report from the collected results
          |
    report.md: every number is checked against the results
```

## Who it is for

- **Scientists** who want a standard analysis of their data (bulk or single-cell RNA-seq, differential
  expression, and more) without writing samplesheets and pipeline configurations. Read the
  [user guide](user-guide.md).
- **Bioinformatics teams** who want to automate the repetitive set-up of routine analyses and keep control
  of what runs. Read [installation](installation.md), then the [developer guide](developer-guide.md).

## What Geth does

| Step | Command | Who | What happens |
|---|---|---|---|
| Plan | `geth plan` | planner agent | Lists and reads the data folder, then chooses one of the supported pipelines. Asks you what the files do not say. Writes the samplesheet, parameters and a rationale, and checks them against the pipeline's own schemas (and the reads) until the check passes. |
| Review | `geth show` | you | Shows the plan and its automatic check. You can edit any plan file. |
| Approve | `geth approve` | you | Records your name and a fingerprint of every plan file. Any later edit needs a new approval. |
| Run | `geth run` | operator agent | Launches the approved plan. On failure it may change only what the error points to; the sample design can never change. The run resumes where it stopped. |
| Report | (automatic) | reporter agent | Writes `report.md` from ready-made result tables. Every number and link is traced back to the results; untraced ones go back to the reporter to correct. |

A finished analysis can be the starting point of a follow-up:

- **differential expression** on the counts of a bulk RNA-seq run (nf-core/differentialabundance)
- **cell filtering, clustering and cell-type annotation** of a single-cell run, on a vetted Scanpy and
  CellTypist toolbox. The agent designs the analysis from a fixed menu of steps and values, and never
  writes code.

A bigger question can become a **project** (`geth legion`). A coordinator agent splits it into steps: one
pipeline per data type in the delivery, their follow-ups, a genome download from Ensembl when the catalogue
lacks the species, and gaps for what Geth cannot do (naming the nf-core pipeline that would). You approve the
step list; every step is then planned, approved by you and run as above. After each step the coordinator
decides whether the next ones still make sense, and at the end it writes one checked report that answers the
question.

The [pipelines page](pipelines.md) lists the supported pipelines and how well each one is validated.

## Why the agents can be trusted with this, and where they cannot

Geth does not trust the model. It contains it.

- **Agents never run arbitrary code.** They can only call a small set of tools: list or read files in the
  data area, measure read lengths, read the reference catalogue, browse the pipeline's options, ask you a
  question, check a plan, launch an approved plan, read the results. The one
  exception is the experimental lab (`geth lab build`, benchmark data only), where code written by agents
  runs in a sandbox with no network, no host files and no keys.
- **Pipelines are pinned.** Each supported pipeline runs at one tested release, with parameters checked
  against that release's schema. A parameter that does not exist is refused, and the check suggests the
  closest real name.
- **Nothing runs without a person's approval.** The approval holds fingerprints (SHA-256 hashes) of the
  plan files.
- **The plan-diff gate.** When a run fails, the operator may retry, but every retry is compared with the
  approved plan. Sample names, file assignments, contrasts and the pipeline are frozen. Any other change
  must be named by the previous error.
- **Reports are checked.** Every number in the report must match a value in the results, and every link
  must come from the results. What cannot be traced goes back to the reporter once; anything left makes the
  report carry a visible warning.
- **Models are allowlisted.** Geth refuses to start with a model that is not on the site's allowlist, which
  protects a shared API key from accidental use of paid models. A site may define paid models that a person
  chooses for one command (`--model`); each has prices and a budget, and a request that could cross the
  budget is not sent.

What Geth is **not**:

- It does not replace scientific judgement. The plan and the report are a starting point that a person
  reviews.
- It is not validated for every data type. The [validation page](validation.md) shows exactly what was
  tested. Some pipelines are validated on test-size deliveries only.
- It is not a pipeline writer. It plans and runs existing nf-core pipelines. (An experimental lab,
  `geth lab`, tests agents that design and write analyses themselves, on benchmark data only: see the
  [developer guide](developer-guide.md#the-lab-experimental-phase-11).)

## What you need

- A Linux machine or cluster with Java, [Nextflow](https://www.nextflow.io) (26.10 or later), and
  apptainer or singularity (docker works for the nf-core pipelines).
- An OpenAI-compatible language-model endpoint with a model that handles tool calls well. Geth was
  developed and validated with **Qwen3.5-397B-A17B**. Mistral Small 4 did much worse in
  the same tests (see [validation](validation.md)).
- Disk space: a human bulk RNA-seq analysis of 8 samples uses about 35 GB while it runs.

## Status

Geth is research software (`geth version` prints the version; the [changelog](../CHANGELOG.md) lists
what each release changed), developed and validated on a university SGE cluster. Since version 2.0 its
agents run on Geth's own small harness, which talks to the model service directly; Nextflow runs the
pipelines.

## Where to go next

- [Installation](installation.md): install Geth and describe your site in one file.
- [User guide](user-guide.md): your first analysis, step by step, then follow-ups and projects.
- [Developer guide](developer-guide.md): how it works inside, and how to add a pipeline.
