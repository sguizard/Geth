#!/usr/bin/env python3
"""Regression tests for geth_checks.py, replaying real failures seen while building Geth.

Run: python3 geth/tests/test_geth_checks.py -v      (no site configuration or data needed)
The plans and attempts of real runs are kept here as text; the files they point to are recreated as small
placeholders in a temporary folder (the checks look at names, headers and gzip magic, not at contents).
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import geth_checks as gc  # noqa: E402

ROOT = tempfile.mkdtemp(prefix="geth_fixtures_")  # filled by setUpModule, removed by tearDownModule
YEAST = f"{ROOT}/data/bulk_yeast"
REFS = f"{ROOT}/references"
AIRWAY = f"{ROOT}/runs/airway_1"  # a finished nf-core/rnaseq run: upstream of the DE analyses
COUNTS = f"{AIRWAY}/results/star_salmon/salmon.merged.gene_counts.tsv"
LENGTHS = f"{AIRWAY}/results/star_salmon/salmon.merged.gene_lengths.tsv"
GTF = f"{REFS}/homo_sapiens_GRCh38_ens116/Homo_sapiens.GRCh38.116.gtf.gz"

# Spike 3, run full_bulk_mistral_1 (Mistral Small 4 as operator): the approved plan, then two attempts.
# Attempt 1 split a technical replicate (second RAP1_uninduced_REP2 file renamed REP3); attempt 2 answered a
# plan-check error about 'strandedness' by also adding threshold params nobody asked for.
MISTRAL_SHEET = """sample,fastq_1,fastq_2,strandedness
wild_type_REP1,{Y}/fastq/SRR6357070_1.fastq.gz,{Y}/fastq/SRR6357070_2.fastq.gz,auto
wild_type_REP1,{Y}/fastq/SRR6357071_1.fastq.gz,{Y}/fastq/SRR6357071_2.fastq.gz,auto
wild_type_REP2,{Y}/fastq/SRR6357072_1.fastq.gz,{Y}/fastq/SRR6357072_2.fastq.gz,auto
RAP1_uninduced_REP1,{Y}/fastq/SRR6357073_1.fastq.gz,,auto
RAP1_uninduced_REP2,{Y}/fastq/SRR6357074_1.fastq.gz,,auto
RAP1_uninduced_REP2,{Y}/fastq/SRR6357075_1.fastq.gz,,auto
RAP1_IAA_30min_REP1,{Y}/fastq/SRR6357076_1.fastq.gz,{Y}/fastq/SRR6357076_2.fastq.gz,auto
""".replace("{Y}", YEAST)
MISTRAL_ATTEMPT_1_SHEET = MISTRAL_SHEET.replace(f"RAP1_uninduced_REP2,{YEAST}/fastq/SRR6357075",
                                                f"RAP1_uninduced_REP3,{YEAST}/fastq/SRR6357075")
MISTRAL_PARAMS = json.dumps({"fasta": f"{YEAST}/reference/genome.fasta", "gtf": f"{YEAST}/reference/genes.gtf.gz",
                             "aligner": "star_salmon", "strandedness": "auto", "skip_bbsplit": True,
                             "skip_dupradar": True, "skip_qualimap": True}, indent=2)
MISTRAL_ATTEMPT_2_PARAMS = json.dumps({"fasta": f"{YEAST}/reference/genome.fasta", "gtf": f"{YEAST}/reference/genes.gtf.gz",
                                       "aligner": "star_salmon", "stranded_threshold": 0.8, "unstranded_threshold": 0.2,
                                       "skip_bbsplit": True, "skip_dupradar": True, "skip_qualimap": True}, indent=2)

OBS = """sample,condition,donor
N61311_untreated,untreated,N61311
N61311_Dex,dex,N61311
N052611_untreated,untreated,N052611
N052611_Dex,dex,N052611
N080611_untreated,untreated,N080611
N080611_Dex,dex,N080611
N061011_untreated,untreated,N061011
N061011_Dex,dex,N061011
"""
CONTRASTS = "id,variable,reference,target,blocking\ndex_vs_untreated,condition,untreated,dex,donor\n"
DE_PARAMS = json.dumps({"matrix": COUNTS, "feature_length_matrix": LENGTHS, "gtf": GTF})

H5AD = f"{ROOT}/runs/pbmc_1/results/star/mtx_conversions/pbmc_1k_v3/pbmc_1k_v3_filtered_matrix.h5ad"
MODEL = f"{REFS}/celltypist_immune_v2/Immune_All_Low.pkl"


def setUpModule():
    def write(path, text, compress=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with (gzip.open(path, "wt") if compress else open(path, "w")) as fh:
            fh.write(text)

    for run in range(70, 77):
        for read in (1, 2):
            write(f"{YEAST}/fastq/SRR63570{run}_{read}.fastq.gz", "@r\nACGT\n+\nIIII\n", compress=True)
    write(f"{YEAST}/reference/genome.fasta", ">I\nACGT\n")
    write(f"{YEAST}/reference/genes.gtf.gz", 'I\tx\texon\t1\t4\t.\t+\t.\tgene_id "g";\n', compress=True)
    write(GTF, '1\tx\texon\t1\t4\t.\t+\t.\tgene_id "g";\n', compress=True)
    header = "\t".join(["gene_id", "gene_name"] + [line.split(",")[0] for line in OBS.splitlines()[1:]]) + "\n"
    write(COUNTS, header + "g1\tA\t" + "\t".join(["5"] * 8) + "\n")
    write(LENGTHS, header + "g1\tA\t" + "\t".join(["900"] * 8) + "\n")
    write(f"{AIRWAY}/plan_samplesheet.csv", MISTRAL_SHEET)
    write(f"{AIRWAY}/plan_params.json", json.dumps({"fasta": f"{YEAST}/reference/genome.fasta", "gtf": GTF}))
    write(H5AD, "placeholder")
    write(MODEL, "placeholder")
    gc.REFERENCES = REFS


def tearDownModule():
    shutil.rmtree(ROOT)


class Run:
    """A throwaway run folder holding plan_* files."""

    def __init__(self, pipeline, sheet, params, contrasts=None, profile=None, upstream=None):
        self.dir = tempfile.mkdtemp(prefix="geth_test_")
        self.write("plan_pipeline.txt", pipeline)
        self.write("plan_samplesheet.csv", sheet)
        self.write("plan_params.json", params)
        if contrasts is not None:
            self.write("plan_contrasts.csv", contrasts)
            self.write("plan_profile.txt", profile or "")
        if upstream:
            self.write("plan_upstream.txt", upstream)

    def write(self, name, text):
        open(os.path.join(self.dir, name), "w").write(text)

    def path(self, name):
        return os.path.join(self.dir, name)

    def read(self, name):
        return open(self.path(name)).read()

    def close(self):
        shutil.rmtree(self.dir)


class UpstreamGate(unittest.TestCase):
    """v1.1 behaviour, replayed on the real Mistral failures from spike 3."""

    def setUp(self):
        self.run = Run("rnaseq", MISTRAL_SHEET, MISTRAL_PARAMS)
        gc.approve(self.run.dir, "tester")

    def tearDown(self):
        self.run.close()

    def test_unapproved_plan_is_refused(self):
        os.remove(self.run.path("APPROVED"))
        problems = gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.assertTrue(any("not been approved" in p for p in problems))

    def test_split_technical_replicate_is_refused(self):
        problems = gc.gate(self.run.dir, "rnaseq", MISTRAL_ATTEMPT_1_SHEET, self.run.read("plan_params.json"))
        self.assertTrue(any("RAP1_uninduced_REP3" in p for p in problems), problems)

    def test_unrequested_params_are_refused_and_minimal_fix_allowed(self):
        problems, _ = gc.check_plan("rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.run.write("check.txt", "\n".join(problems))
        gc.record(self.run.dir, "check", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"), "\n".join(problems))
        self.assertTrue(gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), MISTRAL_ATTEMPT_2_PARAMS))
        minimal = json.loads(self.run.read("plan_params.json"))
        minimal.pop("strandedness")
        self.assertEqual(gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), json.dumps(minimal)), [])

    def test_plan_edited_after_approval_is_refused(self):
        self.run.write("plan_params.json", self.run.read("plan_params.json") + "\n")
        problems = gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.assertTrue(any("changed after approval" in p for p in problems))


class StarIndexReuse(unittest.TestCase):
    """A reused STAR index must be registered and match the release's STAR version, FASTA and GTF."""

    def setUp(self):
        self.index = tempfile.mkdtemp(prefix="geth_star_")
        self.info = {"tool": "STAR", "version": "2.7.11b", "fasta": f"{YEAST}/reference/genome.fasta",
                     "gtf": f"{YEAST}/reference/genes.gtf.gz"}
        self.write_info(self.info)
        self.params = {"fasta": f"{YEAST}/reference/genome.fasta", "gtf": f"{YEAST}/reference/genes.gtf.gz",
                       "star_index": self.index}

    def tearDown(self):
        shutil.rmtree(self.index)

    def write_info(self, info):
        json.dump(info, open(os.path.join(self.index, "geth_index.json"), "w"))

    def problems(self, pipeline="rnaseq", **change):
        return gc.check_params(pipeline, json.dumps(dict(self.params, **change)))[0]

    def test_registered_index_matching_the_plan_passes(self):
        self.assertEqual(self.problems(), [])
        self.assertEqual(self.problems("scrnaseq", aligner="star", protocol="10XV3"), [])

    def test_mismatches_are_refused(self):
        self.assertTrue(any("built from gtf" in p for p in self.problems(gtf=f"{YEAST}/reference/genome.fasta")))
        self.write_info(dict(self.info, version="2.7.10a"))
        self.assertTrue(any("STAR 2.7.10a" in p for p in self.problems()))
        os.remove(os.path.join(self.index, "geth_index.json"))
        self.assertTrue(any("registered in the reference catalogue" in p for p in self.problems()))

    def test_scrnaseq_index_needs_the_star_aligner(self):
        self.assertIn("param 'star_index' is only used with a STAR aligner (aligner is 'simpleaf')",
                      self.problems("scrnaseq", protocol="10XV3"))
        self.assertTrue(any("STAR aligner" in p for p in self.problems(aligner="hisat2")))


class RunFixes(unittest.TestCase):
    """Failures seen in the v1.6 benchmark runs (operator retries on test deliveries), replayed."""

    def setUp(self):
        self.run = Run("rnaseq", MISTRAL_SHEET, MISTRAL_PARAMS)
        gc.approve(self.run.dir, "tester")
        self.params = json.loads(MISTRAL_PARAMS)

    def tearDown(self):
        self.run.close()

    def fail(self, error, params=None):
        gc.record(self.run.dir, "nextflow", MISTRAL_SHEET, json.dumps(params or self.params), error)

    def gate(self, params=None, profile="", contrasts=""):
        return gc.gate(self.run.dir, "rnaseq", MISTRAL_SHEET, json.dumps(params or self.params), contrasts, profile)

    def test_samplesheet_rows_get_every_column(self):
        self.assertEqual(gc.normalise_sheet("sample,fastq_1,fastq_2,replicate\nA,/a.fq.gz,,1\nB,/b.fq.gz\n"),
                         "sample,fastq_1,fastq_2,replicate\nA,/a.fq.gz,,1\nB,/b.fq.gz,,\n")

    def test_skipping_the_step_named_by_the_error(self):
        self.fail("Process `NFCORE_RNASEQ:RNASEQ:QUALIMAP_RNASEQ (WT_REP1)` terminated with an error exit status (1)")
        self.assertEqual(self.gate(dict(self.params, skip_qualimap=True, skip_dupradar=True)),
                         [])  # both already true in the plan: unchanged
        allowed = dict(self.params, skip_rseqc=False)
        self.fail("Process `NFCORE_RNASEQ:RNASEQ:RSEQC_INFEREXPERIMENT` terminated")
        self.assertEqual(self.gate(dict(allowed, skip_rseqc=True)), [])
        self.assertTrue(self.gate(dict(self.params, skip_markduplicates=True)), "a step the error does not name")

    def test_no_analysis_profile_for_upstream_pipelines(self):
        self.assertTrue(any("takes no analysis profile" in p for p in self.gate(profile="roslin")))

    def test_a_third_identical_launch_is_refused(self):
        self.fail("Process `NFCORE_RNASEQ:RNASEQ:SALMON_QUANT` terminated (exit 140)")
        self.assertEqual(self.gate(), [], "one identical relaunch (resume) is allowed")
        self.fail("Process `NFCORE_RNASEQ:RNASEQ:SALMON_QUANT` terminated (exit 140)")
        self.assertTrue(any("already failed twice" in p for p in self.gate()))

    def test_parameters_describing_the_data_are_frozen(self):
        run = Run("nanoseq", "group,replicate,barcode,input_file,fasta,gtf\nKCMF1,1,6,,,\n",
                  json.dumps({"protocol": "DNA", "input_path": "/x.fastq.gz", "barcode_kit": "NBD103/NBD104"}))
        try:
            gc.approve(run.dir, "tester")
            gc.record(run.dir, "nextflow", run.read("plan_samplesheet.csv"), run.read("plan_params.json"),
                      "ERROR ~ Invalid protocol option if performing quantification: DNA")
            changed = json.dumps({"protocol": "cDNA", "input_path": "/x.fastq.gz", "barcode_kit": "NBD103/NBD104"})
            problems = gc.gate(run.dir, "nanoseq", run.read("plan_samplesheet.csv"), changed)
            self.assertTrue(any("'protocol' describes the data" in p for p in problems), problems)
            skip = json.dumps({"protocol": "DNA", "input_path": "/x.fastq.gz", "barcode_kit": "NBD103/NBD104",
                               "skip_quantification": True})
            self.assertEqual(gc.gate(run.dir, "nanoseq", run.read("plan_samplesheet.csv"), skip), [])
        finally:
            run.close()

    def test_geth_sets_the_profile_name_ampliseq_requires(self):
        self.assertEqual(gc.launch_params("ampliseq", {"primer_fwd": "ACGT"})["config_profile_name"], "Geth")
        self.assertNotIn("config_profile_name", gc.parse_params("config_profile_name=mine\nprimer_fwd=ACGT"))
        self.assertNotIn("config_profile_name", gc.launch_params("rnaseq", {}))

    def replay(self, pipeline, sheet, params, error, new_params):
        run = Run(pipeline, sheet, json.dumps(params))
        try:
            gc.approve(run.dir, "tester")
            gc.record(run.dir, "nextflow", sheet, json.dumps(params), error)
            return gc.gate(run.dir, pipeline, sheet, json.dumps(new_params))
        finally:
            run.close()

    def test_skipping_a_three_letter_step_named_by_the_error(self):
        sheet = "sample,run,group,short_reads_1,short_reads_2\nmouseA,0,0,/a_1.fastq.gz,/a_2.fastq.gz\n"
        params = {"skip_gtdbtk": True}
        ale = ("ERROR ~ Error executing process > 'NFCORE_MAG:MAG:ALE (MEGAHIT-mouseA)'\n"
               "Caused by:\n  Process `NFCORE_MAG:MAG:ALE (MEGAHIT-mouseA)` terminated with an error exit status (134)\n"
               "  ALE Output file: mouseA-MEGAHIT_ALEoutput.txt\n  cat <<-END_VERSIONS > versions.yml\n")
        self.assertEqual(self.replay("mag", sheet, params, ale, dict(params, skip_ale=True)), [])
        other = "Process `NFCORE_MAG:MAG:MEGAHIT (mouseA)` terminated: see mouseA-MEGAHIT_ALEoutput.txt, genes.gtf"
        self.assertTrue(self.replay("mag", sheet, params, other, dict(params, skip_ale=True)),
                        "ALE inside a file name does not name the step")
        self.assertFalse(gc.names_step("gtf", "reading /ref/genes.gtf"))
        self.assertFalse(gc.names_step("cat", "Error: x/cat.txt"))

    def test_fixes_for_a_file_named_by_the_error(self):
        sheet = "patient,sex,status,sample,lane,fastq_1,fastq_2\nred1,NA,0,red1,L001,/r_1.fastq.gz,/r_2.fastq.gz\n"
        vcf = "/refs/chicken/gallus_gallus.vcf.gz"
        params = {"tools": "haplotypecaller", "dbsnp": vcf, "known_indels": vcf}
        collision = ("ERROR ~ Error executing process > 'NFCORE_SAREK:SAREK:FASTQ_PREPROCESS_GATK:BAM_BASERECALIBRATOR:"
                     "GATK4_BASERECALIBRATOR (2)'\nCaused by:\n  Process `NFCORE_SAREK:SAREK:FASTQ_PREPROCESS_GATK:"
                     "BAM_BASERECALIBRATOR:GATK4_BASERECALIBRATOR` input file name collision -- There are multiple input "
                     "files for each of the following file names: gallus_gallus.vcf.gz, gallus_gallus.vcf.gz.tbi\n")
        no_indels = {k: v for k, v in params.items() if k != "known_indels"}
        self.assertEqual(self.replay("sarek", sheet, params, collision, no_indels), [])
        self.assertEqual(self.replay("sarek", sheet, params, collision, dict(params, skip_tools="baserecalibrator")), [])
        self.assertTrue(self.replay("sarek", sheet, params, collision, dict(params, skip_tools="baserecalibrator,mosdepth")),
                        "a tool the error does not name")
        self.assertTrue(self.replay("sarek", sheet, params, "Process `NFCORE_SAREK:SAREK:MOSDEPTH` terminated", no_indels),
                        "a file the error does not name")


class DifferentialAbundance(unittest.TestCase):

    def check(self, obs=OBS, params=DE_PARAMS, contrasts=CONTRASTS, profile="rnaseq", upstream=AIRWAY):
        problems, _ = gc.check_plan("differentialabundance", obs, params, contrasts, profile, upstream)
        return problems

    def test_textbook_plan_passes(self):
        self.assertEqual(self.check(), [])

    def test_samples_must_match_matrix(self):
        obs = OBS.replace("N61311_Dex", "N61311_dex")
        problems = self.check(obs=obs)
        self.assertTrue(any("not a column of the count matrix" in p for p in problems))
        self.assertTrue(any("has no row in the observations sheet" in p for p in problems))

    def test_unknown_level_and_missing_blocking(self):
        problems = self.check(contrasts=CONTRASTS.replace(",dex,donor", ",dexamethasone,batch"))
        self.assertTrue(any("target level 'dexamethasone'" in p for p in problems))
        self.assertTrue(any("blocking variable 'batch'" in p for p in problems))

    def test_profile_allowlist_and_upstream_gtf(self):
        problems = self.check(profile="rnaseq_magic", params=DE_PARAMS.replace(".116.gtf.gz", ".115.gtf.gz"))
        self.assertTrue(any("analysis profile" in p for p in problems))
        self.assertTrue(any("annotation used by the upstream run" in p for p in problems))

    def test_contrasts_rejected_for_upstream_pipelines(self):
        sheet = open(f"{AIRWAY}/plan_samplesheet.csv").read()
        problems, _ = gc.check_plan("rnaseq", sheet, open(f"{AIRWAY}/plan_params.json").read(), CONTRASTS)
        self.assertIn("nf-core/rnaseq takes no contrasts", problems)

    def test_gate_freezes_observations_contrasts_and_profile(self):
        run = Run("differentialabundance", OBS, DE_PARAMS, CONTRASTS, "rnaseq", AIRWAY)
        try:
            gc.approve(run.dir, "tester")
            self.assertEqual(gc.gate(run.dir, "differentialabundance", OBS, DE_PARAMS, CONTRASTS, "rnaseq"), [])
            swapped = CONTRASTS.replace("untreated,dex", "dex,untreated")
            self.assertTrue(gc.gate(run.dir, "differentialabundance", OBS, DE_PARAMS, swapped, "rnaseq"))
            relabelled = OBS.replace("N61311_Dex,dex", "N61311_Dex,untreated")
            self.assertTrue(any("condition of N61311_Dex" in p for p in
                                gc.gate(run.dir, "differentialabundance", relabelled, DE_PARAMS, CONTRASTS, "rnaseq")))
            self.assertTrue(gc.gate(run.dir, "differentialabundance", OBS, DE_PARAMS, CONTRASTS, "rnaseq_limma"))
            run.write("plan_contrasts.csv", swapped)
            self.assertTrue(any("changed after approval" in p for p in
                                gc.gate(run.dir, "differentialabundance", OBS, DE_PARAMS, swapped, "rnaseq")))
        finally:
            run.close()


class NewPipelines(unittest.TestCase):
    """sarek, isoseq, taxprofiler, mag: valid sheets pass, typical mistakes are caught."""

    @classmethod
    def setUpClass(cls):
        import gzip
        cls.d = tempfile.mkdtemp(prefix="geth_pipes_")
        for name in ("N_L1_R1.fastq.gz", "N_L1_R2.fastq.gz", "N_L2_R1.fastq.gz", "N_L2_R2.fastq.gz",
                     "T_L1_R1.fastq.gz", "T_L1_R2.fastq.gz", "S1_R1.fastq.gz", "S1_R2.fastq.gz", "S2_R1.fastq.gz",
                     "ont.fastq.gz"):
            with gzip.open(os.path.join(cls.d, name), "wt") as fh:
                fh.write("@r\nACGT\n+\nIIII\n")
        for name in ("genome.fa", "primers.fa", "run.subreads.bam", "run.subreads.bam.pbi", "run.ccs.bam"):
            open(os.path.join(cls.d, name), "w").write(">x\nACGT\n")
        k2 = os.path.join(cls.d, "k2.tar.gz")
        open(k2, "wb").write(b"placeholder")
        open(os.path.join(cls.d, "databases.csv"), "w").write(
            f"tool,db_name,db_params,db_type,db_path\nkraken2,k2,,short,{k2}\nbracken,k2,;-r 150,short,{k2}\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d)

    def f(self, name):
        return os.path.join(self.d, name)

    def check(self, pipeline, sheet, params):
        return gc.check_plan(pipeline, sheet, json.dumps(params))[0]

    def test_sarek(self):
        sheet = ("patient,sex,status,sample,lane,fastq_1,fastq_2\n"
                 f"P1,XX,0,P1_N,L1,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')}\n"
                 f"P1,XX,0,P1_N,L2,{self.f('N_L2_R1.fastq.gz')},{self.f('N_L2_R2.fastq.gz')}\n"
                 f"P1,XX,1,P1_T,L1,{self.f('T_L1_R1.fastq.gz')},{self.f('T_L1_R2.fastq.gz')}\n")
        ok = {"tools": "mutect2,strelka,manta", "fasta": self.f("genome.fa"), "igenomes_ignore": True,
              "skip_tools": "baserecalibrator"}
        self.assertEqual(self.check("sarek", sheet, ok), [])
        no_lane = sheet.replace(",L2,", ",,")
        self.assertTrue(any("'lane' is required" in p for p in self.check("sarek", no_lane, ok)))
        germline_only = sheet.replace("P1,XX,1,P1_T", "P1,XX,0,P1_T")
        self.assertTrue(any("no sample has status 1" in p for p in self.check("sarek", germline_only, ok)))
        self.assertTrue(any("'tools' value" in p for p in self.check("sarek", sheet, dict(ok, tools="haplotypecaller,gatk4"))))

    def test_sarek_livestock_germline(self):
        sheet = ("patient,sex,status,sample,lane,fastq_1,fastq_2\n"
                 f"red1,NA,0,red1,L001,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')}\n"
                 f"A191,NA,0,A191,L001,{self.f('N_L2_R1.fastq.gz')},{self.f('N_L2_R2.fastq.gz')}\n")
        cache = os.path.join(self.d, "vep_cache")
        os.makedirs(os.path.join(cache, "gallus_gallus", "116_GRCg7b"), exist_ok=True)
        vcf = self.f("known_variants.vcf.gz")
        with gzip.open(vcf, "wt") as fh:
            fh.write("##fileformat=VCFv4.2\n")
        ok = {"fasta": self.f("genome.fa"), "igenomes_ignore": True, "tools": "haplotypecaller,vep",
              "joint_germline": True, "dbsnp": vcf, "vep_cache": cache,
              "vep_species": "gallus_gallus", "vep_genome": "GRCg7b", "vep_cache_version": 116}
        self.assertEqual(self.check("sarek", sheet, ok), [])
        self.assertTrue(any("must be different files" in p for p in self.check("sarek", sheet, dict(ok, known_indels=vcf))))
        no_sites = {k: v for k, v in ok.items() if k != "dbsnp"}
        self.assertTrue(any("needs known sites" in p for p in self.check("sarek", sheet, no_sites)))
        self.assertEqual(self.check("sarek", sheet, dict(no_sites, skip_tools="baserecalibrator")), [])
        self.assertTrue(any("VEP cache folder not found" in p for p in self.check("sarek", sheet, dict(ok, vep_genome="GRCg6a"))))
        self.assertTrue(any("cannot index a gzip" in p for p in self.check("sarek", sheet, dict(ok, fasta=self.f("S1_R1.fastq.gz")))))
        self.assertTrue(any("needs vep_species" in p for p in
                            self.check("sarek", sheet, {k: v for k, v in ok.items() if k != "vep_species"})))

    def test_isoseq(self):
        sheet = ("sample,seq_data,pbi,start_from\n"
                 f"brain,{self.f('run.subreads.bam')},{self.f('run.subreads.bam.pbi')},ccs\n"
                 f"brain,{self.f('run.ccs.bam')},none,lima\n")
        ok = {"aligner": "minimap2", "fasta": self.f("genome.fa"), "primers": self.f("primers.fa"), "chunk_ccs": 5}
        self.assertEqual(self.check("isoseq", sheet, ok), [])
        self.assertTrue(any("set 'chunk_ccs' to 5 or fewer" in p for p in self.check("isoseq", sheet, dict(ok, chunk_ccs=40))))
        problems = self.check("isoseq", sheet.replace(self.f("run.subreads.bam.pbi"), "none"),
                              {"aligner": "ultra", "fasta": self.f("genome.fa")})
        text = "\n".join(problems)
        for expected in ("needs its .pbi", "needs a 'gtf'", "'primers'"):
            self.assertIn(expected, text)

    def test_taxprofiler(self):
        sheet = ("sample,run_accession,instrument_platform,fastq_1,fastq_2,fasta\n"
                 f"S1,S1_run1,ILLUMINA,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},\n"
                 f"S2,S2,ILLUMINA,{self.f('S2_R1.fastq.gz')},,\n")
        ok = {"databases": self.f("databases.csv"), "run_kraken2": True, "run_bracken": True,
              "perform_shortread_qc": True, "run_profile_standardisation": True}
        self.assertEqual(self.check("taxprofiler", sheet, ok), [])
        problems = self.check("taxprofiler", sheet.replace("S2,S2,", "S1,S1_run1,"), dict(ok, run_metaphlan=True))
        text = "\n".join(problems)
        self.assertIn("used twice", text)
        self.assertIn("no 'metaphlan' database", text)
        self.assertTrue(any("'databases' is required" in p for p in self.check("taxprofiler", sheet, {"run_kraken2": True})))
        mixed = sheet.replace("S2,S2,", "S1,S1_run2,")
        merging = dict(ok, perform_runmerging=True)
        self.assertTrue(any("mixes single-end short-read runs" in p for p in self.check("taxprofiler", mixed, merging)))
        self.assertEqual(self.check("taxprofiler", mixed, dict(merging, shortread_qc_mergepairs=True)), [])
        self.assertEqual(self.check("taxprofiler", mixed, ok), [], "no run merging: nothing to mix")
        long_reads = sheet.replace(f"S2,S2,ILLUMINA,{self.f('S2_R1.fastq.gz')},,",
                                   f"S1,S1_ont,OXFORD_NANOPORE,{self.f('ont.fastq.gz')},,")
        self.assertEqual(self.check("taxprofiler", long_reads, merging), [], "long reads are not single-end short reads")

    def test_taxprofiler_databases_and_memory(self):
        k2 = os.path.join(self.d, "k2db")
        os.makedirs(k2, exist_ok=True)
        open(os.path.join(k2, "hash.k2d"), "wb").write(b"\0" * 1000)
        open(os.path.join(k2, "database150mers.kmer_distrib"), "w").write("x\n")
        sheet_db = self.f("databases_real.csv")
        open(sheet_db, "w").write(f"tool,db_name,db_params,db_type,db_path\nkraken2,k2,,short,{k2}\nbracken,k2,;-r 150,short,{k2}\n")
        sheet = ("sample,run_accession,instrument_platform,fastq_1,fastq_2,fasta\n"
                 f"S1,S1_run1,ILLUMINA,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},\n")
        ok = {"databases": sheet_db, "run_kraken2": True, "run_bracken": True}
        self.assertEqual(self.check("taxprofiler", sheet, ok), [])
        open(sheet_db, "w").write(f"tool,db_name,db_params,db_type,db_path\nkraken2,k2,,short,{k2}\nbracken,k2,;-r 100,short,{k2}\n")
        self.assertTrue(any("no Bracken distribution for read length 100" in p for p in self.check("taxprofiler", sheet, ok)))
        self.assertIn("KRAKEN2_KRAKEN2", gc.extra_resources("taxprofiler", ok))
        self.assertEqual(gc.extra_resources("rnaseq", ok), "")
        self.assertEqual(gc.reference_bytes("taxprofiler", ok), 1000)

    def test_mag(self):
        sheet = ("sample,run,group,short_reads_1,short_reads_2,short_reads_platform,long_reads,long_reads_platform\n"
                 f"S1,1,G1,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},ILLUMINA,{self.f('ont.fastq.gz')},OXFORD_NANOPORE_HQ\n"
                 f"S2,1,G1,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')},ILLUMINA,,\n")
        ok = {"skip_gtdbtk": True, "skip_spades": True}
        self.assertEqual(self.check("mag", sheet, ok), [])
        self.assertTrue(any("GTDB-Tk would download" in p for p in self.check("mag", sheet, {"skip_spades": True})))
        bad = sheet.replace(",OXFORD_NANOPORE_HQ", ",").replace(f"{self.f('N_L1_R2.fastq.gz')}", "")
        text = "\n".join(self.check("mag", bad, dict(ok, coassemble_group=True)))
        for expected in ("'long_reads_platform' is required", "mixes single-end and paired-end", "binning_map_mode=group"):
            self.assertIn(expected, text)


class MorePipelines(NewPipelines):
    """ampliseq, chipseq, atacseq, nanoseq, eager, methylseq (reuses the dummy files of NewPipelines)."""

    def test_ampliseq(self):
        sheet = ("sample,fastq_1,fastq_2,run\n"
                 f"soil_A,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},run1\n"
                 f"soil_B,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')},run2\n")
        ok = {"primer_fwd": "GTGYCAGCMGCCGCGGTAA", "primer_rev": "GGACTACNVGGGTWTCTAAT", "dada_ref_taxonomy": "silva=138.2"}
        self.assertEqual(self.check("ampliseq", sheet, ok), [])
        text = "\n".join(self.check("ampliseq", sheet.replace("soil_B", "2-soil"), {"dada_ref_taxonomy": "silva=138.2"}))
        self.assertIn("must start with a letter", text)
        self.assertIn("'primer_fwd' and 'primer_rev' are required", text)

    def test_chipseq(self):
        head = "sample,fastq_1,fastq_2,replicate,antibody,control,control_replicate\n"
        sheet = (head + f"H3K27ac,{self.f('T_L1_R1.fastq.gz')},{self.f('T_L1_R2.fastq.gz')},1,H3K27ac,INPUT,1\n"
                 f"H3K27ac,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},2,H3K27ac,INPUT,1\n"
                 f"INPUT,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')},1,,,\n")
        ok = {"fasta": self.f("genome.fa"), "macs_gsize": 2.7e9, "read_length": 150}
        self.assertEqual(self.check("chipseq", sheet, ok), [])
        bad = sheet.replace(",2,H3K27ac,INPUT,1", ",3,H3K27ac,INPUT,2")
        text = "\n".join(self.check("chipseq", bad, {"fasta": self.f("genome.fa"), "read_length": 120}))
        for expected in ("numbered 1..N", "replicate '2' is not a row", "'macs_gsize'", "'read_length' must be one of"):
            self.assertIn(expected, text)

    def test_atacseq(self):
        sheet = ("sample,fastq_1,fastq_2,replicate\n"
                 f"WT,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},1\n"
                 f"WT,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')},2\n")
        ok = {"fasta": self.f("genome.fa"), "macs_gsize": 2.7e9, "read_length": 50, "narrow_peak": True}  # no MT contig
        self.assertEqual(self.check("atacseq", sheet, ok), [])
        self.assertTrue(any("numbered 1..N" in p for p in self.check("atacseq", sheet.replace(",2\n", ",3\n"), ok)))

    def test_nanoseq(self):
        sheet = ("group,replicate,barcode,input_file,fasta,gtf\n"
                 f"ctrl,1,,{self.f('ont.fastq.gz')},{self.f('genome.fa')},\n")
        ok = {"protocol": "cDNA", "skip_demultiplexing": True, "skip_quantification": True}
        self.assertEqual(self.check("nanoseq", sheet, ok), [])
        text = "\n".join(self.check("nanoseq", sheet, {"protocol": "RNA"}))
        self.assertIn("demultiplexing needs 'barcode'", text)
        self.assertIn("'protocol' must be DNA, cDNA or directRNA", text)

    def test_eager(self):
        head = "Sample_Name,Library_ID,Lane,Colour_Chemistry,SeqType,Organism,Strandedness,UDG_Treatment,R1,R2,BAM\n"
        sheet = (head + f"IND1,IND1_L1,1,4,PE,Homo sapiens,double,half,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},NA\n"
                 f"IND1,IND1_L1,2,2,SE,Homo sapiens,double,half,{self.f('S2_R1.fastq.gz')},NA,NA\n")
        ok = {"fasta": self.f("genome.fa"), "mapper": "bwaaln", "dedupper": "markduplicates"}
        self.assertEqual(self.check("eager", sheet, ok), [])
        bad = sheet.replace(",SE,Homo sapiens,double,half,", ",PE,Homo sapiens,double,quarter,").replace("IND1,IND1_L1,2", "IND2,IND1_L1,1")
        text = "\n".join(self.check("eager", bad, dict(ok, udg_type="half")))
        for expected in ("SeqType PE needs R2", "'UDG_Treatment' must be one of", "used by several samples", "'udg_type' must not be set"):
            self.assertIn(expected, text)

    def test_methylseq(self):
        sheet = f"sample,fastq_1,fastq_2\nliver,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')}\n"
        self.assertEqual(self.check("methylseq", sheet, {"fasta": self.f("genome.fa"), "em_seq": True}), [])
        text = "\n".join(self.check("methylseq", sheet, {"fasta": self.f("genome.fa"), "rrbs": True, "pbat": True, "taps": True}))
        self.assertIn("at most one library-prep preset", text)
        self.assertIn("aligner=bwamem", text)

    def test_atacseq_mito_name_is_a_reference_contig(self):
        fasta = self.f("yeast.fa")
        open(fasta, "w").write(">I\nACGT\n>MT\nACGT\n")
        sheet = f"sample,fastq_1,fastq_2,replicate\nWT,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},1\n"
        ok = {"fasta": fasta, "macs_gsize": 1.2e7, "read_length": 50, "narrow_peak": True, "mito_name": "MT"}
        self.assertEqual(self.check("atacseq", sheet, ok), [])
        self.assertTrue(any("its contigs are: I, MT" in p for p in self.check("atacseq", sheet, dict(ok, mito_name="M"))))
        unset = dict(ok); unset.pop("mito_name")
        self.assertTrue(any("set 'mito_name'" in p and "'MT'" in p for p in self.check("atacseq", sheet, unset)))
        self.assertEqual(self.check("atacseq", sheet, dict(unset, keep_mito=True)), [])

    def test_ampliseq_metadata_ids_are_sample_names(self):
        sheet = ("sample,fastq_1,fastq_2,run\n"
                 f"soil_A,{self.f('S1_R1.fastq.gz')},{self.f('S1_R2.fastq.gz')},run1\n"
                 f"soil_B,{self.f('N_L1_R1.fastq.gz')},{self.f('N_L1_R2.fastq.gz')},run2\n")
        meta = self.f("metadata.tsv")
        ok = {"primer_fwd": "GTGYCAGCMGCCGCGGTAA", "primer_rev": "GGACTACNVGGGTWTCTAAT", "metadata": meta,
              "metadata_category": "treatment"}
        open(meta, "w").write("ID\ttreatment\nsoil_A\tcontrol\nsoil_B\twarmed\n")
        self.assertEqual(self.check("ampliseq", sheet, ok), [])
        open(meta, "w").write("facility_id\ttreatment\n1\tcontrol\n2\twarmed\n")
        text = "\n".join(self.check("ampliseq", sheet, dict(ok, metadata_category="plot")))
        for expected in ("first column must be named 'ID'", "not found: 1, 2", "'plot' is not a column"):
            self.assertIn(expected, text)

    def test_nanoseq_barcode_kit_uses_qcat_names(self):
        sheet = "group,replicate,barcode,input_file,fasta,gtf\nKCMF1,1,6,,,\nKCMF1,2,12,,,\n"
        ok = {"protocol": "DNA", "input_path": self.f("ont.fastq.gz"), "barcode_kit": "NBD103/NBD104",
              "skip_quantification": True, "skip_fusion_analysis": True}
        self.assertEqual(self.check("nanoseq", sheet, ok), [])
        no_skips = {k: v for k, v in ok.items() if not k.startswith("skip_")}
        text = "\n".join(self.check("nanoseq", sheet, no_skips))
        self.assertIn("set 'skip_quantification=true'", text)
        self.assertIn("set 'skip_fusion_analysis=true'", text)
        self.assertTrue(any("qcat's kit names" in p for p in self.check("nanoseq", sheet, dict(ok, barcode_kit="EXP-NBD104"))))

    test_sarek = test_isoseq = test_taxprofiler = test_mag = None  # covered by NewPipelines
    test_sarek_livestock_germline = None


SC_SHEET = f"sample,h5ad\npbmc_1k_v3,{H5AD}\n"
SC_DESIGN = "\n".join([
    "qc.min_genes=200", "qc.max_pct_mt=20", "doublets.method=scrublet", "doublets.threshold=0.25",
    "leiden.resolutions=0.5,0.8,1.2", "leiden.chosen=0.8", "markers.panel=CD3E,CD8A,MS4A1,CD14,FCGR3A",
    f"annotation.model={MODEL}"])


class SingleCellDesign(unittest.TestCase):

    def test_valid_design_is_normalised(self):
        problems, design = gc.check_plan("sc_downstream", SC_SHEET, SC_DESIGN)
        self.assertEqual(problems, [])
        self.assertEqual(design["leiden.resolutions"], [0.5, 0.8, 1.2])
        self.assertEqual(design["markers.panel"][:2], ["CD3E", "CD8A"])

    def test_menu_ranges_and_consistency(self):
        bad = SC_DESIGN.replace("qc.max_pct_mt=20", "qc.max_pct_mt=150").replace("leiden.chosen=0.8", "leiden.chosen=2.0")
        bad += "\nhvg.flavor=seurat_v3\nqc.max_mito=10\nannotation.model=/tmp/model.pkl"
        problems, _ = gc.check_plan("sc_downstream", SC_SHEET, bad)
        text = "\n".join(problems)
        for expected in ("between 1 and 100", "'leiden.chosen' must be one of", "'hvg.flavor' must be one of",
                         "'qc.max_mito' is not on the menu", "reference catalogue"):
            self.assertIn(expected, text)

    def test_gate_one_justified_revision_of_tunable_keys(self):
        _, design = gc.check_plan("sc_downstream", SC_SHEET, SC_DESIGN)
        run = Run("sc_downstream", SC_SHEET, json.dumps(design))
        try:
            gc.approve(run.dir, "tester")
            revised = dict(design, **{"leiden.chosen": 1.2})
            self.assertTrue(gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(revised)), "must run approved first")
            self.assertEqual(gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(design)), [])
            gc.record(run.dir, "analysis", SC_SHEET, json.dumps(design), "cluster 9 has 51% CellTypist agreement")
            self.assertTrue(any("justification" in p for p in gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(revised))))
            revised["justification"] = "cluster 9 mixes two CellTypist labels (agreement 51%)"
            self.assertEqual(gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(revised)), [])
            frozen = dict(revised, **{"markers.panel": ["CD3E"]})
            self.assertTrue(any("not tunable" in p for p in gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(frozen))))
            gc.record(run.dir, "analysis", SC_SHEET, json.dumps(revised), "after revision")
            again = dict(revised, **{"leiden.chosen": 0.5})
            self.assertTrue(any("only one revision" in p for p in gc.gate(run.dir, "sc_downstream", SC_SHEET, json.dumps(again))))
            other = SC_SHEET.replace("pbmc_1k_v3,", "other,")
            self.assertTrue(any("design change" in p for p in gc.gate(run.dir, "sc_downstream", other, json.dumps(design))))
        finally:
            run.close()


if __name__ == "__main__":
    unittest.main()
