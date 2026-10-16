#!/usr/bin/env python3
"""Summarise an nf-core results folder as ready-to-copy Markdown for Geth's reporter agent.

Usage: collect_results.py <run_dir> <pipeline>
Numbers are converted, rounded and labelled here, so the reporter can copy them without arithmetic.
"""
import csv
import glob
import os
import sys


def read_tsv(path):
    with open(path) as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    return rows[0], rows[1:]


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def count(x):
    return "n/a" if x is None else f"{x:,.0f}"


def pct(x, digits=1):
    return "n/a" if x is None else f"{x:.{digits}f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def general_stats(outdir):
    files = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_general_stats.txt"), recursive=True))
    if not files:
        return {}
    header, body = read_tsv(files[0])
    return {r[0]: {h: num(v) for h, v in zip(header[1:], r[1:])} for r in body}


def latest_samplesheet(run_dir):
    attempts = sorted(glob.glob(os.path.join(run_dir, "attempt_*", "samplesheet.csv")),
                      key=lambda p: int(p.split("attempt_")[1].split("/")[0]))
    path = attempts[-1] if attempts else os.path.join(run_dir, "plan_samplesheet.csv")
    with open(path) as fh:
        return list(csv.DictReader(fh))


def rnaseq(run_dir, outdir):
    stats = general_stats(outdir)
    counts = sorted(glob.glob(os.path.join(outdir, "*", "salmon.merged.gene_counts.tsv")))
    parts = []
    samples, assigned = [], {}
    if counts:
        header, body = read_tsv(counts[0])
        samples = header[2:]
        for i, s in enumerate(samples):
            assigned[s] = sum(float(r[i + 2]) for r in body)
        means = sorted(((sum(float(x) for x in r[2:]) / len(samples), r[1] or r[0]) for r in body), reverse=True)
    rows = []
    for s in samples:
        st = stats.get(s, {})
        # MultiQC general stats store FastQC read totals in millions, summed over both mates.
        raw = st.get("fastqc_raw-total_sequences")
        trimmed = st.get("fastqc_trimmed-total_sequences")
        rows.append([s, count(raw * 1e6 if raw is not None else None),
                     count(trimmed * 1e6 if trimmed is not None else None),
                     pct(st.get("star-uniquely_mapped_percent")),
                     pct(st.get("fastqc_raw-percent_duplicates")),
                     pct(st.get("fastqc_raw-percent_gc"), 0),
                     count(assigned.get(s))])
    parts.append("### Per-sample QC\n" + table(
        ["Sample", "Reads (raw, both mates)", "Reads after trimming", "Uniquely mapped (%)",
         "Duplicates, raw (%)", "GC (%)", "Reads assigned to genes"], rows))
    if counts:
        parts.append(f"### Gene counts\nFile: `{os.path.relpath(counts[0], outdir)}`. "
                     f"{len(means)} genes x {len(samples)} samples.\n\n"
                     + table(["Gene", "Mean count per sample"], [[g, count(m)] for m, g in means[:5]]))
    else:
        parts.append("### Gene counts\nNot found.")
    pca = glob.glob(os.path.join(outdir, "*", "deseq2_qc", "*.pca.vals.txt"))
    if pca:
        parts.append(f"DESeq2 sample-QC PCA values: `{os.path.relpath(pca[0], outdir)}`")
    return parts


def scrnaseq(run_dir, outdir):
    parts = []
    rows = []
    for summary in sorted(glob.glob(os.path.join(outdir, "**", "Solo.out", "Gene", "Summary.csv"), recursive=True)
                          + glob.glob(os.path.join(outdir, "**", "*.Solo.out", "Gene", "Summary.csv"), recursive=True)):
        with open(summary) as fh:
            v = dict(line.rstrip("\n").split(",", 1) for line in fh if "," in line)
        sample = os.path.basename(os.path.dirname(os.path.dirname(summary))).replace(".Solo.out", "")
        f = lambda k: num(v.get(k))
        rows.append([sample, count(f("Number of Reads")),
                     pct(100 * f("Reads With Valid Barcodes")) if f("Reads With Valid Barcodes") is not None else "n/a",
                     pct(100 * f("Reads Mapped to Genome: Unique")) if f("Reads Mapped to Genome: Unique") is not None else "n/a",
                     count(f("Estimated Number of Cells")), count(f("Mean Reads per Cell")),
                     count(f("Median Gene per Cell")), count(f("Median UMI per Cell")), count(f("Total Gene Detected"))])
    rows = sorted({tuple(r) for r in rows})
    if rows:
        parts.append("### Per-sample STARsolo metrics\n" + table(
            ["Sample", "Reads", "Valid barcodes (%)", "Uniquely mapped to genome (%)", "Estimated cells",
             "Mean reads per cell", "Median genes per cell", "Median UMIs per cell", "Genes detected"], rows))
    else:
        parts.append("### Per-sample metrics\nNo STARsolo summary found (other aligners are not summarised yet).")

    # FastQC rows are named <sample>_<n>, n counting the sample's FASTQ files in samplesheet order.
    stats = general_stats(outdir)
    files = {}
    for row in latest_samplesheet(run_dir):
        files.setdefault(row["sample"], []).extend(os.path.basename(row[k]) for k in ("fastq_1", "fastq_2") if row.get(k))
    fq_rows = []
    for name, st in sorted(stats.items()):
        sample, _, idx = name.rpartition("_")
        if sample in files and idx.isdigit() and int(idx) <= len(files[sample]) and st.get("fastqc-total_sequences") is not None:
            fq_rows.append([files[sample][int(idx) - 1], sample, count(st["fastqc-total_sequences"] * 1e6),
                            pct(st.get("fastqc-percent_duplicates")), pct(st.get("fastqc-percent_gc"), 0)])
    if fq_rows:
        parts.append("### FastQC per input file\n" + table(["File", "Sample", "Reads", "Duplicates (%)", "GC (%)"], fq_rows))
    h5ad = sorted(glob.glob(os.path.join(outdir, "**", "*.h5ad"), recursive=True))
    parts.append("### Count matrices\n" + ("\n".join(f"- `{os.path.relpath(p, outdir)}`" for p in h5ad) or "None found."))
    return parts


def de_tables(outdir):
    """Per contrast: (contrast id, full results table, annotated table or None)."""
    found = []
    for path in sorted(glob.glob(os.path.join(outdir, "tables", "differential", "*", "*.results.tsv"))):
        name = os.path.basename(path)
        contrast = name.split(".deseq2.")[0].split(".limma.")[0]
        annotated = glob.glob(os.path.join(os.path.dirname(path), f"{contrast}_*annotated.tsv"))
        found.append((contrast, path, annotated[0] if annotated else None))
    return found


def sci(x):
    return "n/a" if x is None else f"{x:.2g}"


def differentialabundance(run_dir, outdir):
    parts = []
    contrasts_file = os.path.join(run_dir, "plan_contrasts.csv")
    if os.path.isfile(contrasts_file):
        with open(contrasts_file) as fh:
            rows = list(csv.DictReader(fh))
        parts.append("### Contrasts\n" + table(["id", "variable", "reference", "target", "blocking"],
                                                [[r.get(k, "") for k in ("id", "variable", "reference", "target", "blocking")] for r in rows])
                     + "\nlog2 fold change = target vs reference (positive = higher in the target).")
    for contrast, path, annotated in de_tables(outdir):
        with open(annotated or path) as fh:
            rows = list(csv.DictReader(fh, delimiter="\t"))
        fc_col = "log2FoldChange" if rows and "log2FoldChange" in rows[0] else "logFC"
        q_col = "padj" if rows and "padj" in rows[0] else "adj.P.Val"
        tested = [r for r in rows if num(r.get(q_col)) is not None and num(r.get(fc_col)) is not None]
        sig = [r for r in tested if num(r[q_col]) < 0.05 and abs(num(r[fc_col])) >= 1]
        up = sum(num(r[fc_col]) > 0 for r in sig)
        top = sorted(sig, key=lambda r: num(r[q_col]))[:15]
        parts.append(f"### Contrast {contrast}\n"
                     f"File: `{os.path.relpath(path, outdir)}`\n\n"
                     + table(["Genes tested", "DE genes (padj < 0.05, abs. log2FC >= 1)", "Up in target", "Down in target"],
                             [[count(len(tested)), count(len(sig)), count(up), count(len(sig) - up)]])
                     + "\n\nTop 15 DE genes by adjusted p-value:\n\n"
                     + table(["Gene", "Gene ID", "log2FC", "padj"],
                             [[r.get("gene_name") or r.get("gene_id", ""), r.get("gene_id", ""),
                               f"{num(r[fc_col]):.2f}", sci(num(r[q_col]))] for r in top]))
    if len(parts) <= 1:
        parts.append("No differential expression tables found.")
    reports = sorted(glob.glob(os.path.join(outdir, "**", "*.html"), recursive=True))
    reports = [r for r in reports if "shinyngs" not in r and "pipeline_info" not in r]
    if reports:
        parts.append("Reports: " + ", ".join(f"`{os.path.relpath(r, outdir)}`" for r in reports[:3]))
    return parts


def raw_values(run_dir):
    """Every number in the raw QC tables, so a correctly quoted value passes at any precision."""
    outdir = os.path.join(run_dir, "results")
    values = [v for st in general_stats(outdir).values() for v in st.values() if v is not None]
    for _, path, annotated in de_tables(outdir):
        with open(annotated or path) as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                values += [num(r.get(k)) for k in ("log2FoldChange", "padj", "logFC", "adj.P.Val", "baseMean")]
    for summary in glob.glob(os.path.join(outdir, "**", "Summary.csv"), recursive=True):
        with open(summary) as fh:
            values += [num(line.rstrip("\n").split(",", 1)[1]) for line in fh if "," in line]
    return [v for v in values if v is not None]


def collect(run_dir, pipeline):
    outdir = os.path.join(run_dir, "results")
    pipeline = pipeline.replace("nf-core/", "").strip()
    if not os.path.isdir(outdir):
        return f"No results folder at {outdir} (the run probably failed before publishing outputs)."
    parts = [f"Results folder: `{outdir}`"]
    if pipeline == "differentialabundance":
        return "\n\n".join(parts + differentialabundance(run_dir, outdir))
    parts += rnaseq(run_dir, outdir) if pipeline == "rnaseq" else scrnaseq(run_dir, outdir)
    reports = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_report.html"), recursive=True))
    parts.append("MultiQC report: " + (f"`{reports[0]}`" if reports else "not found"))
    return "\n\n".join(parts)


if __name__ == "__main__":
    print(collect(sys.argv[1], sys.argv[2]))
