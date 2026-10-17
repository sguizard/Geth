---
name: nfcore-scrnaseq
description: How to plan a droplet single-cell RNA-seq run (10x Chromium) with nf-core/scrnaseq 4.2.0 — samplesheet rules, lanes, protocol, aligner and reference params.
---

# nf-core/scrnaseq 4.2.0 — planning guide

Use this pipeline for **single-cell / single-nucleus** RNA-seq from droplet protocols (10x Chromium, Drop-seq, ...).

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2,expected_cells`
- `sample`: no spaces.
- `fastq_1`: barcode + UMI read (10x file name contains `_R1_`). `fastq_2`: cDNA read (`_R2_`). Absolute paths, `.fastq.gz` only.
- **Several lanes of the same sample** (`_L001_`, `_L002_`): one row per lane with the **same `sample` name**.
- Ignore `_I1_`/`_I2_` index reads.
- `expected_cells`: integer, optional; use the number given in the metadata if any.

## Parameters (JSON object, do not include `input` or `outdir`)
- `protocol`: for 10x Chromium 3' use `10XV2` (v2 chemistry) or `10XV3` (v3/v3.1). `auto` only works with some aligners — prefer an explicit value when the chemistry is known.
- `aligner`: `star` (STARsolo; robust, recommended here), `simpleaf` (default), `kallisto`, `cellranger` (needs licence-free container, slow).
- Custom reference: `fasta` and `gtf`, absolute paths. Do not set `genome` at the same time.
- **CellBender** (ambient RNA removal) is recommended for real data: keep it on (`skip_cellbender=false`, the
  default). Geth runs it on an Eddie GPU automatically. A real sample with ~1,000 cells or more is not "small".
- Only for tiny **test** datasets (a few MB of reads, a subset reference such as one chromosome):
  set `skip_cellbender=true` and `skip_qcatch=true` — these modules fail on such data.

## Typical failure causes
- Swapped R1/R2 (barcode read must be `fastq_1`).
- Wrong `protocol` → almost no cells detected or whitelist errors.
- CellBender / qcatch failures on small inputs (skip them).

## Outputs
`<outdir>/multiqc/multiqc_report.html`; per-aligner count matrices, e.g. `<outdir>/star/mtx_conversions/` (`*.h5ad`, `*.rds`).
