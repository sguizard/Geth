#!/usr/bin/env python3
"""Summarise an nf-core results folder as compact text for Geth's reporter agent.

Usage: collect_results.py <outdir> <pipeline>
Only facts read from files are printed, so the agent has real numbers to cite.
"""
import csv
import glob
import os
import sys

LIMIT = 9000


def general_stats(outdir):
    files = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_general_stats.txt"), recursive=True))
    if not files:
        return "MultiQC general stats: not found"
    with open(files[0]) as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    header, body = rows[0], rows[1:]
    # keep the most informative columns only
    wanted = [i for i, h in enumerate(header) if i == 0 or any(k in h.lower() for k in (
        "percent_mapped", "uniquely_mapped_percent", "total_sequences", "percent_duplicates", "percent_gc",
        "num_processed", "percent_assigned", "estimated_number_of_cells", "median_genes", "mapped_reads",
        "strandedness", "reads_with_valid_barcodes"))]
    wanted = wanted[:12]
    out = [f"MultiQC general stats ({os.path.relpath(files[0], outdir)}):",
           "\t".join(header[i] for i in wanted)]
    out += ["\t".join(r[i] if i < len(r) else "" for i in wanted) for r in body[:40]]
    return "\n".join(out)


def rnaseq(outdir):
    out = []
    for counts in sorted(glob.glob(os.path.join(outdir, "*", "salmon.merged.gene_counts.tsv"))):
        with open(counts) as fh:
            rows = list(csv.reader(fh, delimiter="\t"))
        header, body = rows[0], rows[1:]
        samples = header[2:]
        totals = [sum(float(r[i + 2]) for r in body) for i in range(len(samples))]
        means = sorted(((sum(float(x) for x in r[2:]) / len(samples), r[1] or r[0]) for r in body), reverse=True)
        out.append(f"Gene counts: {os.path.relpath(counts, outdir)} — {len(body)} genes x {len(samples)} samples")
        out += [f"  {s}: {t:,.0f} assigned reads" for s, t in zip(samples, totals)]
        out.append("  Top 5 genes by mean count: " + ", ".join(f"{g} ({m:,.0f})" for m, g in means[:5]))
    for f in sorted(glob.glob(os.path.join(outdir, "*", "deseq2_qc", "*.pca.vals.txt"))):
        out.append(f"DESeq2 PCA values file: {os.path.relpath(f, outdir)}")
    return "\n".join(out) or "Gene counts: not found"


def scrnaseq(outdir):
    out = []
    for summary in sorted(glob.glob(os.path.join(outdir, "**", "Summary.csv"), recursive=True)):
        keep = ("Number of Reads", "Reads With Valid Barcodes", "Reads Mapped to Genome: Unique",
                "Estimated Number of Cells", "Mean Reads per Cell", "Median Gene per Cell",
                "Median UMI per Cell", "Total Gene Detected")
        with open(summary) as fh:
            vals = dict(line.rstrip("\n").split(",", 1) for line in fh if "," in line)
        out.append(f"STARsolo {os.path.relpath(summary, outdir)}: "
                   + "; ".join(f"{k}={vals[k]}" for k in keep if k in vals))
    h5ad = sorted(glob.glob(os.path.join(outdir, "**", "*.h5ad"), recursive=True))
    out.append("Count matrices (.h5ad): " + (", ".join(os.path.relpath(f, outdir) for f in h5ad[:12]) or "none"))
    return "\n".join(out)


def main():
    outdir, pipeline = sys.argv[1], sys.argv[2].replace("nf-core/", "")
    if not os.path.isdir(outdir):
        print(f"No results folder at {outdir} (the run probably failed before publishing outputs).")
        return
    parts = [f"Results folder: {outdir}", general_stats(outdir)]
    parts.append(rnaseq(outdir) if pipeline == "rnaseq" else scrnaseq(outdir))
    reports = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_report.html"), recursive=True))
    parts.append("MultiQC report: " + (reports[0] if reports else "not found"))
    print("\n\n".join(parts)[:LIMIT])


if __name__ == "__main__":
    main()
