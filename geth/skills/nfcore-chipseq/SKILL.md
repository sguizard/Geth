---
name: nfcore-chipseq
description: How to plan ChIP-seq peak calling with nf-core/chipseq 2.1.0 — samplesheet linking IPs to their input controls, replicates and re-sequenced libraries, antibodies, narrow vs broad peaks, genome size, read length and references.
---

# nf-core/chipseq 2.1.0 — planning guide

Use this pipeline for **ChIP-seq** (transcription factors, histone marks): alignment, filtering, peak calling
(MACS2), consensus peaks per antibody, QC. For ATAC-seq use nf-core/atacseq.

## Samplesheet (CSV, header required; these 7 columns, in this order)
`sample,fastq_1,fastq_2,replicate,antibody,control,control_replicate`
- One row per FASTQ (pair). **IP** rows: `antibody` = the antibody/mark (e.g. `H3K27ac`, `CTCF`),
  `control` = the `sample` name of its input/IgG control, `control_replicate` = that control's replicate.
- **Control (input) rows**: same columns, but `antibody`, `control` and `control_replicate` empty.
- `sample` is the **condition** (antibody + treatment or time point, e.g. `SPT5_T0`), not the library:
  biological replicates of one condition share `sample`, with `replicate` = 1, 2, 3... (start at 1, no gaps).
  Never one sample per library.
- Inputs: one input `sample` with a replicate per culture/batch (or one input sample per condition). Each IP's
  `control` + `control_replicate` must name the input library from the **same** culture/batch.
- Re-sequenced library (several FASTQs of one replicate): repeat the row with the same `sample` and `replicate`.
- `fastq_2` empty for single-end. Absolute paths, gzipped.

## Parameters
- References: `fasta` + `gtf` from the catalogue (or `genome` for iGenomes).
- `macs_gsize`: effective genome size for MACS2 (human ≈ 2.7e9, mouse ≈ 1.87e9); required with a custom
  `fasta` unless `read_length` lets the pipeline compute it.
- `read_length`: one of 50, 75, 100, 150, 200 (nearest to the real read length).
- Peak shape: `narrow_peak=true` for transcription factors and sharp marks (H3K4me3, H3K27ac); leave false
  (broad, default) for broad marks (H3K27me3, H3K36me3, H3K9me3). Keep one peak type per antibody.
- `blacklist=<BED>` (ENCODE blacklist for the assembly) if available in the catalogue.
- `aligner`: `bwa` (default), `bowtie2`, `chromap`, `star`.

## Typical failure causes
- `control`/`control_replicate` pointing to a sample/replicate that does not exist.
- Replicates not starting at 1; controls given an antibody.
- Missing `macs_gsize` with a custom genome.

## Outputs
Peaks under `<outdir>/<aligner>/merged_library/macs2/`, consensus peaks per antibody, bigWigs, MultiQC report.
