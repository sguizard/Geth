#!/usr/bin/env python3
"""Tests for Geth lab's agents on Rannoch (geth/harness/lab.py) with a scripted model: the real design check and
bookkeeping (lab_checks.py, lab_build.py), no scheduler jobs.

Run: python3 geth/tests/test_harness_lab.py -v
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from harness import lab  # noqa: E402
from test_harness import FakeClient, call  # noqa: E402

STEPS = [f"{s} | method | tool | params | why" for s in
         ("qc", "doublets", "normalisation", "feature_selection", "dimensionality_reduction", "integration",
          "clustering", "annotation", "differential_expression")]
STATS = ["stim vs ctrl | donor | pseudobulk DESeq2 | ~donor+condition | BH"]


class LabHarness(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.data = os.path.join(self.root, "testdata", "kang")
        self.runs = os.path.join(self.root, "runs")
        self.d = os.path.join(self.runs, "lab", "demo")
        os.makedirs(self.data)
        os.makedirs(self.d)
        open(os.path.join(self.data, "README.txt"), "w").write("PBMC, stimulated and control.\n")
        open(os.path.join(self.data, "kang.h5ad"), "w").write("binary")
        self.env = {k: os.environ.get(k) for k in ("GETH_RUNS_DIR", "GETH_REFERENCES", "GETH_LAB_DATA")}
        os.environ.update(GETH_RUNS_DIR=self.runs, GETH_REFERENCES=os.path.join(self.root, "refs"),
                          GETH_LAB_DATA=os.path.join(self.root, "testdata"))
        self.saved = lab.model_client, lab.job
        self.jobs = []
        lab.job = lambda run_dir, task, *params: self.jobs.append((task, params)) or f"{task}: done"

    def tearDown(self):
        lab.model_client, lab.job = self.saved
        for k, v in self.env.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})
        shutil.rmtree(self.root)

    def go(self, mode, *replies, **args):
        client = FakeClient(*replies)
        lab.model_client = lambda *a, **k: client
        argv = ["--mode", mode, "--run_dir", self.d, "--data_dir", self.data]
        for k, v in args.items():
            argv += [f"--{k}", v]
        return lab.main(argv), client

    def outputs(self, client):
        return [m["content"] for m in client.seen[-1] if m["role"] == "tool"]

    def test_designer_checks_and_saves_its_design(self):
        rc, client = self.go(
            "design",
            {"content": "", "tool_calls": [call("LAB_LIST_FILES", dir="/etc"), call("LAB_LIST_FILES", dir=self.data),
                                           call("LAB_READ_TEXT", path=os.path.join(self.data, "kang.h5ad")),
                                           call("LAB_INSPECT", h5ad=os.path.join(self.data, "kang.h5ad"))]},
            {"content": "", "tool_calls": [call("CHECK_DESIGN", steps=STEPS[:3], statistics=STATS, expected=["x"])]},
            {"content": "", "tool_calls": [call("CHECK_DESIGN", steps=STEPS, statistics=STATS, expected=["ISG15 up"])]},
            {"content": "", "tool_calls": [call("SUBMIT_DESIGN", steps=STEPS, statistics=STATS, expected=["ISG15 up"],
                                                rationale="Pseudobulk per donor.")]},
            question="Which genes respond to interferon?", lab_skill="false")
        self.assertEqual(rc, 0)
        first = [m["content"] for m in client.seen[1] if m["role"] == "tool"]
        self.assertIn("REFUSED: the lab only lists benchmark folders", first[0])
        self.assertIn("README.txt", first[1])
        self.assertIn("REFUSED: binary file", first[2])
        self.assertEqual(self.jobs, [("inspect", ("--h5ad", os.path.join(self.data, "kang.h5ad")))])
        self.assertIn("DESIGN CHECK: 6 problem(s)", [m["content"] for m in client.seen[2] if m["role"] == "tool"][-1])
        self.assertEqual(open(os.path.join(self.d, "lab_design_check.txt")).read(), "DESIGN CHECK: OK\n")
        self.assertIn("pseudobulk DESeq2", open(os.path.join(self.d, "lab_design_statistics.txt")).read())
        self.assertEqual(open(os.path.join(self.d, "lab_arm.txt")).read(), "A0 design, no skill\n")
        self.assertNotIn("Skills (load one", client.seen[0][0]["content"])  # arm A0: no skill

    def save_design(self):
        for part, text in (("steps", STEPS), ("statistics", STATS), ("expected", ["ISG15 up"])):
            open(os.path.join(self.d, f"lab_design_{part}.txt"), "w").write("# EXPERIMENTAL\n" + "\n".join(text) + "\n")
        open(os.path.join(self.d, "question.txt"), "w").write("Which genes respond to interferon?\n")

    def test_engineer_notes_wait_for_a_checked_spec(self):
        self.save_design()
        rc, client = self.go(
            "engineer",
            {"content": "", "tool_calls": [call("SUBMIT_NOTES", notes=["qc: filters cells"])]},
            data_file=os.path.join(self.data, "kang.h5ad"), build_round="1")
        self.assertEqual(rc, 1)  # turns ran out: the notes were refused until the spec passes
        self.assertIn("REFUSED: nothing has passed SAVE_SPEC yet", [m["content"] for m in client.seen[1] if m["role"] == "tool"][-1])
        self.assertEqual(self.jobs[0], ("subset", ("--data_file", os.path.join(self.data, "kang.h5ad"))))
        self.assertIn("The subset for tests: subset: done", client.seen[0][1]["content"])
        self.assertIn("pseudobulk DESeq2", client.seen[0][1]["content"])  # the design, without its banner
        self.assertNotIn("EXPERIMENTAL\n", client.seen[0][1]["content"].split("The checked design:")[1].split("Review")[0])

    def test_reviewer_verdict_is_saved(self):
        self.save_design()
        rc, _ = self.go(
            "review",
            {"content": "", "tool_calls": [call("SUBMIT_REVIEW", verdict="maybe", issues=[])]},
            {"content": "", "tool_calls": [call("SUBMIT_REVIEW", verdict="revise", issues=["de: use donor as the unit"])]},
            build_round="1")
        self.assertEqual(rc, 0)
        self.assertEqual(open(os.path.join(self.d, "review_1.txt")).read(), "VERDICT: revise\n- de: use donor as the unit\n")

    def test_runs_outside_the_lab_and_data_outside_the_benchmarks_are_refused(self):
        with self.assertRaises(SystemExit) as e:
            lab.main(["--mode", "design", "--run_dir", os.path.join(self.runs, "demo"), "--data_dir", self.data])
        self.assertIn("run_dir must be under", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            lab.main(["--mode", "design", "--run_dir", self.d, "--data_dir", "/etc"])
        self.assertIn("only works on benchmark data", str(e.exception))


if __name__ == "__main__":
    unittest.main()
