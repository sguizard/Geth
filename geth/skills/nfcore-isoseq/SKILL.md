---
name: nfcore-isoseq
description: How to plan PacBio Iso-Seq long-read transcript analysis with nf-core/isoseq 3.0.1 — samplesheet with start_from per file (subreads, CCS, full-length, FASTA), primers, aligner choice and references.
---

# nf-core/isoseq 3.0.1 — planning guide

Use this pipeline for **PacBio Iso-Seq** (full-length cDNA long reads) to build transcript models
(CCS → primer removal → refine → mapping → TAMA collapse/merge). Not for short reads or Nanopore cDNA.

## Samplesheet (CSV, header required)
Columns: `sample,seq_data,pbi,start_from`
- `seq_data`: absolute path to the input file.
- `start_from` depends on what the file contains:
  - `ccs`: raw **subreads** BAM (`*.subreads.bam`) → runs CCS, lima, refine, mapping. Needs its `.pbi` index.
  - `lima`: **CCS** reads BAM (HiFi consensus, `*.ccs.bam` / `*.hifi_reads.bam`) → skips CCS.
  - `refine`: full-length reads already demultiplexed by lima (`*.fl.bam`) → skips CCS and lima.
  - `mapping`: long-read **FASTA** (`.fa`/`.fa.gz`) → only mapping and collapse.
- `pbi`: the `.pbi` file next to a subreads BAM (`<bam>.pbi`); write `none` (lower case) for every other row.
- Several runs of the same sample: one row per file, same `sample` name (merged at the end by TAMA).

## Parameters
- `fasta`: genome FASTA (required), from the data folder or the reference catalogue.
- `aligner`: `minimap2` (works without annotation) or `ultra` (better small-exon detection, **requires `gtf`**).
- `gtf`: annotation of the same assembly (required with `ultra`).
- `primers`: FASTA of the Iso-Seq cDNA primers (required unless every row starts from `mapping`). Use the
  primers file provided with the data; never invent primer sequences.
- `chunk_ccs`, `chunk_mapping`: parallelism; keep defaults.

## Typical failure causes
- `start_from` that does not match the file type (subreads vs CCS vs FASTA).
- Missing `.pbi` for a subreads BAM, or a `pbi` path given for a non-subreads row.
- `aligner=ultra` without `gtf`; `primers` missing for BAM input.

## Outputs
Per-row results named `<sample>_<row>`; merged transcript models (TAMA merge) under the plain sample name.
