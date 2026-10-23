#!/usr/bin/env python3
"""Tests for Rannoch's operator and reporter (geth/harness/run.py) with a scripted model and a fake pipeline
launcher: no model service, no scheduler.

Run: python3 geth/tests/test_harness_run.py -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from harness import run  # noqa: E402
from test_harness import FakeClient, call  # noqa: E402

# A stand-in for run_nfcore.sh: one attempt per call; the pipeline completes when params.json says "ok": true.
FAKE_LAUNCHER = r'''#!/usr/bin/env bash
run_dir=$1; params=$4
n=$(( $(find "$run_dir" -maxdepth 1 -type d -name 'attempt_*' | wc -l) + 1 ))
mkdir -p "$run_dir/attempt_$n"
echo "ATTEMPT: $n"
if grep -q '"ok": true' "$params"; then
    echo "Pipeline completed successfully" > "$run_dir/attempt_$n/nextflow.log"
    echo "STATUS: SUCCESS"; echo "OUTDIR: $run_dir/results"
else
    echo "ERROR ~ out of memory in FASTQC" > "$run_dir/attempt_$n/nextflow.log"
    echo "STATUS: FAILED (exit 1)"; echo "ERROR ~ out of memory in FASTQC"
fi
'''


class RunHarness(unittest.TestCase):

    def setUp(self):
        self.runs = tempfile.mkdtemp()
        self.bin = tempfile.mkdtemp()
        self.d = os.path.join(self.runs, "demo")
        os.makedirs(self.d)
        files = {"APPROVED": "approved by tester\n", "question.txt": "Quantify expression.\n",
                 "plan_pipeline.txt": "rnaseq\n", "plan_samplesheet.csv": "sample,fastq_1\nA,/data/a.fq.gz\n",
                 "plan_params.json": '{"genome": "R64"}\n', "plan_rationale.txt": "One sample.\n"}
        for name, text in files.items():
            open(os.path.join(self.d, name), "w").write(text)
        open(os.path.join(self.bin, "run_nfcore.sh"), "w").write(FAKE_LAUNCHER)
        open(os.path.join(self.bin, "collect_results.py"), "w").write("print('| sample | reads |\\n| A | 1234 |')\n")
        self.saved = run.BIN, run.Client, run.check_report.check, os.environ.get("GETH_RUNS_DIR")
        run.BIN = self.bin
        os.environ["GETH_RUNS_DIR"] = self.runs
        # The report check, as check_report.check: numbers in the report other than 1234 are not traced.
        run.check_report.check = lambda report, *_: (
            ("REPORT CHECK: 1/2 numbers traced to the results; not traced: 99", ["99"], []) if "99" in report
            else ("REPORT CHECK: 1/1 numbers traced to the results", [], []))

    def tearDown(self):
        run.BIN, run.Client, run.check_report.check, runs = self.saved
        os.environ.pop("GETH_RUNS_DIR") if runs is None else os.environ.update(GETH_RUNS_DIR=runs)
        shutil.rmtree(self.runs)
        shutil.rmtree(self.bin)

    def go(self, *replies, report_only=False):
        client = FakeClient(*replies)
        run.Client = lambda *a, **k: client
        rc = run.main(["--run_dir", self.d] + (["--report_only"] if report_only else []))
        return rc, client

    def outcome(self):
        return open(os.path.join(self.d, "outcome.txt")).read()

    def tool_outputs(self, client):
        return [m["content"] for m in client.seen[-1] if m["role"] == "tool"]

    def test_a_fixed_failure_then_success_is_reported_with_its_change(self):
        rc, client = self.go(
            {"content": "", "tool_calls": [call("RUN_NFCORE", pipeline="rnaseq", samplesheet_csv="x", params_json='{"genome": "R64"}')]},
            {"content": "", "tool_calls": [call("RUN_NFCORE", pipeline="rnaseq", samplesheet_csv="x", params_json='{"ok": true}')]},
            {"content": "", "tool_calls": [call("SUBMIT_OUTCOME", succeeded=True, outdir="results",
                                                changes_to_plan=["more memory for FASTQC"], last_error="none")]},
            {"content": "", "tool_calls": [call("COLLECT_RESULTS", pipeline="nf-core/rnaseq")]},
            {"content": "", "tool_calls": [call("SUBMIT_REPORT", report="```markdown\n# Summary\nA has 1234 reads.\n```")]})
        self.assertEqual(rc, 0)
        self.assertIn("succeeded: true\nattempts: 2\n", self.outcome())
        self.assertIn("changes_to_plan: [more memory for FASTQC]\nannotations: []\n", self.outcome())
        report = open(os.path.join(self.d, "report.md")).read()
        self.assertEqual(report, "# Summary\nA has 1234 reads.\n")  # fences stripped, nothing to flag
        self.assertIn("| A | 1234 |", self.tool_outputs(client)[0])
        self.assertIn('"attempts": 2', client.seen[-1][1]["content"])  # the reporter is told the outcome

    def test_a_success_claim_on_a_failed_attempt_is_refused(self):
        rc, _ = self.go(
            {"content": "", "tool_calls": [call("RUN_NFCORE", pipeline="rnaseq", samplesheet_csv="x", params_json="{}")]},
            {"content": "", "tool_calls": [call("SUBMIT_OUTCOME", succeeded=True, outdir="results", changes_to_plan=[], last_error="none")]},
            {"content": "", "tool_calls": [call("SUBMIT_OUTCOME", succeeded=False, outdir="none", changes_to_plan=[],
                                                last_error="out of memory in FASTQC")]},
            {"content": "", "tool_calls": [call("SUBMIT_REPORT", report="# Summary\nThe run failed: out of memory.")]})
        self.assertEqual(rc, 1)
        self.assertIn("succeeded: false\nattempts: 1\n", self.outcome())
        self.assertIn("last_error: out of memory in FASTQC", self.outcome())

    def test_a_failure_claim_on_a_completed_attempt_is_refused(self):
        tool = run.submit_outcome_tool(self.d, {}, ["rnaseq"])
        os.makedirs(os.path.join(self.d, "attempt_1"))
        open(os.path.join(self.d, "attempt_1", "nextflow.log"), "w").write("Pipeline completed successfully\n")
        self.assertIn("REFUSED", tool.func(succeeded=False, outdir="none", changes_to_plan=[], last_error="x"))
        # an attempt ended by geth stop is not the last launched one
        os.makedirs(os.path.join(self.d, "attempt_2"))
        open(os.path.join(self.d, "attempt_2", "nextflow.log"), "w").write("killed\n")
        open(os.path.join(self.d, "attempt_2", "STOPPED"), "w").write("")
        self.assertEqual(run.last_attempt(self.d), os.path.join(self.d, "attempt_1"))

    def test_untraced_numbers_go_back_once_then_the_report_is_saved_with_a_note(self):
        open(os.path.join(self.d, "outcome.txt"), "w").write(
            "succeeded: true\nattempts: 1\noutdir: x\nchanges_to_plan: []\nannotations: []\nlast_error: none\n")
        rc, client = self.go(
            {"content": "", "tool_calls": [call("SUBMIT_REPORT", report="# Summary\n99 genes.")]},
            {"content": "", "tool_calls": [call("SUBMIT_REPORT", report="# Summary\nStill 99 genes.")]},
            report_only=True)
        self.assertEqual(rc, 0)
        first = [m["content"] for m in client.seen[1] if m["role"] == "tool"][0]
        self.assertTrue(first.startswith("NOT SAVED."), first)
        report = open(os.path.join(self.d, "report.md")).read()
        self.assertIn("Still 99 genes.", report)
        self.assertIn("**Automatic check:** these values could not be traced to the pipeline results and may be wrong: 99.", report)
        self.assertIn("not traced: 99", open(os.path.join(self.d, "report_check.txt")).read())

    def test_no_outcome_and_no_report_still_leave_the_truth_on_disk(self):
        rc, _ = self.go(*[{"content": "Thinking about it."}] * 30)
        self.assertEqual(rc, 1)
        self.assertIn("succeeded: false\nattempts: 0\n", self.outcome())
        self.assertIn("the operator ended without reporting an outcome", self.outcome())
        self.assertIn("did not write a report", open(os.path.join(self.d, "report.md")).read())
        self.assertIn("no report was written", open(os.path.join(self.d, "report_check.txt")).read())

    def test_the_analyst_runs_the_toolbox_and_its_annotations_are_kept(self):
        open(os.path.join(self.d, "plan_pipeline.txt"), "w").write("sc_downstream\n")
        open(os.path.join(self.d, "plan_params.json"), "w").write('{"resolutions": [0.5]}\n')
        jobs = []

        def fake_job(run_dir, task, path):  # the toolbox job: analysis_N, SUCCEEDED when it worked
            jobs.append((task, open(path).read()))
            out = os.path.join(run_dir, f"analysis_{len(jobs)}")
            os.makedirs(out)
            open(os.path.join(out, "SUCCEEDED"), "w").close()
            return f"STATUS: SUCCESS\nOUTDIR: {out}\nclusters: 2\nFLAGS: none"
        saved_job, run.sc_job = run.sc_job, fake_job
        try:
            rc, client = self.go(
                {"content": "", "tool_calls": [call("activate_skill", skill_name="sc-downstream")]},
                {"content": "", "tool_calls": [call("SC_ANALYSE", design='{"resolutions": [0.5]}')]},
                {"content": "", "tool_calls": [call("SAVE_ANNOTATIONS", annotations="cluster 0: B cell (MS4A1)\ncluster 1: NK (NKG7)")]},
                {"content": "", "tool_calls": [call("SUBMIT_OUTCOME", succeeded=True, outdir="analysis_1", changes_to_plan=[],
                                                    annotations=["cluster 0: B cell (MS4A1)", "cluster 1: NK (NKG7)"],
                                                    last_error="none")]},
                {"content": "", "tool_calls": [call("SUBMIT_REPORT", report="# Summary\nTwo clusters.")]})
        finally:
            run.sc_job = saved_job
        self.assertEqual(rc, 0)
        self.assertEqual(jobs, [("analyse", '{"resolutions": [0.5]}\n')])
        self.assertIn("annotations: [cluster 0: B cell (MS4A1), cluster 1: NK (NKG7)]", self.outcome())
        self.assertEqual(open(os.path.join(self.d, "annotations.txt")).read(), "cluster 0: B cell (MS4A1)\ncluster 1: NK (NKG7)\n")
        first = client.seen[0]
        self.assertIn("single-cell analyst", first[0]["content"])
        self.assertIn('{"resolutions": [0.5]}', first[1]["content"])

    def test_a_refused_revision_does_not_undo_a_successful_analysis(self):
        for n, ok in ((1, True), (2, False)):  # analysis_2: refused by the gate
            os.makedirs(os.path.join(self.d, f"analysis_{n}"))
            if ok:
                open(os.path.join(self.d, f"analysis_{n}", "SUCCEEDED"), "w").close()
        tool = run.submit_outcome_tool(self.d, {}, ["a", "b"], analyst=True)
        submit = lambda **k: tool.func(**dict(dict(changes_to_plan=[], last_error="none", annotations=[]), **k))
        self.assertIn("analysis_1 succeeded", submit(succeeded=False, outdir="none"))
        self.assertIn("OUTDIR must be the folder of an analysis", submit(succeeded=True, outdir=os.path.join(self.d, "analysis_2")))
        self.assertEqual(submit(succeeded=True, outdir=os.path.join(self.d, "analysis_1")), "OUTCOME SAVED")
        self.assertIn("succeeded: true\nattempts: 2\n", self.outcome())

    def test_the_approved_plan_runs_without_being_copied_and_a_text_report_is_submitted(self):
        report = "# Summary\nA has 1234 reads.\n\n" + "## Caveats\nTest data only.\n" * 30
        rc, client = self.go(
            {"content": "", "tool_calls": [call("RUN_NFCORE", pipeline="rnaseq")]},
            {"content": "", "tool_calls": [call("SUBMIT_OUTCOME", succeeded=False, outdir="none", changes_to_plan=[],
                                                last_error="out of memory in FASTQC")]},
            {"content": report})  # the reporter answers with the report itself
        self.assertEqual(open(os.path.join(self.d, ".harness", "samplesheet.csv")).read(), "sample,fastq_1\nA,/data/a.fq.gz\n")
        self.assertEqual(open(os.path.join(self.d, ".harness", "params.json")).read(), '{"genome": "R64"}\n')
        self.assertEqual(open(os.path.join(self.d, "report.md")).read(), report.strip() + "\n")
        self.assertEqual(client.usage["requests"], 3)  # no second writing of the report

    def test_outcome_txt_round_trip(self):
        outcome = {"succeeded": True, "attempts": 3, "outdir": "/r/results", "fixes_applied": ["a", "b"],
                   "annotations": [], "last_error": "none"}
        run.save_outcome(self.d, outcome)
        back = run.outcome_from_file(self.d)
        self.assertEqual(back["fixes_applied"], ["a, b"])  # one entry, as Geth 1.x read it
        self.assertEqual({k: back[k] for k in ("succeeded", "attempts", "outdir", "annotations", "last_error")},
                         {k: outcome[k] for k in ("succeeded", "attempts", "outdir", "annotations", "last_error")})

    def test_unapproved_plans_and_runs_outside_the_runs_folder_are_refused(self):
        os.remove(os.path.join(self.d, "APPROVED"))
        with self.assertRaises(SystemExit) as e:
            self.go()
        self.assertIn("has not been approved", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            run.main(["--run_dir", "/tmp/elsewhere"])
        self.assertIn("run_dir must be under", str(e.exception))


if __name__ == "__main__":
    unittest.main()
