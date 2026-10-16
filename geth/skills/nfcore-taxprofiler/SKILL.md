---
name: nfcore-taxprofiler
description: How to plan taxonomic classification and profiling of shotgun metagenomes with nf-core/taxprofiler 2.0.1 — samplesheet with run accessions and platforms, the databases sheet, which profilers to enable, read QC, host removal and run merging.
---

# nf-core/taxprofiler 2.0.1 — planning guide

Use this pipeline to answer "which organisms are in these metagenomic samples, and how abundant" from
shotgun reads (short or long). For assembling genomes from metagenomes use nf-core/mag instead.

## Samplesheet (CSV, header required)
Columns: `sample,run_accession,instrument_platform,fastq_1,fastq_2,fasta`
- `sample`: the biological sample. `run_accession`: unique per file (pair); for one run per sample repeat the sample name.
- Several runs/lanes of one sample: same `sample`, different `run_accession`, and set `perform_runmerging=true`.
- `instrument_platform`: ENA vocabulary: `ILLUMINA`, `OXFORD_NANOPORE`, `PACBIO_SMRT`, `BGISEQ`, `DNBSEQ`, ...
- Short reads: `fastq_1` (+ `fastq_2` for paired-end, empty for single-end). Long reads: `fastq_1` only.
- `fasta`: only for already assembled contigs/long reads given as FASTA; leave FASTQ columns empty on that row.
- All files gzipped, absolute paths. Do not mix short- and long-read data in one run.

## Databases (required)
`databases`: absolute path to a databases CSV **from the reference catalogue** (Geth never downloads or builds
profiling databases). Its columns: `tool,db_name,db_params,db_type,db_path`.
Only enable profilers that have a row in that sheet.

## Parameters
- Enable profilers with `run_<tool>=true`, matching the databases sheet: `run_kraken2`, `run_bracken` (needs
  `run_kraken2` too), `run_metaphlan`, `run_motus`, `run_centrifuge`, `run_kaiju`, `run_diamond`, `run_malt`,
  `run_krakenuniq`, `run_ganon`, `run_kmcp`, `run_sylph`, `run_metacache`, `run_melon` (long reads only).
- `run_profile_standardisation=true` gives merged, comparable tables across profilers (recommended).
- Read QC (opt-in): `perform_shortread_qc=true` (adapter/quality trimming) or `perform_longread_qc=true`.
- Host removal (e.g. human gut/clinical samples): `perform_shortread_hostremoval=true` (or long-read) with
  `hostremoval_reference=<host genome FASTA from the catalogue>`.
- `perform_runmerging=true` when a sample has several runs.

## Typical failure causes
- A `run_<tool>` flag without a matching database row (or the reverse).
- Bracken without Kraken2, or Bracken `db_params` without the `;` separator.
- Duplicate `run_accession` within a sample; FASTQ and FASTA on the same row.
- Long-read data with short-read-only tools (bracken, ganon, kmcp).

## Outputs
Per-profiler reports under `<outdir>/<tool>/`, standardised tables under `<outdir>/taxpasta/`, MultiQC report.
