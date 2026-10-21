---
name: nfcore-rnaseq
description: How to plan a bulk RNA-seq run with nf-core/rnaseq 3.27.0 — samplesheet rules, technical replicates, strandedness, reference params, and choosing the aligner.
---

# nf-core/rnaseq 3.27.0 — planning guide

Use this pipeline for **bulk** RNA-seq (one library = one biological sample). Not for single-cell data.

## Ask when the delivery does not say
If the folder's text files do not tell you these, ask the scientist (ASK_USER, when you have it) before planning, in one round:
- The sample table: for every file, its sample, condition and biological replicate, and which files are the same library (re-sequenced runs or lanes get one sample name).
- Strandedness, or the library kit (otherwise `auto`).
- The organism and reference, when the folder holds none.

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2,strandedness`
- `sample`: no spaces. Use condition + biological replicate, e.g. `WT_REP1`, `KO_REP2`.
- `fastq_1`, `fastq_2`: **absolute paths**. Files must end in `.fastq.gz` / `.fq.gz`.
- Single-end reads: leave `fastq_2` **empty** (`WT_REP1,/data/x_1.fastq.gz,,auto`).
- `strandedness`: `auto` | `forward` | `reverse` | `unstranded`. If the library strandedness is not documented, use `auto` (Salmon infers it).
- **Technical replicates / several sequencing runs of the same library**: write one row per run with the **same `sample` name**; the pipeline merges them. Never give them different names.
- Paired-end files usually end in `_1`/`_2` or `_R1`/`_R2`. A run with only `_1` is single-end.
- Do not mix single- and paired-end runs under the same `sample` name.

## Parameters (JSON object, do not include `input` or `outdir`)
- Custom reference: `fasta` (genome FASTA) and `gtf` (annotation, `.gtf` or `.gtf.gz`), absolute paths. Do not set `genome` when using `fasta`/`gtf`.
- `aligner`: `star_salmon` (default, recommended). Use `hisat2` only if memory is very limited.
- Keep `skip_bbsplit: true` (default) unless contaminant genomes are provided.
- Optional: `skip_dupradar`, `skip_qualimap` speed up small runs.

## Reusing a built index
If the reference catalogue entry you use lists a `STAR index:` for STAR 2.7.11b (the version of this release),
set `star_index` to that folder and keep `fasta` and `gtf` as the entry's files: the index was built from them.
It saves about 30 minutes and 30 GB per run. Leave `star_index` unset otherwise (the pipeline builds one).

## Typical failure causes
- Samplesheet validation errors: wrong column names, spaces in sample names, relative paths, a `fastq_2` that is not a FASTQ.
- `min_trimmed_reads` (default 10000): samples with fewer reads after trimming are dropped. For tiny test data, set `"min_trimmed_reads": 1000`.
- `min_mapped_reads` (default 5 %) drops samples with low mapping.

## Outputs
`<outdir>/multiqc/star_salmon/multiqc_report.html`, gene counts in `<outdir>/star_salmon/salmon.merged.gene_counts.tsv`.
