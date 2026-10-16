---
name: nfcore-nanoseq
description: How to plan Oxford Nanopore analysis with nf-core/nanoseq 3.1.0 — samplesheet with groups, replicates, barcodes or demultiplexed files, protocol (DNA, cDNA, directRNA), demultiplexing, alignment, transcript quantification and differential analysis, RNA modifications.
---

# nf-core/nanoseq 3.1.0 — planning guide

Use this pipeline for **Oxford Nanopore** reads: demultiplexing, QC, alignment (minimap2/GraphMap2),
and for cDNA/direct RNA: transcript quantification, differential expression, fusions, RNA modifications.
Basecalling is not done: start from FASTQ (or BAM).

## Samplesheet (CSV, header required)
Columns: `group,replicate,barcode,input_file,fasta,gtf`
- `group`: condition; `replicate`: 1, 2, ... within the group.
- **Already demultiplexed** reads (one FASTQ per sample, the usual case): `input_file` = absolute path to the
  `.fastq.gz`, `barcode` empty, and set `skip_demultiplexing=true`.
- **Not demultiplexed** (one pooled FASTQ folder): `barcode` = the barcode number per sample, `input_file`
  empty, and set `input_path=<pooled FASTQ>` and `barcode_kit` (e.g. `SQK-PBK004`) from the run metadata.
- Already aligned BAM in `input_file`: also `skip_alignment=true`.
- `fasta`: absolute path to the genome (or transcriptome) FASTA for this row; `gtf`: annotation (needed for
  quantification). Usually the same reference on every row, from the catalogue.

## Parameters
- `protocol`: `DNA`, `cDNA` or `directRNA` (from the library prep) — required.
- `aligner`: `minimap2` (default) or `graphmap2`.
- RNA: `quantification_method` `bambu` (default, can find novel transcripts) or `stringtie2`; differential
  analysis needs ≥ 2 groups with replicates (else `skip_differential_analysis=true`);
  `skip_fusion_analysis=true` unless fusions are asked for; modifications (directRNA only, needs fast5):
  otherwise `skip_modification_analysis=true`.
- DNA: `call_variants=true` only if variant calling is requested.

## Typical failure causes
- Barcodes given with `skip_demultiplexing=true` (or input files without it).
- `protocol` not matching the library (cDNA vs directRNA).
- Differential analysis with one group or no replicates.

## Outputs
Alignments and QC under `<outdir>/<aligner>/`, quantification and DE under `<outdir>/<quantification_method>/`.
