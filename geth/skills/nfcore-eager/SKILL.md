---
name: nfcore-eager
description: How to plan ancient DNA analysis with nf-core/eager 2.5.3 — the TSV of samples, libraries, lanes, sequencing type, strandedness and UDG treatment; mapping, deduplication, damage, BAM filtering, sex determination, contamination and genotyping options.
---

# nf-core/eager 2.5.3 — planning guide (ancient DNA)

Use this pipeline for **ancient (or degraded) DNA**: adapter removal and read merging, mapping, duplicate
removal, DNA damage profiling, optional BAM filtering, sex determination, contamination estimates,
genotyping, metagenomic screening.

## Ask when the delivery does not say
If the folder's text files do not tell you these, ask the scientist (ASK_USER, when you have it) before planning, in one round:
- For every library: UDG treatment (none, half, full) and single- or double-stranded library.
- The sequencer of every library (two-colour NextSeq/NovaSeq or four-colour HiSeq/MiSeq), single- or paired-end.
- Which libraries belong to which individual or sample.

## Samplesheet (Geth converts it to eager's TSV; write it as CSV with exactly these columns)
`Sample_Name,Library_ID,Lane,Colour_Chemistry,SeqType,Organism,Strandedness,UDG_Treatment,R1,R2,BAM`
- `Sample_Name`: the individual/specimen. `Library_ID`: unique **across all samples**.
- `Lane`: integer; several lanes or runs of one library = same `Library_ID`, different `Lane`.
- `Colour_Chemistry`: `2` (NovaSeq, NextSeq) or `4` (HiSeq, MiSeq).
- `SeqType`: `PE` or `SE`. `Strandedness`: `double` or `single` (library prep).
- `UDG_Treatment`: `none`, `half` or `full` (from the lab protocol; affects damage and trimming).
- `R1`/`R2`: absolute FASTQ paths; `R2=NA` for single-end. `BAM`: `NA`, or a BAM (then `R1`/`R2` = `NA`, `SeqType=SE`).
- `Organism`: free text, the same for all libraries of a sample. Use `NA` for any unused field.
- Single-stranded and double-stranded libraries of one individual: give them different `Sample_Name`s.
- Do **not** set `single_end`, `udg_type`, `single_stranded` or `colour_chemistry` params: the TSV defines them.

## Parameters
- Reference: `fasta` (from the catalogue). `mapper`: `bwaaln` (default, best for short aDNA), `bwamem`,
  `circularmapper` (mitochondrial genomes), `bowtie2`.
- `dedupper`: `markduplicates` (default; required when PE and SE are mixed) or `dedup` (merged PE only).
- Optional modules, only when asked for: `run_bam_filtering` (+ mapping quality threshold), `run_trim_bam`
  (half-UDG/none: trim damaged ends before genotyping), `run_genotyping` + `genotyping_tool`
  (`pileupcaller` for SNP panels, `hc`, `ug`, `freebayes`, `angsd`), `run_sexdeterrmine`, `run_mtnucratio`,
  `run_metagenomic_screening` (needs a MALT/Kraken database — skip unless one is in the catalogue).

## Typical failure causes
- Duplicate `Library_ID`s across samples, or two rows with the same library and lane.
- `R2` given for `SE`, or `R1`/`R2` together with `BAM`.
- Setting TSV-defined options (UDG, strandedness, colour chemistry, single_end) as params too.

## Note
eager 2.5.3 is written in the old Nextflow DSL1: Geth runs it with Nextflow 22.10.8 and Java 17.
