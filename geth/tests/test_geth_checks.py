#!/usr/bin/env python3
"""Regression tests for geth_checks.py, replaying real failures seen while building Geth.

Run: source env.sh; python3 geth/tests/test_geth_checks.py -v
Uses real files under $PERSEUS_VEIL (staged test data, the spike runs and the airway_1 results).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import geth_checks as gc  # noqa: E402

PV = os.environ.get("PERSEUS_VEIL", "/exports/eddie/scratch/sguizard/Perseus_Veil")
SPIKES = f"{PV}/spikes/nfcore/runs"
AIRWAY = f"{PV}/geth/runs/airway_1"
COUNTS = f"{AIRWAY}/results/star_salmon/salmon.merged.gene_counts.tsv"
LENGTHS = f"{AIRWAY}/results/star_salmon/salmon.merged.gene_lengths.tsv"
GTF = f"{PV}/references/homo_sapiens_GRCh38_ens116/Homo_sapiens.GRCh38.116.gtf.gz"

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


@unittest.skipUnless(os.path.isdir(SPIKES), "spike runs not available")
class UpstreamGate(unittest.TestCase):
    """v1.1 behaviour, replayed on the real Mistral failures from spike 3."""

    def setUp(self):
        src = f"{SPIKES}/full_bulk_mistral_1"
        self.src = src
        self.run = Run("rnaseq", open(f"{src}/plan_samplesheet.csv").read(), open(f"{src}/plan_params.json").read())
        gc.approve(self.run.dir, "tester")

    def tearDown(self):
        self.run.close()

    def test_unapproved_plan_is_refused(self):
        os.remove(self.run.path("APPROVED"))
        problems = gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.assertTrue(any("not been approved" in p for p in problems))

    def test_split_technical_replicate_is_refused(self):
        sheet = open(f"{self.src}/attempt_1/samplesheet.csv").read()
        problems = gc.gate(self.run.dir, "rnaseq", sheet, self.run.read("plan_params.json"))
        self.assertTrue(any("RAP1_uninduced_REP3" in p for p in problems), problems)

    def test_unrequested_params_are_refused_and_minimal_fix_allowed(self):
        problems, _ = gc.check_plan("rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.run.write("check.txt", "\n".join(problems))
        gc.record(self.run.dir, "check", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"), "\n".join(problems))
        mistral_fix = open(f"{self.src}/attempt_2/params.json").read()
        self.assertTrue(gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), mistral_fix))
        minimal = json.loads(self.run.read("plan_params.json"))
        minimal.pop("strandedness")
        self.assertEqual(gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), json.dumps(minimal)), [])

    def test_plan_edited_after_approval_is_refused(self):
        self.run.write("plan_params.json", self.run.read("plan_params.json") + "\n")
        problems = gc.gate(self.run.dir, "rnaseq", self.run.read("plan_samplesheet.csv"), self.run.read("plan_params.json"))
        self.assertTrue(any("changed after approval" in p for p in problems))


@unittest.skipUnless(os.path.isfile(COUNTS), "airway_1 results not available")
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


if __name__ == "__main__":
    unittest.main()
