#!/usr/bin/env python3
"""Tests for Geth projects (geth/bin/geth_project.py): the step check, approval, and the runner with stand-ins
for the geth commands and the coordinator. No model, network or scheduler.

Run: python3 geth/tests/test_project.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import geth_project as gp  # noqa: E402

COUNT = {"id": "count", "kind": "pipeline", "pipeline": "scrnaseq", "question": "Count the cells."}
CELLS = {"id": "cells", "kind": "pipeline", "pipeline": "sc_downstream", "question": "Find the cell types.", "after": ["count"]}
GAP = {"id": "de", "kind": "gap", "question": "Compare stimulated with control per cell type.",
       "suggestion": "pseudobulk DE per cell type, on the toolbox's h5ad"}


class Project(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.saved = gp.RUNS, gp.DATA_ROOT, gp.REFERENCES, gp.geth, gp.coordinate, gp.ensembl_files
        gp.RUNS, gp.DATA_ROOT, gp.REFERENCES = (os.path.join(self.root, x) for x in ("runs", "data", "refs"))
        self.data = os.path.join(gp.DATA_ROOT, "delivery")
        self.p = os.path.join(gp.RUNS, "projects", "demo")
        for d in (self.data, self.p, gp.REFERENCES):
            os.makedirs(d)
        open(os.path.join(self.data, "S1_R1.fastq.gz"), "w").write("reads")
        open(os.path.join(self.p, "data_dir.txt"), "w").write(self.data + "\n")
        open(os.path.join(self.p, "question.txt"), "w").write("Which cell types are there?\n")
        gp.save(os.path.join(self.p, "options.json"), {"lab": False})
        gp.ensembl_files = lambda sp, asm, rel: [("https://ftp/x.fa.gz", 4e6), ("https://ftp/x.gtf.gz", 1e6)]

    def tearDown(self):
        gp.RUNS, gp.DATA_ROOT, gp.REFERENCES, gp.geth, gp.coordinate, gp.ensembl_files = self.saved
        shutil.rmtree(self.root)

    def problems(self, *steps, started=()):
        return gp.check(self.p, {"steps": list(steps)}, started)[0]

    def test_a_chain_with_a_gap_passes(self):
        self.assertEqual(self.problems(COUNT, CELLS, GAP), [])

    def test_follow_ups_and_raw_pipelines_build_on_the_right_steps(self):
        self.assertIn("sc_downstream builds on one finished scrnaseq step", self.problems(dict(CELLS, after=[]))[0])
        rnaseq = {"id": "bulk", "kind": "pipeline", "pipeline": "rnaseq", "question": "Count."}
        self.assertIn("differentialabundance builds on one finished rnaseq step",
                      self.problems(COUNT, dict(CELLS, pipeline="differentialabundance"))[0])
        self.assertIn("runs on sequencing data", self.problems(COUNT, dict(rnaseq, after=["count"]))[0])
        self.assertIn("no step above", self.problems(dict(CELLS, after=["later"]), COUNT)[0])
        self.assertIn("is not a folder of the delivery", self.problems(dict(rnaseq, data="/etc"))[0])
        os.makedirs(os.path.join(self.data, "RNA"))
        open(os.path.join(self.data, "RNA", "S1_R1.fastq.gz"), "w").write("reads")
        doc = {"steps": [dict(rnaseq, data="RNA")]}
        self.assertEqual(gp.check(self.p, doc)[0], [])  # relative: inside the delivery
        self.assertEqual(doc["steps"][0]["data"], os.path.join(self.data, "RNA"))

    def test_what_geth_cannot_run_is_a_gap(self):
        self.assertIn("make this step a gap naming it", self.problems(dict(COUNT, pipeline="smrnaseq"))[0])
        self.assertEqual(self.problems(dict(GAP, nfcore="smrnaseq")), [])
        self.assertIn("nf-core has no pipeline named", self.problems(dict(GAP, nfcore="magicseq"))[0])
        self.assertIn("make this step a pipeline step", self.problems(dict(GAP, nfcore="rnaseq"))[0])
        self.assertIn("say what the gap is", self.problems(dict(GAP, suggestion=""))[0])

    def test_the_lab_only_when_allowed_and_from_a_count_matrix(self):
        lab = {"id": "custom", "kind": "lab", "question": "Per cell type DE.", "after": ["cells"]}
        self.assertIn("does not allow the lab", self.problems(COUNT, CELLS, lab)[0])
        gp.save(os.path.join(self.p, "options.json"), {"lab": True})
        self.assertEqual(self.problems(COUNT, CELLS, lab), [])
        self.assertIn("one .h5ad file", " ".join(self.problems(dict(lab, after=[]))))

    def test_reference_steps(self):
        genome = {"id": "genome", "kind": "reference", "question": "Mouse genome.", "species": "mus_musculus",
                  "assembly": "GRCm39", "release": "116"}
        problems, notes = gp.check(self.p, {"steps": [genome, dict(COUNT, after=["genome"])]})
        self.assertEqual(problems, [])
        self.assertIn("downloads 0.0 GB", notes[0])
        os.makedirs(gp.catalogue_entry(genome))
        self.assertIn("the catalogue already has", self.problems(genome)[0])
        self.assertIn("species (e.g. mus_musculus)", self.problems(dict(genome, release="latest"))[0])

    def test_no_download_when_the_delivery_brings_its_genome_and_one_folder_per_pipeline(self):
        genome = {"id": "genome", "kind": "reference", "question": "Yeast genome.", "species": "saccharomyces_cerevisiae",
                  "assembly": "R64-1-1", "release": "116"}
        os.makedirs(os.path.join(self.data, "RNA", "reference"))
        open(os.path.join(self.data, "RNA", "reference", "genome.fa"), "w").write(">chrI\nACGT\n")
        self.assertIn("the delivery brings its own genome", self.problems(genome)[0])
        rna = {"id": "rna", "kind": "pipeline", "pipeline": "rnaseq", "question": "Count."}
        atac = {"id": "atac", "kind": "pipeline", "pipeline": "atacseq", "question": "Peaks."}
        self.assertIn("both use", self.problems(rna, atac)[0])
        os.makedirs(os.path.join(self.data, "ATAC"))
        for kind in ("RNA", "ATAC"):
            open(os.path.join(self.data, kind, "S1_R1.fastq.gz"), "w").write("reads")
        self.assertEqual(self.problems(dict(rna, data="RNA"), dict(atac, data="ATAC")), [])
        os.makedirs(os.path.join(self.data, "RNA", "fastq"))
        open(os.path.join(self.data, "RNA", "README.txt"), "w").write("RNA-seq\n")
        self.assertIn("holds no README or sample table", self.problems(dict(rna, data="RNA/fastq"))[0])

    def test_a_pipeline_on_sequencing_data_needs_reads(self):
        os.makedirs(os.path.join(self.data, "matrix"))
        open(os.path.join(self.data, "matrix", "kang.h5ad"), "w").write("matrix")
        self.assertIn("needs sequencing reads", self.problems(dict(COUNT, data="matrix"))[0])

    def test_ids_size_and_started_steps(self):
        self.assertIn("is used twice", self.problems(COUNT, dict(COUNT))[0])
        self.assertIn("at most 8", self.problems(*[dict(GAP, id=f"g{i}") for i in range(9)])[0])
        gp.save(os.path.join(self.p, "steps.json"), {"steps": [COUNT, CELLS]})
        self.assertIn("has started", self.problems(dict(COUNT, question="Count again."), CELLS, started=["count"])[0])

    def test_approval_is_a_fingerprint(self):
        gp.save(os.path.join(self.p, "steps.json"), {"steps": [COUNT, CELLS]})
        self.assertEqual(gp.approve(self.p, "tester"), 0)
        self.assertIsNotNone(gp.approved_doc(self.p, quiet=True))
        gp.save(os.path.join(self.p, "steps.json"), {"steps": [COUNT]})  # edited after approval
        self.assertIsNone(gp.approved_doc(self.p, quiet=True))

    def fake_geth(self, *args, quiet=False, env=None):
        """The geth commands, as far as the runner sees them: folders and files."""
        self.calls.append(args)
        if args[0] == "plan":
            run = os.path.join(gp.RUNS, args[-1])
            os.makedirs(run)
            open(os.path.join(run, "plan_pipeline.txt"), "w").write("x\n")
        elif args[0] == "approve":
            open(os.path.join(gp.RUNS, args[1], "APPROVED"), "w").write("{}")
        elif args[:2] == ("lab", "design"):
            d = os.path.join(gp.RUNS, "lab", args[-1])
            os.makedirs(d)
            open(os.path.join(d, "lab_design_check.txt"), "w").write("DESIGN CHECK: OK\n")
            open(os.path.join(d, "lab_design_steps.txt"), "w").write("qc | ...\n")
        elif args[:2] == ("lab", "build"):
            d = os.path.join(gp.RUNS, "lab", args[-1])
            os.makedirs(d)
            open(os.path.join(d, "build_state.txt"), "w").write("done (review: approve)\n")
        elif args[0] == "run":
            ok = "true" if args[1] not in self.fail else "false"
            open(os.path.join(gp.RUNS, args[1], "outcome.txt"), "w").write(f"succeeded: {ok}\nattempts: 1\n")
        return 0

    def fake_coordinate(self, pdir, mode, step=""):
        self.calls.append(("coordinate", mode, step))
        if mode == "review":
            reviews = gp.load(os.path.join(pdir, "reviews.json"), {}) or {}
            reviews[step] = {"action": self.decisions.get(step, "continue"), "reason": "test"}
            gp.save(os.path.join(pdir, "reviews.json"), reviews)
        else:
            open(os.path.join(pdir, "report.md"), "w").write("# Project\n")
            open(os.path.join(pdir, "report_check.txt"), "w").write("REPORT CHECK: 0/0 numbers traced\n")
        return 0

    def start(self, *steps, decisions=None, fail=()):
        self.calls, self.decisions, self.fail = [], decisions or {}, fail
        gp.geth, gp.coordinate = self.fake_geth, self.fake_coordinate
        gp.save(os.path.join(self.p, "steps.json"), {"steps": list(steps)})
        self.assertEqual(gp.approve(self.p, "tester"), 0)

    def test_the_run_stops_for_each_plan_approval_and_resumes(self):
        self.start(COUNT, CELLS, GAP)
        self.assertEqual(gp.run(self.p), 2)  # step count planned: waiting for the person
        self.assertEqual(self.calls[0][0], "plan")
        self.assertIn(self.data, self.calls[0])
        open(os.path.join(gp.RUNS, "demo-count", "APPROVED"), "w").write("{}")  # the person approves
        self.assertEqual(gp.run(self.p), 2)  # count ran and was reviewed; cells planned from it
        self.assertIn(("coordinate", "review", "count"), self.calls)
        self.assertEqual(self.calls[-1][:3], ("plan", "--from", "demo-count"))
        open(os.path.join(gp.RUNS, "demo-cells", "APPROVED"), "w").write("{}")
        self.assertEqual(gp.run(self.p), 0)
        self.assertEqual(self.calls[-1], ("coordinate", "summary", ""))
        self.assertIn("step count: waiting", gp.read(os.path.join(self.p, "log.md")).replace("planned, waiting", "waiting"))

    def test_a_failed_step_stops_what_builds_on_it_and_the_coordinator_can_stop_or_revise(self):
        self.start(COUNT, CELLS, fail=("demo-count",))
        self.assertEqual(gp.run(self.p, auto=True), 0)
        self.assertFalse(os.path.isdir(os.path.join(gp.RUNS, "demo-cells")))
        self.assertIn("step cells: not started (it builds on count, not done)", gp.read(os.path.join(self.p, "log.md")))
        shutil.rmtree(os.path.join(gp.RUNS, "demo-count"))
        os.remove(os.path.join(self.p, "report.md"))
        os.remove(os.path.join(self.p, "reviews.json"))
        self.start(COUNT, CELLS, decisions={"count": "revise"})
        self.assertEqual(gp.run(self.p, auto=True), 3)


    def test_a_lab_step_starts_from_the_count_matrix_and_waits_for_its_design_approval(self):
        gp.save(os.path.join(self.p, "options.json"), {"lab": True})
        open(os.path.join(self.data, "kang.h5ad"), "w").write("matrix")
        open(os.path.join(self.data, "README.txt"), "w").write("PBMC, IFN-beta and control.\n")
        lab = {"id": "ifn", "kind": "lab", "question": "Which genes respond to IFN-beta per cell type?"}
        self.start(lab)
        self.assertEqual(gp.run(self.p), 2)  # the design waits for the person
        folder = os.path.join(self.p, "lab_ifn")
        self.assertEqual(sorted(os.listdir(folder)), ["README.txt", "kang.h5ad"])
        self.assertIn("PBMC, IFN-beta and control.", gp.read(os.path.join(folder, "README.txt")))
        self.assertEqual(self.calls[0][:3], ("lab", "design", folder))
        self.assertEqual(gp.approve_lab(self.p, "ifn", "tester"), 0)
        self.assertEqual(gp.run(self.p), 0)
        self.assertEqual(self.calls[1], ("lab", "build", "demo-ifn-design", "demo-ifn"))
        self.assertEqual(gp.status(self.p, lab), "done")


if __name__ == "__main__":
    unittest.main()
