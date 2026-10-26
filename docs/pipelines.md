# Pipelines

Geth plans and runs a fixed list of [nf-core](https://nf-co.re) pipelines, each pinned to one release.
For every pipeline it has:

- a **planner skill**: a short guide the planner loads, in `geth/skills/`
- the release's **parameter and samplesheet schemas**, in `geth/schemas/`
- **pipeline-specific plan checks**, in `geth/bin/geth_checks.py`

## Status levels

- **Validated with agents.** Agents planned, ran and reported real-size public data, with the results
  scored against known answers ([validation](validation.md)).
- **Validated with agents on test deliveries.** The pipeline's own test run passes on the reference site
  with Geth's runtime settings. The planner was benchmarked on a realistic test delivery, with 3/3 plans
  fully correct after one round of fixes. A full run, from plan to checked report, succeeded on that
  delivery ([validation](validation.md#full-runs-of-the-new-pipelines-version-16)). Not yet validated on
  real-size data, so review its plans with care.

## Supported pipelines

| Pipeline | Release | Use it for | Status |
|---|---|---|---|
| [rnaseq](https://nf-co.re/rnaseq/3.27.0) | 3.27.0 | Bulk RNA-seq: QC, alignment, gene counts | validated with agents |
| [scrnaseq](https://nf-co.re/scrnaseq/4.2.0) | 4.2.0 | Droplet single-cell and single-nucleus RNA-seq (10x Chromium): count matrices (introns counted for nuclei), CellBender; multiplexed libraries (OCM, CellPlex, Flex) with Cell Ranger multi | validated with agents; multiplexed: see [validation](validation.md) |
| [differentialabundance](https://nf-co.re/differentialabundance/2.0.0) | 2.0.0 | Differential expression on a finished rnaseq run | validated with agents |
| sc_downstream (Geth's toolbox) | 1.0.0 | Single-cell QC filtering, doublets, clustering, markers, CellTypist annotation (human, mouse; other species: markers only), on a finished scrnaseq run | validated with agents |
| [isoseq](https://nf-co.re/isoseq/3.0.1) | 3.0.1 | PacBio Iso-Seq full-length transcripts | validated with agents on test deliveries |
| [ampliseq](https://nf-co.re/ampliseq/3.0.0) | 3.0.0 | Amplicon / metabarcoding (16S, 18S, ITS, COI) | validated with agents on test deliveries |
| [chipseq](https://nf-co.re/chipseq/2.1.0) | 2.1.0 | ChIP-seq peak calling | validated with agents on test deliveries |
| [atacseq](https://nf-co.re/atacseq/2.1.2) | 2.1.2 | ATAC-seq chromatin accessibility | validated with agents on test deliveries |
| [methylseq](https://nf-co.re/methylseq/4.2.0) | 4.2.0 | DNA methylation: WGBS, RRBS, EM-seq, TAPS | validated with agents on test deliveries |
| [nanoseq](https://nf-co.re/nanoseq/3.1.0) | 3.1.0 | Oxford Nanopore DNA, cDNA and direct RNA | validated with agents on test deliveries |
| [eager](https://nf-co.re/eager/2.5.3) | 2.5.3 | Ancient DNA | validated with agents on test deliveries |
| [sarek](https://nf-co.re/sarek/3.10.0) | 3.10.0 | Germline and somatic variant calling (WGS, WES, panels) | validated with agents on test deliveries: germline, chicken. Somatic and human calling need a GATK bundle, not tested |
| [taxprofiler](https://nf-co.re/taxprofiler/2.0.1) | 2.0.1 | Taxonomic profiling of shotgun metagenomes | validated with agents on test deliveries, with Kraken2 and Bracken. MetaPhlAn not tested |
| [mag](https://nf-co.re/mag/5.5.0) | 5.5.0 | Metagenome assembly and binning | validated with agents on test deliveries, without GTDB-Tk and CheckM2 (no databases on the test site) |

Results summaries in the report are tailored for rnaseq, scrnaseq (with Cell Ranger multi and CellBender),
differentialabundance, mag (assemblies and bins) and the single-cell toolbox; chipseq and atacseq add the
peaks of each sample and the consensus peaks. For the other pipelines the report gives MultiQC's general
statistics (from MultiQC's text table or, when a MultiQC writes only JSON, from its JSON data) and points to
the MultiQC report and results folders.

## What each pipeline needs from you

Put the reads, and a README describing the samples, in the data folder ([user guide](user-guide.md)).
Beyond that:

| Pipeline | Reference | Worth stating in the README |
|---|---|---|
| rnaseq | genome FASTA + GTF (catalogue or folder); a registered STAR index is reused | conditions and replicates, lanes or re-sequenced libraries, strandedness if known |
| scrnaseq | genome FASTA + GTF; a registered STAR index is reused (STAR aligner) | 10x chemistry (v2, v3, GEM-X v4 ...), whole cells or nuclei, the expected number of cells; for multiplexed libraries (several samples per library: OCM, CellPlex, Flex), which barcode is which sample |
| differentialabundance | the upstream rnaseq run | the comparisons you want, pairing (donor) or batches |
| sc_downstream | a CellTypist model in the catalogue, for your tissue and species | tissue, expected cell types |
| isoseq | genome FASTA (+ GTF for some aligners) and the primers | what the files are (subreads, CCS, full-length), the primer set |
| ampliseq | none (the taxonomy database is downloaded by the pipeline) | the amplicon and primer sequences, negative controls, sequencing runs |
| chipseq | genome FASTA + GTF | which IP goes with which input control, antibodies, replicates, read length |
| atacseq | genome FASTA + GTF | replicates and controls, read length |
| methylseq | genome FASTA | library kit or protocol (e.g. RRBS, EM-seq, PBAT) |
| nanoseq | genome or transcriptome FASTA (+ GTF) | DNA, cDNA or direct RNA; barcodes, or already demultiplexed files |
| eager | genome FASTA | library build (single or double stranded), UDG treatment, colour chemistry |
| sarek | genome FASTA (uncompressed or bgzip), a known-variants VCF for base recalibration, a VEP cache for annotation: catalogue entries (`geth/references/stage_ensembl_variation.sh`) | germline or tumour/normal, sex, lanes, the variant callers you want |
| taxprofiler | a databases sheet in the catalogue (Kraken2/Bracken, MetaPhlAn), registered with `geth/references/register_database.sh` | sequencing platform, runs per sample, single- or paired-end, host reads to remove |
| mag | none required; a host genome to remove host reads; GTDB-Tk and CheckM2 databases for taxonomy and completeness (never downloaded per run) | runs per sample, groups for co-assembly, long reads |

## Pipelines with their own runtime

Some older pipeline releases do not run with Nextflow 26.10. Geth starts each one with what it needs,
without any action from you:

| Pipeline | Runs with | Why |
|---|---|---|
| chipseq 2.1.0, atacseq 2.1.2, methylseq 4.2.0 | Nextflow 26.10.2, legacy config parser (`NXF_SYNTAX_PARSER=v1`) | Their `nextflow.config` defines functions, which the strict parser rejects. |
| nanoseq 3.1.0 | Nextflow 23.10.4, singularity engine | It uses the `echo` directive, which recent Nextflow removed. With singularity it picks ready-made images instead of converting docker images. |
| eager 2.5.3 | Nextflow 22.10.8 with Java 17 (`GETH_JAVA17_HOME`), singularity engine, TSV samplesheet, `--max_*` resource parameters | It is a DSL1 pipeline. |

## Not supported (yet)

- Pipelines outside this list. The planner says so in its rationale instead of forcing a pipeline that
  does not fit. In a `geth legion` project, the coordinator reports such a step as a gap, naming the
  nf-core pipeline that would do it, if one exists (or, with `--lab`, may make a single-cell
  analysis that no pipeline does an experimental lab step).
- Several organisms or unrelated experiments in one delivery: plan them separately. (Several data types
  towards one question, such as RNA-seq and ATAC-seq of the same samples, are what `geth legion` is for:
  one step per pipeline.)
- Writing new pipelines. Geth plans and runs existing ones.

To add a pipeline, see the [developer guide](developer-guide.md#adding-a-pipeline).
