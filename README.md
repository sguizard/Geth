# Geth

**Language-model agents that plan, run, fix and report routine [nf-core](https://nf-co.re) analyses. A
person approves every plan, and deterministic checks surround every agent action.**

Give Geth a folder of sequencing data and a question in plain words. A planner agent reads the
delivery: file names, README and metadata. If something only you know is missing (which samples to
compare, say), it asks you. It chooses the pipeline, then writes the samplesheet and parameters. You
review and approve the plan. An operator agent runs the pinned nf-core pipeline, and
fixes what the error message points to if something fails. A reporter agent then writes a short report,
whose every number is checked against the results.

```
data folder + question
      |
  planner  ---- reads the folder, picks the pipeline, checks its plan against the pipeline's schemas
      |
  YOU review and approve
      |
  operator ---- launches the pinned pipeline; on failure changes only what the error names; resumes
      |
  reporter ---- writes report.md; every number and link is traced to the results
```

The agents run on Geth's own small harness (Python, standard library only) and talk to any
OpenAI-compatible model endpoint, including self-hosted ones; Nextflow runs the pipelines. Geth runs on a
single machine or a cluster.

## Quick start

```bash
git clone https://github.com/sguizard/Geth.git && cd Geth
cp site/site.env.example site/site.env      # describe your site: folders, model endpoint, scheduler
export GETH_LLM_API_KEY=...                 # the key of your model endpoint (never stored in a file)
source env.sh && geth doctor                # checks the installation (fish: source env.fish)

geth plan /data/my_experiment "Compare the treated and untreated samples." my_experiment
geth show my_experiment                     # review the plan; edit the plan files if needed
geth approve my_experiment
geth run my_experiment --detach
geth status my_experiment                   # the report: runs/my_experiment/report.md
geth stop my_experiment                     # if needed: stops it and its cluster jobs; geth run resumes
```

Then follow up on a finished run, for example with differential expression:

```bash
geth plan --from my_experiment "Which genes change with the treatment? Pair samples by donor." my_experiment_de
```

Or let the legion split a bigger question into steps (pipelines, follow-ups, a genome download when needed),
each one planned, approved and run as above, with one report at the end:

```bash
geth legion new /data/my_experiment "Which genes change with the treatment, and in which cell types?" my_project
geth legion approve my_project && geth legion run my_project   # stops whenever a step's plan needs you
```

## What it runs

| Analysis | Pipeline | Status |
|---|---|---|
| Bulk RNA-seq | nf-core/rnaseq 3.27.0 | validated with agents |
| Single-cell RNA-seq (10x), with CellBender on a GPU; multiplexed libraries (OCM, CellPlex, Flex) with Cell Ranger multi | nf-core/scrnaseq 4.2.0 | validated with agents (multiplexed: OCM test delivery) |
| Differential expression of a bulk RNA-seq run | nf-core/differentialabundance 2.0.0 | validated with agents |
| Single-cell QC, clustering and cell-type annotation | Geth's Scanpy and CellTypist toolbox | validated with agents |
| Iso-Seq, amplicon, ChIP-seq, ATAC-seq, methylation, Nanopore, ancient DNA | isoseq, ampliseq, chipseq, atacseq, methylseq, nanoseq, eager | validated with agents on realistic test deliveries |
| Germline variant calling, metagenomic profiling, metagenome assembly and binning | sarek, taxprofiler, mag | validated with agents on test deliveries (chicken germline; shared Kraken2/Bracken database) |

On a real human bulk RNA-seq dataset, Geth matched a hand-made reference analysis gene for gene. On a
10x PBMC sample it found every expected cell population. Indexes built by one run (such as STAR's, 30
minutes and 30 GB for a human genome) are registered in the reference catalogue and reused by the next.
See [validation](docs/validation.md).

## Why trust the agents

- **Agents never run arbitrary code.** They call a handful of tools: list or read files in the data
  area, check a plan, launch an approved plan, read the results. (The experimental lab below is the one
  exception, and its code runs only in a sandbox.)
- **Pinned pipelines, checked plans.** Plans are validated against the pinned release's own parameter
  and samplesheet schemas, plus pipeline-specific rules.
- **Human approval.** Nothing runs before a person approves. The approval fingerprints the plan files,
  so any edit needs a new one.
- **Plan-diff gate.** Retries can never change samples, files or comparisons. Other changes must be
  named by the previous error.
- **Checked reports.** Numbers and links that cannot be traced to the results are sent back to the
  reporter once; any left are flagged in the report.
- **Model allowlist.** Geth refuses models your site has not allowed. A paid model a person chooses for
  one command (`--model`) must be defined by the site, with its prices and a budget it cannot cross.
- **Contained agents (optional).** With `GETH_AGENT_SANDBOX=yes`, the agents run in a container that
  sees only the run, its data and the reference catalogue; the API key reaches them through the environment,
  never a file.

## Experimental: the Geth lab

`geth lab` tests how far agents can go beyond configuring pipelines. **It is not for real analyses**: it
works only on benchmark data, and everything it writes is marked experimental.

- **Arm A, design:** a designer agent writes a complete single-cell downstream analysis (QC to
  differential expression) for a question, and runs nothing. With a best-practice skill, Qwen 3.5's
  designs avoid the classic statistical trap and follow current practice; without it, they are weaker.
- **Arm B, build:** an engineer agent writes the analysis as Python steps, tests each on a subset, and a
  reviewer agent checks them; Geth then runs them on the full data. Agent-written code runs only in a
  sandbox: no network, no host files but its input and its own folder, no keys.
- **Arm C, pipeline:** the engineer writes the whole Nextflow pipeline too. Its driver runs in the sandbox
  as well, since a Nextflow script runs code in its driver.

With its skills and a reviewer agent, Qwen 3.5 built correct, working analyses in 14 of 15 builds across arms
B and C. Without the coding skill, it managed 2 of 6. These are the final benchmark rounds: rounds spoiled by
faults in Geth's own harness (an image missing packages, a contradictory results contract) were fixed and
rerun.

Results so far are in [validation](docs/validation.md#geth-lab-arm-a-agents-designing-single-cell-analyses-experimental-version-16).

## Documentation

- [Introduction](docs/introduction.md): what Geth does and does not do
- [Installation](docs/installation.md) and [configuration](docs/configuration.md): requirements, the one-file site configuration, clusters and GPUs
- [User guide](docs/user-guide.md): your first analysis, step by step
- [Pipelines](docs/pipelines.md): what is supported and what each pipeline needs
- [Developer guide](docs/developer-guide.md): architecture, gates, adding a pipeline, tests, benchmarks
- [Validation](docs/validation.md): what was tested and the results
- [Changelog](CHANGELOG.md): what changed in each release

## Status

Geth is research software. Plans are a starting point for a person to review, not a replacement for
scientific judgement.

## Contributing

Issues and pull requests are welcome. Development follows git flow: branch from `develop`; `master`
holds tagged releases. Before opening a pull request, run the tests:

```bash
python3 geth/tests/test_geth_checks.py
python3 geth/tests/test_collect_results.py
python3 geth/tests/test_lab_build.py
python3 geth/tests/test_harness.py
python3 geth/tests/test_harness_run.py
python3 geth/tests/test_harness_lab.py
python3 geth/tests/test_project.py
nextflow lint geth/jobs.nf geth/lab/jobs.nf
```

The [developer guide](docs/developer-guide.md) explains the code and how to add a pipeline.

## Citing

If you use Geth, please cite the tools that did the work:

- [Nextflow](https://doi.org/10.1038/nbt.3820) and [nf-core](https://doi.org/10.1038/s41587-020-0439-x)
- the pipelines you ran: see each pipeline's `CITATIONS.md`
- for single-cell analyses, [Scanpy](https://doi.org/10.1186/s13059-017-1382-0) and
  [CellTypist](https://doi.org/10.1126/science.abl5197)

## License

Geth is free software, released under the [GNU General Public License v3.0](LICENSE).
