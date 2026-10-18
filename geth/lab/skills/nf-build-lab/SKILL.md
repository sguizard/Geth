---
name: nf-build-lab
description: How to write a small Nextflow 26.10 pipeline (strict syntax) for Geth's lab sandbox - params, processes that call Python scripts in bin/, passing files and folders between processes, publishing results - with a working template and the strict-syntax rules that most often break a first draft.
---

# Writing the pipeline for the lab sandbox (EXPERIMENTAL lab skill)

## How Geth runs it
`nextflow run main.nf --input <data.h5ad> --outdir <folder> --models <folder>` with the local executor, no
containers and no network. Every task sees the scripts in `bin/` on its PATH. Do not set `executor`,
`container`, `conda` or `queue` in processes: Geth decides where the pipeline runs.

## A working template
```groovy
params.input  = null
params.outdir = 'results'
params.models = null

process QC {
    cpus 2

    input:
    path h5ad

    output:
    path 'qc.h5ad'

    script:
    """
    qc.py ${h5ad} qc.h5ad
    """
}

process ANNOTATE {
    cpus 2

    input:
    path h5ad
    path models          // a folder: it appears as ./models in the task

    output:
    path 'annotated.h5ad'

    script:
    """
    annotate.py ${h5ad} annotated.h5ad models
    """
}

process DIFFERENTIAL_EXPRESSION {
    cpus 4
    publishDir params.outdir, mode: 'copy'

    input:
    path h5ad

    output:
    path 'final.h5ad'
    path 'de_results.tsv'

    script:
    """
    de.py ${h5ad} final.h5ad de_results.tsv
    """
}

workflow {
    qc = QC(file(params.input))
    annotated = ANNOTATE(qc, file(params.models))
    DIFFERENTIAL_EXPRESSION(annotated)
}
```
- Each script reads and writes the files named on its command line (`sys.argv`), so the process `output:`
  names match what the script writes. A missing output file fails the task with "Missing output file".
- Only the published files reach the results: put `publishDir params.outdir, mode: 'copy'` on the processes
  that make `final.h5ad`, `de_results.tsv` or `markers.tsv`. Figures can be published too.
- A process with several outputs: use `emit:` names (`path 'final.h5ad', emit: h5ad`) and refer to
  `PROCESS.out.h5ad` in the workflow.

## Strict syntax (Nextflow 26.10): what breaks first drafts
- No `def` variables at the top level of the script: put values in `params` or inside the workflow block.
- Closures name their parameter: `.map { f -> f.name }`, not `it`.
- Channel factories are lower case: `channel.of(...)`, `channel.fromPath(...)`.
- Use `file(params.input)` for a single input file; no `Channel.fromPath` for one file.
- Strings with `$` meant for bash in a script block need `\$` (e.g. `\$HOME`); Nextflow fills `${...}`.
- Run LINT_PIPELINE after each edit of main.nf: it reports the line and the rule.

## Python scripts in bin/
- Start with `#!/usr/bin/env python3`; Geth makes them executable.
- Each step script reads its input h5ad and writes the next one; keep `layers["counts"]` (see the
  sc-build-lab skill for the analysis code itself).
- Print what each step did (cells kept, clusters, labels, tests): the test output shows it.

## Testing
TEST_PIPELINE runs everything on a 3,000-cell subset in a few minutes. When a task fails, its error output is
shown under "failed tasks"; fix the script or main.nf and test again. Only a pipeline whose last test passed,
on the files as they are now, can be saved.
