---
name: nfcore-differentialabundance
description: How to plan differential expression with nf-core/differentialabundance 2.0.0 on the results of a finished nf-core/rnaseq run — observations sheet, contrasts and their direction, blocking for paired designs, matrices, analysis profiles.
---

# nf-core/differentialabundance 2.0.0 — planning guide (RNA-seq)

Use this pipeline for a **follow-up** analysis of a finished nf-core/rnaseq run (the upstream run).
Pipeline name in the plan: `differentialabundance`.

## Ask when the delivery does not say
If the folder's text files do not tell you these, ask the scientist (ASK_USER, when you have it) before planning, in one round:
- The comparison: which condition is the reference and which the target.
- Pairing or batches to block on (e.g. donor), and other covariates.

## Inputs from the upstream run (absolute paths)
- `matrix`: `<upstream>/results/star_salmon/salmon.merged.gene_counts.tsv` (raw counts; DESeq2 needs counts).
- `feature_length_matrix`: `<upstream>/results/star_salmon/salmon.merged.gene_lengths.tsv` (lets DESeq2 correct
  for gene-length bias; always give it with the counts above).
- `gtf`: exactly the `gtf` of the upstream run (read it from the upstream `plan_params.json`).
- If the upstream used another aligner, the folder is named after it (e.g. `star_rsem`, `hisat2`): list `results/`.

## Observations sheet (the plan's samplesheet)
Columns: `sample` plus one column per experimental variable, e.g. `sample,condition,donor`.
- `sample` must be **exactly** the column names of the count matrix (the upstream sample names), one row each.
- Take the variables from the metadata / README of the original data folder and from the upstream plan's
  rationale; never guess a variable that is not documented.
- Values: short, no spaces (e.g. `untreated`, `dex`; `N61311`).

## Contrasts (CSV)
Columns: `id,variable,reference,target,blocking`.
- `reference` is the baseline (e.g. untreated/control), `target` the condition of interest (e.g. treated).
  log2 fold changes are target vs reference: positive = higher in the target.
- `id`: letters, digits and `_` only, e.g. `dex_vs_untreated`.
- **Paired / blocked designs**: when the same donor, patient, animal, batch or cell line appears in every
  condition, put that column in `blocking` (several: separate with `;`). This removes donor-to-donor
  variation and is the correct model for paired samples.
- One row per comparison asked for; do not add comparisons nobody requested.

## Analysis profile
- `rnaseq` — DESeq2 (default, recommended).
- `rnaseq_deseq2_gprofiler2` — DESeq2 + g:Profiler enrichment of the DE genes (needs `gprofiler2_organism`,
  e.g. `hsapiens`, `mmusculus`). Use when the request asks for pathways/functions.
- `rnaseq_deseq2_gsea` — DESeq2 + GSEA (needs `gene_sets_files`; only if gene sets are provided).
- `rnaseq_limma` — limma-voom instead of DESeq2 (only if asked for).

## Parameters worth setting
- `study_name`: short name of the study.
- `differential_max_qval=0.05`, `differential_min_fold_change=2` (= |log2FC| ≥ 1) unless the request says otherwise.
- Leave everything else at its default unless the request needs it.

## Typical failure causes
- Sample names that differ from the matrix columns (case, `-` vs `_`).
- A contrast level that does not exist in the observations sheet, or a level with a single sample.
- Using TPM or length-scaled matrices with DESeq2 (use raw counts + length matrix).
