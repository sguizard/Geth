---
name: nfcore-sarek
description: How to plan germline or somatic (tumour/normal) variant calling from DNA-seq (WGS, WES, panels) with nf-core/sarek 3.10.0 — samplesheet with patients, samples, lanes and status, the step to start from, variant callers per analysis type, references and intervals.
---

# nf-core/sarek 3.10.0 — planning guide

Use this pipeline for **DNA** sequencing (whole genome, exome, targeted panels): germline small variants,
structural variants, copy number, somatic tumour/normal calling. Not for RNA-seq.

## Samplesheet (CSV, header required)
Columns for raw reads (`step=mapping`, the default): `patient,sex,status,sample,lane,fastq_1,fastq_2`
- `patient`: the individual. `sample`: one biological sample of that patient (e.g. normal blood, tumour).
- `status`: `0` = normal (germline), `1` = tumour. A tumour/normal pair = same `patient`, two `sample`s with status 0 and 1.
- `sex`: `XX`, `XY` or `NA` (only used by copy-number callers in tumour runs).
- `lane`: **required** for mapping. Several lanes or runs of the same library: one row per lane, same `sample`,
  a different `lane` value (e.g. `L001`, `L002`). Never merge lanes into one row.
- `fastq_1`/`fastq_2`: absolute paths, `.fastq.gz`. Sarek expects paired-end reads.
- Starting later (already aligned data): `step=variant_calling` with columns `bam,bai` or `cram,crai` instead of FASTQs.

## Parameters
- `step`: `mapping` for FASTQs (default).
- `tools`: comma-separated callers, chosen from the request and the design:
  - germline (status 0 only): `haplotypecaller` or `deepvariant` (small variants), add `manta` (SVs), `cnvkit` (CNV);
  - somatic tumour/normal: `mutect2`, `strelka` (small variants), `manta` (SVs), `ascat` or `cnvkit` (CNV);
  - annotation: add `vep` or `snpeff` only if annotation is requested and its cache is available.
- `wes=true` + `intervals=<target BED>` for exome/panel data (from the data folder or the reference catalogue).
- `joint_germline=true` for joint genotyping of a germline cohort (with `haplotypecaller`).
- References: prefer files from the reference catalogue: set `igenomes_ignore=true` and `fasta=<genome fasta>`.
  Without known-sites files (`dbsnp`, `known_indels`) base quality recalibration is impossible: set
  `skip_tools=baserecalibrator`.
- `genome=GATK.GRCh38` downloads the full GATK bundle from AWS iGenomes at run time (tens of GB): only if the
  request asks for it and no local reference exists.

## Other species (livestock, birds, plants)
- `igenomes_ignore=true` and `fasta` = the catalogue genome, **uncompressed** (sarek cannot index a gzipped
  FASTA: the entry lists an uncompressed copy). Known sites: the entry's `Known variants VCF`
  as `dbsnp` only (sarek builds the index; never the same file as `known_indels` too: sarek stages them together
  and the names collide). Without one: `skip_tools=baserecalibrator`.
- `germline_resource` and `pon` are human somatic resources: never set them for other species.
- Birds have a ZW sex system: `sex=NA` (the XX/XY values do not apply).
- Annotation: `vep` in `tools` only with the entry's `VEP cache`, and its four values: `vep_cache`,
  `vep_species`, `vep_genome`, `vep_cache_version` (all listed in the catalogue README). Not `snpeff`.
- Copy-number callers (`ascat`, `controlfreec`) need human resource files: do not use them here.

## Typical failure causes
- Missing `lane` column for FASTQ input; lanes given the same `lane` value.
- Somatic callers (`mutect2`, `strelka` somatic, `ascat`) without a status-1 sample, or a tumour without its normal.
- `ascat` on exome data (needs custom allele/loci files).
- Pointing `fasta` to a gzipped file without its index files when the pipeline cannot build them.

## Outputs
`<outdir>/variant_calling/<tool>/<sample or tumour_vs_normal>/*.vcf.gz`, alignment QC in `<outdir>/multiqc/multiqc_report.html`.
