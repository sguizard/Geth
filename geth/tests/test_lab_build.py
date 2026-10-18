#!/usr/bin/env python3
"""Tests for the lab's arm B bookkeeping (geth/lab/bin/lab_build.py) and the shell quoting of agent text.

Run: python3 geth/tests/test_lab_build.py -v      (no container, site configuration or data needed: sandbox
test runs are simulated by writing their test_meta.json)
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

LAB_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lab", "bin")
sys.path.insert(0, LAB_BIN)
import lab_build as lb  # noqa: E402

GOOD = "import sys\nimport scanpy as sc\na = sc.read_h5ad(sys.argv[1])\na.write_h5ad(sys.argv[2])\n"


def out(fn, *args, stdin=None):
    buf = io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin or "")
    try:
        with redirect_stdout(buf):
            fn(*args)
    finally:
        sys.stdin = old
    return buf.getvalue()


class Build(unittest.TestCase):

    def setUp(self):
        self.run = tempfile.mkdtemp(prefix="geth_build_")
        os.makedirs(os.path.join(self.run, "subset"))
        open(os.path.join(self.run, "subset", "output.h5ad"), "w").write("subset")
        open(os.path.join(self.run, "subset", "genes.txt"), "w").write("ISG15\nIFIT1\nMX1\nCD3E\n")

    def tearDown(self):
        shutil.rmtree(self.run)

    def sandbox_run(self, name, source, ok=True, summary="obs 'cell_type': 3 values", table=None):
        """What a sandbox test leaves behind (lab_build.test_step), without running the sandbox."""
        d = os.path.join(self.run, "test", name)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "output.h5ad"), "w").write(f"output of {name}")
        open(os.path.join(d, "summary.txt"), "w").write(summary)
        if table:
            open(os.path.join(d, table[0]), "w").write(table[1])
        json.dump({"step_sha": lb.sha(lb.step_path(self.run, name)), "input_from": source,
                   "input_sha": lb.sha(lb.input_of(self.run, source)), "exit": 0 if ok else 1},
                  open(os.path.join(d, "test_meta.json"), "w"))

    def write(self, name, code=GOOD):
        return out(lb.write_step, self.run, name, stdin=code)

    def test_write_step_names_and_static_check(self):
        self.assertIn("REFUSED", self.write("../etc"))
        self.assertIn("REFUSED", self.write("Bad-Name"))
        self.assertIn("STEP CHECK: OK", self.write("qc"))
        bad = self.write("net", "import sys, subprocess\nsubprocess.run(['curl', 'x'])\nprint(sys.argv[1])\n")
        self.assertIn("module 'subprocess' is not allowed", bad)
        self.assertIn("problem", self.write("path", GOOD + "open('/exports/x')\n"))

    def test_spec_needs_every_step_tested_in_order_on_current_code(self):
        tsv = ("de_results.tsv", "cell_type\tgene\tlog2fc\tpadj\nB\tISG15\t5\t0.001\n")
        self.write("qc")
        self.write("de", GOOD + "# de\n")
        self.sandbox_run("qc", "input")
        self.sandbox_run("de", "qc", table=tsv)
        spec = "qc | 4 | 32 | 60\nde | 2 | 16 | 30\n"
        self.assertIn("SPEC CHECK: OK", out(lb.check_spec, self.run, spec))
        self.assertIn("comes after 'input'", out(lb.check_spec, self.run, "de | 2 | 16 | 30\nqc | 4 | 32 | 60\n"))
        self.assertIn("memory must be between 1 and 64", out(lb.check_spec, self.run, "qc | 4 | 99 | 60\nde | 2 | 16 | 30\n"))
        self.write("qc", GOOD + "# changed after its test\n")
        self.assertIn("changed after its last test", out(lb.check_spec, self.run, spec))
        self.sandbox_run("qc", "input")  # qc tested again: de was tested on the older qc output
        open(os.path.join(self.run, "test", "qc", "output.h5ad"), "w").write("new output")
        self.assertIn("older output of 'qc'", out(lb.check_spec, self.run, spec))

    def test_spec_needs_the_results_contract(self):
        self.write("qc")
        self.sandbox_run("qc", "input", summary="obs 'leiden': 5 values")
        text = out(lb.check_spec, self.run, "qc | 2 | 8 | 10\n")
        self.assertIn("no obs['cell_type']", text)
        self.assertIn("no step wrote de_results.tsv or markers.tsv", text)
        self.sandbox_run("qc", "input", table=("markers.tsv", "cluster\tgene\tscore\n"))
        self.assertIn("lacks the columns", out(lb.check_spec, self.run, "qc | 2 | 8 | 10\n"))

    def test_read_stays_in_the_build(self):
        self.write("qc")
        self.sandbox_run("qc", "input", table=("markers.tsv", "cell_type\tgene\tlog2fc\tpadj\n"))
        self.assertIn("cell_type\tgene", out(lb.read, self.run, "file:qc/markers.tsv"))
        self.assertIn("REFUSED", out(lb.read, self.run, "file:qc/../../../etc/passwd"))
        self.assertIn("REFUSED", out(lb.read, self.run, "file:qc/output.h5ad"))
        os.symlink("/etc/hostname", os.path.join(self.run, "test", "qc", "link.txt"))
        self.assertIn("(no ", out(lb.read, self.run, "file:qc/link.txt"))
        self.assertIn("qc: STEP CHECK: OK; last test OK on 'input'", out(lb.read, self.run, "steps"))

    def test_render_runs_frozen_tested_code(self):
        tsv = ("markers.tsv", "cell_type\tgene\tlog2fc\tpadj\n")
        self.write("qc")
        self.write("annotate", GOOD + "# annotate\n")
        self.sandbox_run("qc", "input")
        self.sandbox_run("annotate", "qc", table=tsv)
        out(lb.check_spec, self.run, "qc | 4 | 32 | 60\nannotate | 2 | 16 | 30\n")
        out(lb.render, self.run, "/img.sif", "/models", "/data/x.h5ad")
        nf = open(os.path.join(self.run, "pipeline", "main.nf")).read()
        self.assertIn("S02_annotate(S01_qc.out.h5ad)", nf)
        self.assertIn(os.path.join(self.run, "pipeline", "steps", "qc.py"), nf)
        self.assertIn("--strict /img.sif", nf)
        self.write("qc", GOOD + "# edited after the spec\n")
        with self.assertRaises(SystemExit):
            out(lb.render, self.run, "/img.sif", "/models", "/data/x.h5ad")

    def test_review_is_saved_as_approve_or_revise(self):
        out(lb.save_review, self.run, "1", "approve", "")
        self.assertEqual(open(os.path.join(self.run, "review_1.txt")).read(), "VERDICT: approve\n")
        self.assertIn("REFUSED", out(lb.save_review, self.run, "2", "maybe", "x"))
        out(lb.save_review, self.run, "2", "maybe", "- de: contrast reversed\n", True)
        self.assertIn("VERDICT: revise\n- de: contrast reversed", open(os.path.join(self.run, "review_2.txt")).read())

    def test_record_does_not_overwrite_a_submitted_review(self):
        """The structured answer can leak the model's commentary ('The model failed to output valid JSON')."""
        out(lb.save_review, self.run, "1", "approve", "")
        text = out(lb.save_review, self.run, "1", "revise", "The model failed to output valid JSON\n", True)
        self.assertIn("already submitted", text)
        self.assertEqual(open(os.path.join(self.run, "review_1.txt")).read(), "VERDICT: approve\n")

    def test_results_contract_wants_symbols_and_cell_types(self):
        self.write("de")
        self.sandbox_run("de", "input", table=("de_results.tsv", "cell_type\tgene\tlog2fc\tpadj\nB\tENSG00000187608\t5\t0.001\n"))
        self.assertIn("gene symbols", out(lb.check_spec, self.run, "de | 2 | 8 | 10\n"))
        self.sandbox_run("de", "input", table=("de_results.tsv", "cell_type\tgene\tlog2fc\tpadj\n0\tISG15\t5\t0.001\n3\tMX1\t4\t0.01\n"))
        self.assertIn("holds numbers", out(lb.check_spec, self.run, "de | 2 | 8 | 10\n"))
        self.sandbox_run("de", "input", table=("de_results.tsv", "cell_type\tgene\tlog2fc\tpadj\nB cells\tISG15\t5\t0.001\n"))
        self.assertIn("SPEC CHECK: OK", out(lb.check_spec, self.run, "de | 2 | 8 | 10\n"))


class ShellQuoting(unittest.TestCase):
    """main.nf passes agent text as '<text>' with each ' replaced by '\\'' (Groovy: replace("'", "'\\\\''"))."""

    def test_hostile_text_is_data(self):
        work = tempfile.mkdtemp(prefix="geth_quote_")
        try:
            hostile = ("x = 1  # it's fine\n'; touch PWNED1; echo '\n$(touch PWNED2)\n`touch PWNED3`\n"
                       "GETH_EOF\n\\'\"; touch PWNED4 #\n")
            quoted = hostile.replace("'", "'\\''")
            script = f"printf '%s' '{quoted}' > received.txt\n"
            subprocess.run(["bash", "-c", script], cwd=work, check=True)
            self.assertEqual(open(os.path.join(work, "received.txt")).read(), hostile)
            self.assertEqual(sorted(f for f in os.listdir(work) if f.startswith("PWNED")), [])
        finally:
            shutil.rmtree(work)


if __name__ == "__main__":
    unittest.main()
