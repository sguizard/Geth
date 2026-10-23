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

    def test_ranges_and_dates(self):
        # 10x_multi_chicken2: "990-1,218" was read as 990 and "218" (untraced), and "83.5-85.4%" as 83.5 only
        import check_report as c
        text = c.scrub("medians 990-1,218 and 1,638–2,164; mapping 83.5-85.4%; run on 2026-10-19; 1-max-sharp")
        self.assertEqual([t for t, _ in c.numbers(text)], ["990", "1,218", "1,638", "2,164", "83.5", "85.4", "1"])
        self.assertEqual([t for t, _ in c.numbers("sample,fastq_1,expected_cells\nA,/x/a.fq.gz,5000")], ["5000"])



class PeakSummary(unittest.TestCase):
    """chipseq / atacseq: MultiQC's statistics only in multiqc_data.json, and the peaks counted from the peak files."""

    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="geth_collect_")
        out = os.path.join(self.run, "results")
        data = os.path.join(out, "multiqc", "narrow_peak", "multiqc_data")
        peaks = os.path.join(out, "bwa", "merged_library", "macs3", "narrow_peak")
        os.makedirs(data)
        os.makedirs(os.path.join(peaks, "consensus", "Spt5"))
        import json
        json.dump({"report_general_stats_data": [{"Spt5_0min_REP1": {"NSC": 1.47}},
                                                 {"Spt5_0min_REP1_T1_1": {"total_sequences": 100000.0, "avg_sequence_length": 76}}],
                   "report_general_stats_headers": [{"NSC": {"title": "NSC", "namespace": "phantompeakqualtools"}},
                                                    {"total_sequences": {"title": "M Seqs", "namespace": "FastQC"},
                                                     "avg_sequence_length": {"title": "Length", "hidden": True}}]},
                  open(os.path.join(data, "multiqc_data.json"), "w"))
        open(os.path.join(peaks, "Spt5_0min_REP1_peaks.narrowPeak"), "w").write("chrI\t1\t2\n" * 779)
        open(os.path.join(peaks, "consensus", "Spt5", "Spt5.consensus_peaks.boolean.txt"), "w").write("header\n" + "x\n" * 1310)

    def tearDown(self):
        shutil.rmtree(self.run)

    def test_json_statistics_and_peak_counts(self):
        text = cr.collect(self.run, "chipseq")
        self.assertIn("| Sample | phantompeakqualtools: NSC | FastQC: total_sequences |", text)  # raw names, hidden left out
        self.assertIn("| Spt5_0min_REP1_T1_1 | n/a | 100,000 |", text)
        self.assertIn("Raw values from MultiQC's data", text)
        self.assertIn("| Spt5_0min_REP1 | narrowPeak | 779 | `bwa/merged_library/macs3/narrow_peak/` |", text)
        self.assertIn("Spt5.consensus_peaks.boolean.txt` | 1,310 |", text)
        self.assertIn(1.47, cr.raw_values(self.run))


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

# Cell Ranger multi (scrnaseq 4.2.0, aligner cellrangermulti): rat_1's metrics_summary.csv from the sc_rat_ocm
# test run (v19ocm_sc_rat_ocm_2), trimmed to the rows the summary reads.
CR_METRICS = """Category,Library Type,Grouped By,Group Name,Metric Name,Metric Value
Cells,Gene Expression,,,Cells,499
Cells,Gene Expression,,,Confidently mapped to genome,0.240079860244572
Cells,Gene Expression,,,Median UMI counts per cell,1
Cells,Gene Expression,,,Median genes per cell,1
Cells,Gene Expression,,,Number of reads in cells,4007
Cells,Gene Expression,,,Total genes detected,212
Library,Gene Expression,Fastq ID,RatPBMC_pool,Number of reads,60000
Library,Gene Expression,OCM Barcode ID,OB1,Cells per OCM barcode,499
Library,Gene Expression,OCM Barcode ID,OB1,Sample ID,rat_1
Library,Gene Expression,OCM Barcode ID,OB1,UMIs per OCM barcode,586
Library,Gene Expression,OCM Barcode ID,OB2,Cells per OCM barcode,629
Library,Gene Expression,OCM Barcode ID,OB2,Sample ID,rat_2
Library,Gene Expression,OCM Barcode ID,OB2,UMIs per OCM barcode,763
Library,Gene Expression,Physical library ID,GEX_1,Cells,2294
Library,Gene Expression,Physical library ID,GEX_1,Mapped to genome,0.12608333333333333
Library,Gene Expression,Physical library ID,GEX_1,Mean reads per cell,26
Library,Gene Expression,Physical library ID,GEX_1,Number of reads,60000
Library,Gene Expression,Physical library ID,GEX_1,Sequencing saturation,0.25013743815283124
Library,Gene Expression,Physical library ID,GEX_1,Valid barcodes,0.93525
"""


class CellRangerMultiSummary(unittest.TestCase):

    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="geth_collect_crm_")
        outs = os.path.join(self.run, "results", "cellrangermulti", "count", "RatPBMC_pool", "outs", "per_sample_outs")
        for sample in ("rat_1", "rat_2"):
            os.makedirs(os.path.join(outs, sample))
            open(os.path.join(outs, sample, "metrics_summary.csv"), "w").write(
                CR_METRICS if sample == "rat_1" else CR_METRICS.replace("Cells,Gene Expression,,,Cells,499",
                                                                        "Cells,Gene Expression,,,Cells,629"))
        data = os.path.join(self.run, "results", "multiqc", "multiqc_data")
        os.makedirs(data)
        open(os.path.join(data, "multiqc_general_stats.txt"), "w").write(
            "Sample\tfastqc-percent_duplicates\tfastqc-percent_gc\tfastqc-total_sequences\n"
            "RatPBMC_pool_gex_1\t28.27\t51.0\t0.01\nRatPBMC_pool_gex_2\t30.37\t47.0\t0.01\n")
        open(os.path.join(self.run, "plan_samplesheet.csv"), "w").write(
            "sample,fastq_1,fastq_2,feature_type\n"
            "RatPBMC_pool,/x/RatPBMC_pool_S1_L001_R1_001.fastq.gz,/x/RatPBMC_pool_S1_L001_R2_001.fastq.gz,gex\n")
        # CellBender, as nf-core runs it after Cell Ranger multi: per sample and per library (10x_multi_chicken2 shape)
        called = {"rat_1": ["AAA-1", "AAC-1", "AAG-1"], "rat_2": ["CCA-1", "CCC-1"]}
        for sample, bcs in called.items():
            open(os.path.join(outs, sample, "sample_filtered_barcodes.csv"), "w").write(
                "".join(f"gex_reference_version,{b}\n" for b in bcs))
        crm = os.path.join(self.run, "results", "cellrangermulti")
        for name, expected, found, removed in (("rat_1", 20802, 42322, 0.016), ("rat_2", 19581, 38944, 0.021),
                                               ("RatPBMC_pool", 2521, 9617, 0.244)):
            cb = os.path.join(crm, name, "cellbender_removebackground")
            os.makedirs(cb)
            open(os.path.join(cb, f"{name}_metrics.csv"), "w").write(
                f"fraction_counts_removed_from_cells,{removed}\nexpected_cells,{expected}.000\nfound_cells,{found}.000\n"
                "fraction_of_analyzed_droplets_that_are_nonempty,0.918\n")
        open(os.path.join(crm, "RatPBMC_pool", "cellbender_removebackground", "RatPBMC_pool_cell_barcodes.csv"), "w").write(
            "AAA-1\nCCA-1\nCCC-1\nGGG-1\n")

    def tearDown(self):
        shutil.rmtree(self.run)

    def test_samples_library_and_barcodes(self):
        text = "\n\n".join(cr.scrnaseq(self.run, os.path.join(self.run, "results")))
        self.assertIn("| rat_1 | RatPBMC_pool | OB1 (OCM Barcode ID) | 499 | 1 | 1 | 212 | 4,007 | 24.0 |", text)
        self.assertIn("| rat_2 | RatPBMC_pool | OB2 (OCM Barcode ID) | 629 |", text)
        self.assertIn("| RatPBMC_pool | 60,000 | 93.5 | 12.6 | n/a | 25.0 | 2,294 | 26 |", text)
        self.assertIn("| RatPBMC_pool | OB2 | rat_2 | 629 | 763 |", text)
        self.assertNotIn("| RatPBMC_pool | RatPBMC_pool |", text)  # the per-FASTQ group is not a barcode
        self.assertIn("| RatPBMC_pool_S1_L001_R2_001.fastq.gz | RatPBMC_pool | 10,000 | 30.4 | 47 |", text)

    def test_cellbender_library_run_split_by_sample(self):
        text = "\n\n".join(cr.scrnaseq(self.run, os.path.join(self.run, "results")))
        self.assertIn("| rat_1 | sample | 20,802 | 42,322 | 3 | 1.6 | 91.8 |", text)
        self.assertIn("| RatPBMC_pool | library | 2,521 | 9,617 | 5 | 24.4 | 91.8 |", text)
        self.assertIn("| RatPBMC_pool | rat_1 | 3 | 1 |", text)
        self.assertIn("| RatPBMC_pool | rat_2 | 2 | 2 |", text)
        self.assertIn("| RatPBMC_pool | no sample (cells Cell Ranger did not call) | 0 | 1 |", text)
        self.assertIn("per-sample CellBender runs", text)


if __name__ == "__main__":
    unittest.main()
