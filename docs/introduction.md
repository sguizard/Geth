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
| Plan | `geth plan` | planner agent | Lists and reads the data folder, then chooses one of the supported pipelines. Writes the samplesheet, parameters and a rationale, and checks them against the pipeline's own schemas until the check passes. |
| Review | `geth show` | you | Shows the plan and its automatic check. You can edit any plan file. |
| Approve | `geth approve` | you | Records your name and a fingerprint of every plan file. Any later edit needs a new approval. |
| Run | `geth run` | operator agent | Launches the approved plan. On failure it may change only what the error points to; the sample design can never change. The run resumes where it stopped. |
| Report | (automatic) | reporter agent | Writes `report.md` from ready-made result tables. Every number and link is traced back to the results. |

A finished analysis can be the starting point of a follow-up:

- **differential expression** on the counts of a bulk RNA-seq run (nf-core/differentialabundance)
- **cell filtering, clustering and cell-type annotation** of a single-cell run, on a vetted Scanpy and
  CellTypist toolbox. The agent designs the analysis from a fixed menu of steps and values, and never
  writes code.

The [pipelines page](pipelines.md) lists the supported pipelines and how well each one is validated.

## Why the agents can be trusted with this, and where they cannot

Geth does not trust the model. It contains it.

- **Agents never run arbitrary code.** They can only call a small set of tools: list or read files in the
  data area, read the reference catalogue, check a plan, launch an approved plan, read the results.
- **Pipelines are pinned.** Each supported pipeline runs at one tested release, with parameters checked
  against that release's schema. A parameter that does not exist is refused, and the check suggests the
  closest real name.
- **Nothing runs without a person's approval.** The approval holds fingerprints (SHA-256 hashes) of the
  plan files.
- **The plan-diff gate.** When a run fails, the operator may retry, but every retry is compared with the
  approved plan. Sample names, file assignments, contrasts and the pipeline are frozen. Any other change
  must be named by the previous error.
- **Reports are checked.** Every number in the report must match a value in the results, and every link
  must come from the results. Otherwise the report carries a visible warning.
- **Models are allowlisted.** Geth refuses to start with a model that is not on the site's allowlist, which
  protects a shared API key from accidental use of paid models.

What Geth is **not**:

- It does not replace scientific judgement. The plan and the report are a starting point that a person
  reviews.
- It is not validated for every data type. The [validation page](validation.md) shows exactly what was
  tested. Pipelines marked "planner not yet validated" pass their own test runs, but agents have not yet
  planned real deliveries for them.
- It is not a pipeline writer. It plans and runs existing nf-core pipelines.

## What you need

- A Linux machine or cluster with Java, [Nextflow](https://www.nextflow.io) (26.10 or later), and
  apptainer or singularity (docker works for the nf-core pipelines).
- An OpenAI-compatible language-model endpoint with a model that handles tool calls and structured output
  well. Geth was developed and validated with **Qwen3.5-397B-A17B**. Mistral Small 4 did much worse in
  the same tests (see [validation](validation.md)).
- Disk space: a human bulk RNA-seq analysis of 8 samples uses about 35 GB while it runs.

## Status

Geth is research software (version 1.5), developed and validated on a university SGE cluster. The
Nextflow `agent` feature it builds on is a preview in Nextflow 26.10, and its interface may change.
Geth pins the Nextflow version for that reason.

## Where to go next

- [Installation](installation.md): install Geth and describe your site in one file.
- [User guide](user-guide.md): your first analysis, step by step.
- [Developer guide](developer-guide.md): how it works inside, and how to add a pipeline.
