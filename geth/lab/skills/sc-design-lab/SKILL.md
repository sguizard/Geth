---
name: sc-design-lab
description: Best practices for designing a single-cell RNA-seq downstream analysis (QC, doublets, normalisation, features, integration, clustering, annotation, differential expression between conditions), after Heumos et al. 2023 (Nat Rev Genet) and the single-cell best-practices book.
---

# Designing a single-cell downstream analysis (EXPERIMENTAL lab skill)

Decide each step from the data you inspected, and say why. Keep raw counts for every statistical test.

## Quality control
- Look at the distributions first (counts, genes and mitochondrial percentage per cell, per sample).
- Prefer data-driven thresholds: cells more than about 5 MADs from the median for counts or genes, or more than
  about 3 MADs above it for mitochondrial percentage (or a fixed 10-20%). Compute them per sample.
- Matrices that were already filtered (few low-count cells) or have no mitochondrial reads need little or no
  filtering: say so instead of applying default cut-offs that would drop real cells.
- Report how many cells each filter removes; removing more than about 10% needs a reason.

## Doublets
- If the delivery has genotype-based calls (e.g. demuxlet, souporcell, vireo), keep the singlets: these calls are
  better than expression-based detection.
- Otherwise run a doublet detector per sample (scDblFinder, Scrublet), never on merged samples.

## Normalisation and features
- Shifted logarithm (counts per 10,000, then log1p) for clustering and visualisation; keep raw counts.
- 2,000-3,000 highly variable genes, chosen per sample or batch-aware when there are several samples.
- PCA with 30-50 components; neighbour graph with 15-30 neighbours.

## Integration
- With several samples, donors or conditions, check whether cells separate by sample or condition rather than by
  type. A stimulation or treatment that shifts expression usually calls for integration (Harmony on the PCA, or
  scVI) before clustering and annotation, so that the same cell type clusters together across conditions.
- Integrated values are for clustering and annotation only: never use them for differential expression.

## Clustering and annotation
- Leiden at several resolutions; choose the one whose clusters have coherent markers.
- Annotate with canonical markers and a reference model (e.g. a CellTypist model from the reference catalogue);
  mark clusters where they disagree as uncertain.

## Differential expression between conditions
- The unit of replication is the biological sample (donor, animal), not the cell. Testing conditions with a
  cell-level test (Wilcoxon on cells) treats cells as replicates and gives false positives (pseudoreplication).
- Use pseudobulk: per cell type, sum raw counts per sample and condition, then a bulk method (DESeq2 or edgeR,
  e.g. pyDESeq2), with the pairing in the design when the same donors appear in every condition
  (`~ donor + condition`). Skip cell types with too few cells per sample (e.g. under 10-20).
- Correct for multiple testing (Benjamini-Hochberg) and report effect sizes (log2 fold changes).
- Cell-level tests remain fine for finding cluster markers.

## Composition
- Changes in cell-type proportions between conditions need sample-level replicates too (e.g. scCODA, propeller).

## Expected results
- State what known biology predicts, so the results can be checked against it.
