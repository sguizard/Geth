#!/usr/bin/env python3
"""Tests for collect_results.py and check_report.py on pipelines without a dedicated summary.

Run: python3 geth/tests/test_collect_results.py -v      (no site configuration or data needed)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
sys.path.insert(0, BIN)
import collect_results as cr  # noqa: E402

# MultiQC general statistics as written by an older MultiQC (eager 2.5.3): long column prefixes, empty cells.
EAGER_STATS = (
    "Sample\tQualiMap_mqc-generalstats-qualimap-mapped_reads\tQualiMap_mqc-generalstats-qualimap-avg_gc\t"
    "FastQC (pre-Trimming)_mqc-generalstats-fastqc_pre_trimming-total_sequences\tEmpty_mqc-generalstats-x-y\n"
    "JK2782\t1160.0\t38.38\t\t\n"
    "JK2782_L008_R1_001\t\t\t10000.0\t\n")


class GenericSummary(unittest.TestCase):

    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="geth_collect_")
        data = os.path.join(self.run, "results", "multiqc", "multiqc_data")
        os.makedirs(data)
        open(os.path.join(data, "multiqc_general_stats.txt"), "w").write(EAGER_STATS)
        open(os.path.join(self.run, "results", "multiqc", "multiqc_report.html"), "w").write("<html></html>")
        os.makedirs(os.path.join(self.run, "results", "mapping"))
        os.makedirs(os.path.join(self.run, "results", "pipeline_info"))
        for f in ("question.txt", "plan_params.json", "plan_rationale.txt"):
            open(os.path.join(self.run, f), "w").write("")
        # eager's samplesheet has no 'sample' column (the scrnaseq summary used to crash on it)
        open(os.path.join(self.run, "plan_samplesheet.csv"), "w").write(
            "Sample_Name,Library_ID,Lane,Colour_Chemistry,SeqType,Organism,Strandedness,UDG_Treatment,R1,R2,BAM\n"
            "JK2782,JK2782_L1,8,4,PE,Homo sapiens,double,half,/x/JK2782_R1.fq.gz,/x/JK2782_R2.fq.gz,NA\n")

    def tearDown(self):
        shutil.rmtree(self.run)

    def test_pipelines_without_collector_get_multiqc_and_folders(self):
        for pipeline in ("eager", "nanoseq", "chipseq"):  # nanoseq and eager have no 'sample' column
            text = cr.collect(self.run, pipeline)
            self.assertIn("| Sample | qualimap-mapped_reads | qualimap-avg_gc | fastqc_pre_trimming-total_sequences |", text)
            self.assertIn("| JK2782 | 1,160 | 38.38 | n/a |", text)
            self.assertNotIn("x-y", text)                # columns without any value are dropped
            self.assertIn("- `mapping/`", text)
            self.assertNotIn("pipeline_info", text)
            self.assertIn("multiqc_report.html", text)

    def test_no_general_statistics(self):
        os.remove(os.path.join(self.run, "results", "multiqc", "multiqc_data", "multiqc_general_stats.txt"))
        self.assertIn("No MultiQC general-statistics table found", cr.collect(self.run, "chipseq"))

    def test_report_check_traces_generic_numbers(self):
        report = os.path.join(self.run, "report.raw.md")
        open(report, "w").write("JK2782: 1,160 mapped reads, 38.4% GC, 10,000 raw reads; invented: 73.9.\n")
        subprocess.run([sys.executable, os.path.join(BIN, "check_report.py"), report, self.run, "eager", "1"],
                       check=True, capture_output=True)
        check = open(os.path.join(self.run, "report_check.txt")).read()
        self.assertIn("3/4 numbers traced", check)
        self.assertIn("73.9", check)



class MagSummary(unittest.TestCase):
    """nf-core/mag: assemblies and bins, from the files mag 5.5.0 writes (values from the mag_gut test run)."""

    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="geth_collect_mag_")
        qc = os.path.join(self.run, "results", "Assembly", "MEGAHIT", "QC", "mouseA")
        os.makedirs(os.path.join(qc, "QUAST"))
        open(os.path.join(qc, "QUAST", "report.tsv"), "w").write(
            "Assembly\tMEGAHIT-mouseA\n# contigs\t278\nLargest contig\t94357\nTotal length\t1727075\n"
            "GC (%)\t47.31\nN50\t10600\n")
        open(os.path.join(qc, "MEGAHIT-mouseA.bowtie2.log"), "w").write("99.67% overall alignment rate\n")
        binning = os.path.join(self.run, "results", "GenomeBinning")
        os.makedirs(binning)
        open(os.path.join(binning, "bin_summary.tsv"), "w").write(
            "bin\tDepth mouseA\tTotal length_quast\tN50_quast\n"
            "MEGAHIT-MetaBAT2-mouseA.1.fa\t6.5\t812495\t23272\n"
            "MEGAHIT-MetaBAT2-mouseA.2.fa\t5.1\t711505\t20000\n"
            "MEGAHIT-CONCOCT-mouseA_0.fa\t5.08\t1424\t1424\n")

    def tearDown(self):
        shutil.rmtree(self.run)

    def test_assemblies_and_bins(self):
        text = cr.collect(self.run, "mag")
        self.assertIn("| mouseA | MEGAHIT | 278 | 1,727,075 | 10,600 | 94,357 | 47.31 | 99.67 |", text)
        self.assertIn("| mouseA | MEGAHIT | MetaBAT2 | 2 | 1,524,000 | 812,495 | 23,272 | 2 |", text)
        self.assertIn("| mouseA | MEGAHIT | CONCOCT | 1 | 1,424 | 1,424 | 1,424 | 0 |", text)
        self.assertIn("No completeness or contamination estimates", text)
        self.assertIn(812495.0, cr.raw_values(self.run))

if __name__ == "__main__":
    unittest.main()
