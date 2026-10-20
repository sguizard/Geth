---
name: nfcore-scrnaseq
description: How to plan a droplet single-cell RNA-seq run (10x Chromium) with nf-core/scrnaseq 4.2.0 — samplesheet rules, lanes, chemistry, aligner, reference params, and multiplexed libraries (OCM, CellPlex, Flex) with cellrangermulti.
---

# nf-core/scrnaseq 4.2.0 — planning guide

Use this pipeline for **single-cell / single-nucleus** RNA-seq from droplet protocols (10x Chromium, Drop-seq, ...).

**First decide whether the libraries are multiplexed** (several samples pooled in one library, told apart by
a barcode): read every README, sample table and delivery report (HTML too). If they are, skip to
"Multiplexed libraries" below: the plain samplesheet would count all the samples of a library as one sample.

## Samplesheet (CSV, header required)
Columns: `sample,fastq_1,fastq_2,expected_cells`
- `sample`: no spaces.
- `fastq_1`: barcode + UMI read (10x file name contains `_R1_`). `fastq_2`: cDNA read (`_R2_`). Absolute paths, `.fastq.gz` only.
- **Several lanes of the same sample** (`_L001_`, `_L002_`): one row per lane with the **same `sample` name**.
- Ignore `_I1_`/`_I2_` index reads.
- `expected_cells`: integer, optional; use the number given in the metadata if any.

## Parameters (JSON object, do not include `input` or `outdir`)
- `protocol` (the chemistry) — **never assume v3**; take it from the delivery text:
  - `10XV2`: Chromium 3' v2. `10XV3`: Chromium Next GEM 3' v3 / v3.1. `10XV4`: **GEM-X** 3' v4.
  - `auto` (Cell Ranger detects the chemistry) only works with `aligner` `cellranger` or `cellrangermulti`.
  - If the delivery does not state the chemistry, say so in the rationale and ask the person to confirm it
    before approval, or use `aligner=cellranger` with `protocol=auto`. A wrong chemistry gives almost no cells.
- `aligner`: `star` (STARsolo; robust, recommended here), `simpleaf` (default), `kallisto`, `cellranger` (needs licence-free container, slow).
- Custom reference: `fasta` and `gtf`, absolute paths. Do not set `genome` at the same time.
- **CellBender** (ambient RNA removal) is recommended for real data: keep it on (`skip_cellbender=false`, the
  default). Geth sends it to a GPU automatically when the site has one (on CPUs it is slower but works).
  A real sample with ~1,000 cells or more is not "small".
- Only for tiny **test** datasets (a few MB of reads, a subset reference such as one chromosome):
  set `skip_cellbender=true` and `skip_qcatch=true` — these modules fail on such data.

## Multiplexed libraries (several samples in one library)
Signs in the delivery: **OCM** / on-chip multiplexing (library names with `10XOCM`, barcodes `OB1`–`OB4`);
**CellPlex** / CMO (`CMO301`–`CMO312`, "cell multiplexing oligo"); **Flex** / Fixed RNA Profiling / probe
barcodes (`BC001`...). A sample table that lists more samples than there are FASTQ libraries is a sign too.
- `aligner=cellrangermulti`, `protocol=auto`, `skip_cellrangermulti_vdjref=true` (unless there are VDJ reads).
- Samplesheet columns: `sample,fastq_1,fastq_2,feature_type` (`expected_cells` optional).
  `sample` is the **library** name (one name per physical library; its lanes are rows with the same name).
  `feature_type`: `gex` for gene-expression reads; CellPlex also has a `cmo` library (its own FASTQs, `cmo` rows).
- The **barcodes sheet** goes in `contrasts_lines` (never as a parameter; Geth passes it as
  `cellranger_multi_barcodes`). Header, exactly:
  `sample,multiplexed_sample_id,probe_barcode_ids,cmo_ids,ocm_ids,description`
  - one row per sample of each library; `sample` = the library name used in the samplesheet;
  - `multiplexed_sample_id` = the sample's own name (unique, no spaces); `description` = short text, required
    (e.g. the condition or tissue from the sample table);
  - exactly one barcode column filled, the same kind for the whole library:
    OCM → `ocm_ids` (`OB1`, or several joined with `|`); CellPlex → `cmo_ids` (`CMO301`...);
    Flex → `probe_barcode_ids` (`BC001`...), and set `gex_frna_probe_set` to the probe set CSV for the species.
  - Example (OCM, two libraries of four samples each):
    ```
    sample,multiplexed_sample_id,probe_barcode_ids,cmo_ids,ocm_ids,description
    Library_A,liver_1,,,OB1,liver
    Library_A,liver_2,,,OB2,liver
    ...
    Library_B,spleen_1,,,OB1,spleen
    ```
- CellBender: keep it on for real data. nf-core runs it on each library and on each sample; only the library
  runs are valid for multiplexed data (a sample's raw matrix lacks the library's empty droplets). Geth's
  report splits the library runs by sample.
- Reference: `fasta` and `gtf` (Cell Ranger builds its own index from them). Results are per sample:
  `<outdir>/cellrangermulti/count/<library>/outs/per_sample_outs/<sample>/` (metrics, web summary) and
  `<outdir>/cellrangermulti/mtx_conversions/<sample>/` (`*.h5ad`, `*.rds`).

## Reusing a built index
With `aligner=star`: if the reference catalogue entry you use lists a `STAR index:` for STAR 2.7.11b (the
version of this release), set `star_index` to that folder and keep `fasta` and `gtf` as the entry's files.
It saves about 30 minutes and 30 GB per run. Leave `star_index` unset otherwise.

## Typical failure causes
- Swapped R1/R2 (barcode read must be `fastq_1`).
- Wrong `protocol` → almost no cells detected or whitelist errors.
- Multiplexed libraries planned as plain 10x → one mixed "sample" per library; the plan check refuses this.
- CellBender / qcatch failures on small inputs (skip them).

## Outputs
`<outdir>/multiqc/multiqc_report.html`; per-aligner count matrices, e.g. `<outdir>/star/mtx_conversions/` (`*.h5ad`, `*.rds`).
