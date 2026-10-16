---
name: nfcore-methylseq
description: How to plan DNA methylation (bisulfite, EM-seq, TAPS) analysis with nf-core/methylseq 4.2.0 — samplesheet with lanes, aligner choice, library-prep presets (PBAT, RRBS, EM-seq, single-cell, Zymo, Accel), deduplication and methylation calling options.
---

# nf-core/methylseq 4.2.0 — planning guide

Use this pipeline for **DNA methylation** sequencing: WGBS, RRBS, PBAT, EM-seq, TAPS. Alignment
(Bismark or bwa-meth), deduplication, methylation extraction and QC.

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2` (+ optional `genome`)
- Several lanes/runs of one library: one row each, same `sample` (concatenated).
- `fastq_2` empty for single-end. Absolute paths, gzipped.

## Parameters
- References: `fasta` from the catalogue (index built on the fly; `bismark_index`/`bwameth_index` if prebuilt).
- `aligner`: `bismark` (default, most validated), `bismark_hisat`, `bwameth` (faster on large genomes),
  `bwamem` with `taps=true` for TAPS data only.
- Library-prep preset — set **at most one**, from the protocol in the metadata: `rrbs=true` (reduced
  representation, MspI; also disables deduplication), `pbat=true`, `em_seq=true`, `single_cell=true`,
  `zymo=true` (Zymo Pico Methyl-Seq), `accel=true` (Swift/Accel-NGS). None = standard directional WGBS.
- `non_directional=true` only for non-directional libraries; `skip_deduplication=true` for amplicon/RRBS-like
  data; `comprehensive=true` to report CHG/CHH context too; `cytosine_report=true` for per-cytosine reports.

## Typical failure causes
- Wrong preset for the library (e.g. RRBS data run as WGBS: deduplication removes most reads).
- `taps=true` with the Bismark aligner (rejected); a prebuilt index without the matching `fasta`.
- Bismark memory on large genomes (process_high, 72 GB): Geth's production resources allow it.

## Outputs
Methylation calls under `<outdir>/<aligner>/methylation_calls/`, deduplicated BAMs, MultiQC report.
