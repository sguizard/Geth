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


if __name__ == "__main__":
    unittest.main()
