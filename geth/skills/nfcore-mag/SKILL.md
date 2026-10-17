---
name: nfcore-mag
description: How to plan metagenome assembly, binning and bin QC (metagenome-assembled genomes) with nf-core/mag 5.5.0 — samplesheet with samples, runs, groups, short and long reads and platforms; assembly and binning modes; which database-dependent steps to run or skip.
---

# nf-core/mag 5.5.0 — planning guide

Use this pipeline to assemble shotgun metagenomes and recover **metagenome-assembled genomes (MAGs)**:
assembly (MEGAHIT/SPAdes, Flye for long reads), binning (MetaBAT2, MaxBin2, CONCOCT...), bin refinement
and QC, taxonomy. For read-level "who is there" profiling use nf-core/taxprofiler instead.

## Samplesheet (CSV, header required)
Columns: `sample,run,group,short_reads_1,short_reads_2,short_reads_platform,long_reads,long_reads_platform`
- `sample`: biological sample. `run`: optional; several runs/lanes of one sample = same `sample`, different `run`
  (concatenated after QC).
- `group`: samples that share a group are binned together using co-abundance (e.g. a time series or replicates
  of the same environment). One group for unrelated samples is fine (assembly stays per sample by default).
- Short reads: `short_reads_1` (+ `short_reads_2`), `short_reads_platform` (e.g. `ILLUMINA`).
- Long reads (hybrid or long-read-only): `long_reads`, `long_reads_platform`: `OXFORD_NANOPORE_HQ` (recent ONT),
  `OXFORD_NANOPORE`, `PACBIO_HIFI`, `PACBIO_CLR`.
- Single-end short reads need `single_end=true`; a samplesheet cannot mix single- and paired-end short reads.
- Leave unused columns empty. Absolute paths, gzipped FASTQ.

## Parameters
- Assembly: per sample by default. Co-assembly of each group: `coassemble_group=true` with `binning_map_mode=group`.
  `skip_spades=true` / `skip_megahit=true` to run one assembler only (SPAdes is slow and memory-hungry; MEGAHIT
  alone is a sensible default for large datasets).
- Host removal: `host_fasta=<host genome FASTA from the catalogue>` for host-associated samples (gut, tissue).
- Database-dependent steps — keep them only if the database is in the reference catalogue, otherwise skip:
  - GTDB-Tk taxonomy (~110 GB): `gtdb_db=<path>` or `skip_gtdbtk=true`
  - BUSCO: `run_busco=true` with `busco_db=<path>`; CheckM2: `run_checkm2=true` with `checkm2_db=<path>`
  - CAT (~200 GB): `cat_db=<path>`; GUNC: `run_gunc=true` with `gunc_db=<path>`
  - MetaEuk: `metaeuk_db=<path>` or `skip_metaeuk=true`
- Bin size filters: `bin_min_size`, `bin_max_size` (set `min_length_unbinned_contigs` with them).

## Typical failure causes
- Platform columns missing for given reads; mixing single- and paired-end short reads.
- Database steps left on without a database (the pipeline then tries to download huge databases).
- `coassemble_group` without a sensible `group` design.

## Outputs
Assemblies under `<outdir>/Assembly/`, bins under `<outdir>/GenomeBinning/`, bin QC/taxonomy summaries
(`bin_summary.tsv`), MultiQC report.
