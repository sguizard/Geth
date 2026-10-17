---
name: nfcore-ampliseq
description: How to plan amplicon sequencing analysis (16S/18S/ITS/COI metabarcoding, ASVs with DADA2) with nf-core/ampliseq 3.0.0 — samplesheet with runs and controls, primers, sequencing type, truncation, taxonomy database, metadata and diversity/differential abundance options.
---

# nf-core/ampliseq 3.0.0 — planning guide

Use this pipeline for **amplicon** sequencing (16S/18S rRNA, ITS, COI... metabarcoding): primer removal,
ASV inference (DADA2), taxonomic classification, and with metadata: barplots, diversity, differential abundance.
Not for shotgun metagenomes (use nf-core/taxprofiler or mag).

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2,run` (+ optional `control`, `quant_reading`)
- `sample`: must start with a letter; letters, numbers and underscores only (no `-` or `.`).
- `run`: the sequencing run of each sample. **Fill it when samples come from several runs** — DADA2 learns
  error models per run. One run: same value everywhere.
- `fastq_2` empty for single-end (then `sequencing_type=illumina_se`).
- `control`: `control` for negative controls, `sample` otherwise (only if decontamination is wanted, `decontam=true`).
- One amplicon (one primer pair) and one sequencing technology per samplesheet.

## Parameters
- `primer_fwd`, `primer_rev`: the PCR primer sequences (IUPAC allowed), **from the metadata/README**; never
  guess. Only if reads were already trimmed of primers: `skip_cutadapt=true`.
- `sequencing_type`: `illumina_pe` (default), `illumina_se`, `iontorrent`, `pacbio`, `nanopore`.
- Truncation: `trunclenf`/`trunclenr` (fixed lengths, from read quality and amplicon length; reads must still
  overlap: trunclenf + trunclenr > amplicon length + 20) or leave them unset to let `trunc_qmin` decide.
  ITS (variable length): `illumina_pe_readthrough=true` instead of fixed truncation.
- `dada_ref_taxonomy`: database matching the amplicon: 16S: `silva=138.2` or `gtdb` / default `sbdi-gtdb`;
  18S: `pr2`; ITS fungi: `unite-fungi`; COI: `coidb`. Taxonomy downloads the database at run time.
- `metadata=<TSV>` and `metadata_category=<column>` for group comparisons; differential abundance only on
  request (`ancombc=true`). The metadata's first column must be named `ID` and hold the **sample names**.
  Geth cannot rewrite a delivery's metadata: if its IDs are not the sample names (or not valid names), leave
  `metadata` unset and say in the rationale that a metadata file with matching IDs is needed.

## Typical failure causes
- Sample names with `-`, `.` or starting with a digit.
- Wrong or missing primers (most reads discarded by cutadapt).
- Truncation lengths so short that read pairs no longer overlap (merging fails, few ASVs).
- Metadata sample IDs not matching the samplesheet.

## Outputs
ASV table and sequences under `<outdir>/dada2/`, taxonomy under `<outdir>/<classifier>/`, QIIME2 results,
summary report `<outdir>/summary_report/`.
