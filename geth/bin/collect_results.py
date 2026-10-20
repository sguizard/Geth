#!/usr/bin/env python3
"""Summarise an nf-core results folder as ready-to-copy Markdown for Geth's reporter agent.

Usage: collect_results.py <run_dir> <pipeline>
Numbers are converted, rounded and labelled here, so the reporter can copy them without arithmetic.
"""
import csv
import json
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
        multi = cellranger_multi(outdir)
        parts += multi or ["### Per-sample metrics\nNo STARsolo or Cell Ranger multi summary found (other "
                           "aligners are not summarised yet)."]
    parts += cellbender(outdir)

    # FastQC rows are named <sample>_<n>, n counting the sample's FASTQ files in samplesheet order
    # (Cell Ranger multi: <sample>_<feature_type>_<n>, counting within the feature type).
    stats = general_stats(outdir)
    files, sample_of = {}, {}
    for row in latest_samplesheet(run_dir):
        keys = [row["sample"]] + ([f"{row['sample']}_{row['feature_type']}"] if row.get("feature_type") else [])
        for key in keys:
            files.setdefault(key, []).extend(os.path.basename(row[k]) for k in ("fastq_1", "fastq_2") if row.get(k))
            sample_of[key] = row["sample"]
    fq_rows = []
    for name, st in sorted(stats.items()):
        sample, _, idx = name.rpartition("_")
        if sample in files and idx.isdigit() and int(idx) <= len(files[sample]) and st.get("fastqc-total_sequences") is not None:
            fq_rows.append([files[sample][int(idx) - 1], sample_of[sample], count(st["fastqc-total_sequences"] * 1e6),
                            pct(st.get("fastqc-percent_duplicates")), pct(st.get("fastqc-percent_gc"), 0)])
    if fq_rows:
        fq_rows.sort(key=lambda r: (r[1], r[0]))
        parts.append("### FastQC per input file\n" + table(["File", "Sample", "Reads", "Duplicates (%)", "GC (%)"], fq_rows))
    h5ad = sorted(glob.glob(os.path.join(outdir, "**", "*.h5ad"), recursive=True))
    parts.append("### Count matrices\n" + ("\n".join(f"- `{os.path.relpath(p, outdir)}`" for p in h5ad) or "None found."))
    return parts


def cr_value(text):
    """A Cell Ranger metric: fractions become percentages; values printed as "93.5%" or "1,234" are read as such."""
    text = (text or "").strip()
    if text.endswith("%"):
        return num(text[:-1].replace(",", "")), True
    return num(text.replace(",", "")), False


def cellranger_multi(outdir):
    """Cell Ranger multi: one table row per demultiplexed sample, one per library, and how the library's cells
    were assigned to its samples (OCM, CMO or probe barcodes), from each sample's metrics_summary.csv."""
    files = sorted(glob.glob(os.path.join(outdir, "cellrangermulti", "**", "per_sample_outs", "*", "metrics_summary.csv"),
                             recursive=True))
    if not files:
        return []
    per_sample, libraries, assignments = [], {}, {}
    for path in files:
        sample = os.path.basename(os.path.dirname(path))
        library = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(path)))))
        with open(path) as fh:
            rows = list(csv.DictReader(fh))
        cells = {r["Metric Name"]: cr_value(r["Metric Value"]) for r in rows
                 if r["Category"] == "Cells" and r["Library Type"] == "Gene Expression"}
        share = lambda k: "n/a" if k not in cells or cells[k][0] is None else pct(cells[k][0] if cells[k][1] else 100 * cells[k][0])
        plain_n = lambda k: count(cells.get(k, (None, False))[0])
        barcode = ""
        for r in rows:
            if r["Category"] != "Library" or r["Library Type"] != "Gene Expression":
                continue
            if r["Grouped By"] == "Physical library ID":
                libraries.setdefault(library, {})[r["Metric Name"]] = cr_value(r["Metric Value"])
            elif r["Metric Name"] == "Sample ID":
                if r["Metric Value"] == sample:
                    barcode = f"{r['Group Name']} ({r['Grouped By']})"
                assignments.setdefault(library, {}).setdefault(r["Group Name"], {})["sample"] = r["Metric Value"]
            elif r["Grouped By"] and r["Group Name"]:
                assignments.setdefault(library, {}).setdefault(r["Group Name"], {})[r["Metric Name"]] = r["Metric Value"]
        per_sample.append([sample, library, barcode or "n/a", plain_n("Cells"), plain_n("Median genes per cell"),
                           plain_n("Median UMI counts per cell"), plain_n("Total genes detected"),
                           plain_n("Number of reads in cells"), share("Confidently mapped to genome")])
    parts = ["### Per-sample metrics (Cell Ranger multi, cells assigned to each sample)\n" + table(
        ["Sample", "Library", "Barcode", "Cells", "Median genes per cell", "Median UMIs per cell", "Genes detected",
         "Reads in cells", "Confidently mapped to genome (%)"], per_sample)]
    lib_rows = []
    for library, m in sorted(libraries.items()):
        g = lambda k: m.get(k, (None, False))
        frac = lambda k: "n/a" if g(k)[0] is None else pct(g(k)[0] if g(k)[1] else 100 * g(k)[0])
        lib_rows.append([library, count(g("Number of reads")[0]), frac("Valid barcodes"), frac("Mapped to genome"),
                         frac("Confidently mapped to transcriptome"), frac("Sequencing saturation"),
                         count(g("Cells")[0]), count(g("Mean reads per cell")[0])])
    if lib_rows:
        parts.append("### Per-library metrics (Cell Ranger multi, all samples of the library)\n" + table(
            ["Library", "Reads", "Valid barcodes (%)", "Mapped to genome (%)", "Confidently mapped to transcriptome (%)",
             "Sequencing saturation (%)", "Cells", "Mean reads per cell"], lib_rows))
    a_rows = []
    for library, tags in sorted(assignments.items()):
        for tag, m in sorted(tags.items()):
            if "sample" not in m:  # other groups, e.g. per FASTQ: not a sample barcode
                continue
            cells = next((v for k, v in m.items() if k.startswith("Cells per")), None)
            umis = next((v for k, v in m.items() if k.startswith("UMIs per")), None)
            a_rows.append([library, tag, m.get("sample", "n/a"), count(cr_value(cells)[0]), count(cr_value(umis)[0])])
    if a_rows:
        parts.append("### Cells assigned per barcode (Cell Ranger multi)\n" + table(
            ["Library", "Barcode", "Sample", "Cells", "UMIs of the barcode"], a_rows))
    reports = sorted(glob.glob(os.path.join(outdir, "cellrangermulti", "**", "web_summary.html"), recursive=True))
    if reports:
        parts.append("### Cell Ranger web summaries\n" + "\n".join(f"- `{os.path.relpath(p, outdir)}`" for p in reports))
    return parts


def barcodes(path, column=-1):
    """The barcodes of a CSV (one per line, possibly after other columns), without a header line."""
    out = set()
    with open(path) as fh:
        for line in fh:
            value = line.strip().split(",")[column] if line.strip() else ""
            if value and value.lower() != "barcode":
                out.add(value)
    return out


def cellbender(outdir):
    """CellBender (ambient RNA removal) runs, from each run's metrics.csv. With Cell Ranger multi, nf-core runs it on
    each sample and on each library: only the library runs are valid (a sample's raw matrix lacks the library's
    empty droplets, so CellBender cannot learn the background), so they are split by sample here."""
    files = sorted(glob.glob(os.path.join(outdir, "**", "cellbender_removebackground", "*_metrics.csv"), recursive=True))
    if not files:
        return []
    per_sample = {}  # Cell Ranger multi: sample -> (library, the barcodes Cell Ranger assigned to it)
    for path in glob.glob(os.path.join(outdir, "cellrangermulti", "count", "*", "outs", "per_sample_outs", "*",
                                       "sample_filtered_barcodes.csv")):
        sample = os.path.basename(os.path.dirname(path))
        library = path.split(os.sep + "count" + os.sep)[1].split(os.sep)[0]
        per_sample[sample] = (library, barcodes(path))
    libraries = {lib for lib, _ in per_sample.values()}
    rows, runs = [], {}
    for path in files:
        name = os.path.basename(path)[:-len("_metrics.csv")]
        with open(path) as fh:
            m = dict(line.strip().split(",", 1) for line in fh if "," in line)
        f = lambda k: num(m.get(k))
        level = "library" if name in libraries else "sample" if name in per_sample else "-"
        called = count(len(per_sample[name][1])) if name in per_sample else (
            count(sum(len(b) for lib, b in per_sample.values() if lib == name)) if name in libraries else "n/a")
        rows.append([name, level, count(f("expected_cells")), count(f("found_cells")), called,
                     pct(100 * f("fraction_counts_removed_from_cells")) if f("fraction_counts_removed_from_cells") is not None else "n/a",
                     pct(100 * f("fraction_of_analyzed_droplets_that_are_nonempty")) if f("fraction_of_analyzed_droplets_that_are_nonempty") is not None else "n/a"])
        runs[name] = os.path.dirname(path)
    header = ["Matrix", "Level", "Expected cells (CellBender)", "Cells kept by CellBender", "Cells called by Cell Ranger",
              "Counts removed from cells (%)", "Analysed droplets called non-empty (%)"]
    if not per_sample:  # not multiplexed: no level, no Cell Ranger multi cell calls
        header = [h for i, h in enumerate(header) if i not in (1, 4)]
        rows = [[c for i, c in enumerate(r) if i not in (1, 4)] for r in rows]
    parts = ["### CellBender (ambient RNA removal)\n" + table(header, rows)]
    split = []
    for library in sorted(libraries & set(runs)):
        kept = glob.glob(os.path.join(runs[library], f"{library}_cell_barcodes.csv"))
        if not kept:
            continue
        kept = barcodes(kept[0], 0)
        assigned = set()
        for sample, (lib, bcs) in sorted(per_sample.items()):
            if lib == library:
                assigned |= bcs
                split.append([library, sample, count(len(bcs)), count(len(kept & bcs))])
        split.append([library, "no sample (cells Cell Ranger did not call)", "0", count(len(kept - assigned))])
    if split:
        parts.append("### Cells per sample after CellBender (library run, split by Cell Ranger's sample assignment)\n"
                     + table(["Library", "Sample", "Cells called by Cell Ranger", "Cells kept by CellBender"], split)
                     + "\n\nWith multiplexed libraries, use the library runs above, split by sample. The per-sample "
                     "CellBender runs (`*_cellbender_filter_matrix.h5ad` of each sample) are not valid: a sample's raw "
                     "matrix lacks the library's empty droplets, so CellBender cannot learn the background. Do not use "
                     "`combined_cellbender_filter_matrix.h5ad` either: it stacks every CellBender run, per sample and "
                     "per library, so each cell appears twice.")
    return parts


def short_name(column):
    """MultiQC general-statistics column: drop the long prefix older MultiQC versions add."""
    return column.split("generalstats-", 1)[1] if "generalstats-" in column else column


def plain(x):
    """A raw value as printed for the reporter: thousands with separators, otherwise up to 2 decimals."""
    if x is None:
        return "n/a"
    if abs(x) >= 1000:
        return count(x)
    return f"{x:.2f}".rstrip("0").rstrip(".")


def generic(run_dir, outdir, max_columns=8):
    """Pipelines without a dedicated summary: MultiQC general statistics as MultiQC reports them,
    and the results folders."""
    parts = []
    files = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_general_stats.txt"), recursive=True))
    for path in files[:3]:
        header, body = read_tsv(path)
        cols = [i for i in range(1, len(header))
                if any(i < len(r) and num(r[i]) is not None for r in body)][:max_columns]
        rows = [[r[0]] + [plain(num(r[i])) if i < len(r) else "n/a" for i in cols] for r in body]
        parts.append(f"### MultiQC general statistics (`{os.path.relpath(path, outdir)}`)\n"
                     "Values exactly as MultiQC reports them: check the MultiQC report for units "
                     "(read totals are often in millions).\n\n"
                     + table(["Sample"] + [short_name(header[i]) for i in cols], rows))
    if not files:
        parts.append("### Quality control\nNo MultiQC general-statistics table found: see the MultiQC report.")
    folders = sorted(d for d in os.listdir(outdir) if os.path.isdir(os.path.join(outdir, d)) and d != "pipeline_info")
    parts.append("### Results folders\n" + ("\n".join(f"- `{d}/`" for d in folders) or "None."))
    return parts


def quast_report(path):
    with open(path) as fh:
        return dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)


def mag(run_dir, outdir):
    """nf-core/mag: assemblies (QUAST, read mapping) and bins per sample and binner."""
    parts, rows = [], []
    for path in sorted(glob.glob(os.path.join(outdir, "Assembly", "*", "QC", "*", "QUAST", "report.tsv"))):
        q = quast_report(path)
        assembler, sample = path.split(os.sep)[-5], path.split(os.sep)[-3]
        logs = glob.glob(os.path.join(os.path.dirname(os.path.dirname(path)), "*.bowtie2.log"))
        mapped = "n/a"
        for line in open(logs[0]) if logs else []:
            if "overall alignment rate" in line:
                mapped = line.split("%")[0].strip()
        rows.append([sample, assembler, count(num(q.get("# contigs"))), count(num(q.get("Total length"))),
                     count(num(q.get("N50"))), count(num(q.get("Largest contig"))), pct(num(q.get("GC (%)")), 2), mapped])
    if rows:
        parts.append("### Assemblies (QUAST, contigs of 500 bp or more)\n"
                     + table(["Sample", "Assembler", "Contigs", "Total length (bp)", "N50 (bp)", "Largest contig (bp)",
                              "GC %", "Reads mapped back %"], rows))
    summary = os.path.join(outdir, "GenomeBinning", "bin_summary.tsv")
    if os.path.isfile(summary):
        with open(summary) as fh:
            bins = list(csv.DictReader(fh, delimiter="\t"))
        groups = {}
        for b in bins:
            name = os.path.basename(b.get("bin", ""))
            fields = name.split("-", 2)
            if len(fields) == 3:
                sample = fields[2].rsplit("_", 1)[0] if "_" in fields[2] else fields[2].split(".")[0]
                groups.setdefault((sample, fields[0], fields[1]), []).append(b)
        completeness = next((k for k in (bins[0] if bins else {}) if k.lower().startswith("completeness")), None)
        brows = []
        for (sample, assembler, binner), bs in sorted(groups.items()):
            lengths = sorted(num(b.get("Total length_quast")) or 0 for b in bs)
            n50s = sorted(num(b.get("N50_quast")) or 0 for b in bs)
            row = [sample, assembler, binner, len(bs), count(sum(lengths)), count(lengths[-1]),
                   count(n50s[len(n50s) // 2]), sum(1 for x in lengths if x >= 500000)]
            if completeness:
                vals = sorted(num(b.get(completeness)) or 0 for b in bs)
                row.append(pct(vals[len(vals) // 2]))
            brows.append(row)
        header = ["Sample", "Assembler", "Binner", "Bins", "Total length (bp)", "Largest bin (bp)", "Median bin N50 (bp)",
                  "Bins of 500 kb or more"] + (["Median completeness %"] if completeness else [])
        parts.append(f"### Bins (`GenomeBinning/bin_summary.tsv`, {len(bins)} bins)\n" + table(header, brows)
                     + ("" if completeness else "\n\nNo completeness or contamination estimates: CheckM2, CheckM and "
                        "BUSCO did not run."))
    return parts + generic(run_dir, outdir)


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


def latest_analysis(run_dir):
    """diagnostics.json of the last successful single-cell analysis (analysis_N/)."""
    found = sorted(glob.glob(os.path.join(run_dir, "analysis_*", "diagnostics.json")),
                   key=lambda p: int(p.split("analysis_")[1].split("/")[0]))
    return found[-1] if found else None


def sc_downstream(run_dir):
    path = latest_analysis(run_dir)
    if not path:
        return ["No successful single-cell analysis found."]
    with open(path) as fh:
        d = json.load(fh)
    out = os.path.dirname(path)
    parts = [f"Final analysis: `{out}` (input `{d['input']}`)",
             "### Cells\n" + table(["Step", "Cells removed", "Cells kept"],
                                   [["input", "", count(d["cells_input"])]]
                                   + [[s["filter"], count(s["removed"]), count(s["kept"])] for s in d["qc_steps"]])
             + f"\n\nCells kept: {count(d['cells_kept'])} of {count(d['cells_input'])} ({pct(100 * d['cells_kept_fraction'])}%). "
             f"Doublets removed: {count(d['doublets']['detected'])} ({pct(100 * d['doublets']['rate'])}%"
             + (f"; expected {pct(100 * d['doublets']['expected_rate'])}%, score threshold {d['doublets']['threshold']}"
                if "threshold" in d["doublets"] else "") + "). "
             f"Genes kept: {count(d['genes_kept'])}.",
             "### Clustering\n" + table(["Leiden resolution", "Clusters", "Smallest cluster (cells)"],
                                        [[r, v["clusters"], v["smallest_cluster"]] for r, v in d["leiden"].items()])
             + f"\n\nChosen resolution: {d['design']['leiden.chosen']}. "
             f"{pct(100 * d['celltypist_cluster_agreement'])}% of cells carry their cluster's majority CellTypist label "
             f"(model `{os.path.basename(str(d['design']['annotation.model']))}`).",
             "### Clusters\n" + table(["Cluster", "Cells", "CellTypist majority label", "Agreement (%)", "Top markers"],
                                      [[c["cluster"], count(c["cells"]), c["celltypist_label"],
                                        pct(100 * c["celltypist_agreement"], 0),
                                        ", ".join(m["gene"] for m in c["top_markers"][:5])] for c in d["clusters"]]),
             "### CellTypist composition (per-cell labels)\n" + table(
                 ["Cell type", "Cells", "Share (%)"],
                 [[k, count(v), pct(100 * v / d["cells_kept"])] for k, v in list(d["celltypist_composition"].items())[:15]])]
    annotations = os.path.join(run_dir, "annotations.txt")
    if os.path.isfile(annotations):
        with open(annotations) as fh:
            parts.append("### Analyst's cluster annotations\n" + "\n".join(f"- {line.strip()}" for line in fh if line.strip()))
    parts.append("### Flags raised by the diagnostics\n" + ("\n".join(f"- {f}" for f in d.get("flags", [])) or "None."))
    figures = sorted(glob.glob(os.path.join(out, "*.png")))
    if figures:
        parts.append("Figures: " + ", ".join(f"`{f}`" for f in figures))
    return parts


def raw_values(run_dir):
    """Every number in the raw QC tables, so a correctly quoted value passes at any precision."""
    outdir = os.path.join(run_dir, "results")
    values = [v for st in general_stats(outdir).values() for v in st.values() if v is not None]
    diag = latest_analysis(run_dir)
    if diag:
        def walk(x):
            if isinstance(x, dict):
                for v in x.values():
                    yield from walk(v)
            elif isinstance(x, list):
                for v in x:
                    yield from walk(v)
            elif isinstance(x, (int, float)) and not isinstance(x, bool):
                yield float(x)
        with open(diag) as fh:
            d = json.load(fh)
        values += list(walk(d))
        values += [100 * d["cells_kept_fraction"], 100 * d["doublets"]["rate"], 100 * d["celltypist_cluster_agreement"]]
        values += [100 * c["celltypist_agreement"] for c in d["clusters"]]
        values += [100 * v / d["cells_kept"] for v in d["celltypist_composition"].values()]
    for _, path, annotated in de_tables(outdir):
        with open(annotated or path) as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                values += [num(r.get(k)) for k in ("log2FoldChange", "padj", "logFC", "adj.P.Val", "baseMean")]
    for path in glob.glob(os.path.join(outdir, "Assembly", "*", "QC", "*", "QUAST", "report.tsv")):
        values += [num(v) for v in quast_report(path).values()]
    if os.path.isfile(os.path.join(outdir, "GenomeBinning", "bin_summary.tsv")):
        with open(os.path.join(outdir, "GenomeBinning", "bin_summary.tsv")) as fh:
            values += [num(v) for r in csv.DictReader(fh, delimiter="\t") for v in r.values()]
    for summary in glob.glob(os.path.join(outdir, "**", "Summary.csv"), recursive=True):
        with open(summary) as fh:
            values += [num(line.rstrip("\n").split(",", 1)[1]) for line in fh if "," in line]
    return [v for v in values if v is not None]


def collect(run_dir, pipeline):
    outdir = os.path.join(run_dir, "results")
    pipeline = pipeline.replace("nf-core/", "").strip()
    if not os.path.isdir(outdir) and pipeline != "sc_downstream":
        return f"No results folder at {outdir} (the run probably failed before publishing outputs)."
    if pipeline == "sc_downstream":
        return "\n\n".join(sc_downstream(run_dir))
    parts = [f"Results folder: `{outdir}`"]
    if pipeline == "differentialabundance":
        return "\n\n".join(parts + differentialabundance(run_dir, outdir))
    parts += {"rnaseq": rnaseq, "scrnaseq": scrnaseq, "mag": mag}.get(pipeline, generic)(run_dir, outdir)
    reports = sorted(glob.glob(os.path.join(outdir, "multiqc", "**", "multiqc_report.html"), recursive=True))
    parts.append("MultiQC report: " + (f"`{reports[0]}`" if reports else "not found"))
    return "\n\n".join(parts)


if __name__ == "__main__":
    print(collect(sys.argv[1], sys.argv[2]))
