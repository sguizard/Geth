---
name: nfcore-atacseq
description: How to plan ATAC-seq chromatin accessibility analysis with nf-core/atacseq 2.1.2 — samplesheet with replicates and re-sequenced libraries, optional controls, mitochondrial reads, narrow peaks, genome size, read length and references.
---

# nf-core/atacseq 2.1.2 — planning guide

Use this pipeline for **ATAC-seq** (open chromatin): alignment, mitochondrial/duplicate filtering, peak calling
(MACS2), consensus peaks and differential accessibility QC. For ChIP-seq use nf-core/chipseq.

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2,replicate` (+ `control,control_replicate` only with `with_control=true`)
- `sample`: the condition/cell type; biological replicates share `sample` with `replicate` = 1, 2, ... (start at 1).
- Re-sequenced library: repeat the row with the same `sample` and `replicate` (merged after alignment).
- No replicates: `replicate=1` everywhere.
- `fastq_2` empty for single-end. Absolute paths, gzipped.

## Parameters
- References: `fasta` + `gtf` from the catalogue (or `genome`).
- `macs_gsize`: effective genome size (human ≈ 2.7e9, mouse ≈ 1.87e9) with a custom genome.
- `read_length`: nearest of 50, 75, 100, 150, 200.
- `narrow_peak=true`: standard for ATAC-seq (Tn5 cut sites); broad only on request.
- Mitochondrial reads are removed by default: set `mito_name` to the mitochondrial contig name of the
  reference (`MT` for Ensembl, `chrM` for UCSC); `keep_mito=true` only if asked.
- `blacklist=<BED>` if available for the assembly.

## Typical failure causes
- Replicates not starting at 1; control columns without `with_control=true`.
- `mito_name` not matching the reference's contig name (mitochondrial reads then stay in).
- Missing `macs_gsize` with a custom genome.

## Outputs
Peaks under `<outdir>/<aligner>/merged_library/macs2/`, consensus peaks and counts, bigWigs, MultiQC report.
