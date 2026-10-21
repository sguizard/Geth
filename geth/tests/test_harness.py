#!/usr/bin/env python3
"""Tests for Rannoch's agent loop (geth/harness) with a scripted model: no model service needed.

Run: python3 geth/tests/test_harness.py -v
"""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from harness.agent import Agent, Tool, load_skills, string_params  # noqa: E402
from harness.tools import list_files, read_text  # noqa: E402


def call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeClient:
    """Answers with the scripted assistant messages, in order; remembers what it was sent."""
    model = "fake"

    def __init__(self, *replies):
        self.replies, self.seen, self.usage = list(replies), [], {"requests": 0}

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        self.usage["requests"] += 1
        return self.replies.pop(0) if self.replies else {"content": "nothing more to say"}


def broken(**_):
    raise RuntimeError("disk on fire")


class AgentLoop(unittest.TestCase):

    def agent(self, client, max_turns=5):
        tools = [Tool("ECHO", "echo", string_params(text="t"), lambda text: f"echo: {text}"),
                 Tool("BROKEN", "fails", string_params(), broken),
                 Tool("SUBMIT", "final", string_params(answer="a"), lambda answer: answer, final=True)]
        return Agent("tester", "You test.", tools, client, max_turns=max_turns, log=lambda m: None)

    def test_tool_failures_come_back_as_text_and_the_final_tool_ends(self):
        client = FakeClient(
            {"content": "", "tool_calls": [call("BROKEN"), call("NOPE"), call("ECHO", wrong=1)]},
            {"content": "", "tool_calls": [{"id": "x", "function": {"name": "ECHO", "arguments": "{oops"}}]},
            {"content": "", "tool_calls": [call("SUBMIT", answer="not yet")]},
            {"content": "", "tool_calls": [call("SUBMIT", answer="OK: done")]})
        out = self.agent(client).run("go", done=lambda name, output: output.startswith("OK"))
        self.assertEqual(out, "OK: done")
        tool_msgs = [m["content"] for m in client.seen[1] if m["role"] == "tool"]
        self.assertIn("BROKEN failed: RuntimeError: disk on fire", tool_msgs[0])
        self.assertIn("no tool named 'NOPE'", tool_msgs[1])
        self.assertIn("wrong arguments for ECHO", tool_msgs[2])
        self.assertIn("not valid JSON", [m["content"] for m in client.seen[2] if m["role"] == "tool"][-1])
        self.assertEqual(client.usage["requests"], 4)  # a refused submission lets the agent go on

    def test_text_answers_are_nudged_and_turns_run_out(self):
        client = FakeClient(*[{"content": "I think I am done."}] * 10)
        out = self.agent(client, max_turns=3).run("go")
        self.assertIsNone(out)
        self.assertEqual(client.usage["requests"], 4)  # 3 turns + 1 last call
        self.assertIn("Call SUBMIT now", client.seen[-1][-1]["content"])
        self.assertIn("Use your tools", client.seen[1][-1]["content"])

    def test_skills_are_listed_and_loaded(self):
        folder = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(folder, "nfcore-x"))
            open(os.path.join(folder, "nfcore-x", "SKILL.md"), "w").write(
                "---\nname: nfcore-x\ndescription: How to plan X.\n---\n\n# X guide\nRule 1.\n")
            skills = load_skills(folder)
            self.assertEqual(skills["nfcore-x"], ("How to plan X.", "# X guide\nRule 1."))
            client = FakeClient({"content": "", "tool_calls": [call("activate_skill", skill_name="nfcore-x")]},
                                {"content": "", "tool_calls": [call("SUBMIT", answer="OK")]})
            agent = Agent("t", "You test.", [Tool("SUBMIT", "f", string_params(answer="a"), lambda answer: answer,
                                                  final=True)], client, skills=skills, log=lambda m: None)
            self.assertIn("- nfcore-x: How to plan X.", agent.instruction)
            agent.run("go")
            self.assertEqual(client.seen[1][-1]["content"], "# X guide\nRule 1.")
        finally:
            shutil.rmtree(folder)


class FileTools(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        d = os.path.join(self.root, "data", "delivery")
        for rel in ("README.txt", "fastq/a_R1.fastq.gz", "x/y/z.txt", "x/y/z/too_deep.txt"):
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
        open(os.path.join(d, "README.txt"), "w").write("Two samples.\n")
        with gzip.open(os.path.join(d, "fastq", "a_R1.fastq.gz"), "wt") as fh:
            fh.write("".join(f"line{i}\n" for i in range(20)))
        open(os.path.join(d, "x/y/z.txt"), "w").write("3 levels")
        open(os.path.join(d, "x/y/z/too_deep.txt"), "w").write("4 levels")
        self.data_root, self.d = os.path.join(self.root, "data"), d

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_list_files_like_find_maxdepth_3(self):
        out = list_files(self.data_root).func(dir=self.d)
        self.assertIn(f"{self.d}/README.txt\t13 bytes", out)
        self.assertIn(f"{self.d}/x/y/z.txt", out)
        self.assertNotIn("too_deep", out)
        self.assertTrue(list_files(self.data_root).func(dir="/etc").startswith("REFUSED"))
        self.assertTrue(list_files(self.data_root).func(dir=f"{self.d}/../../..").startswith("REFUSED"))

    def test_read_text(self):
        tool = read_text(self.data_root).func
        self.assertEqual(tool(path=f"{self.d}/README.txt"), "Two samples.\n")
        gz = tool(path=f"{self.d}/fastq/a_R1.fastq.gz")
        self.assertTrue(gz.startswith("(file type: gzip compressed data; first 8 lines"))
        self.assertIn("line7", gz)
        self.assertNotIn("line8", gz)
        self.assertTrue(tool(path="/etc/passwd").startswith("REFUSED"))


if __name__ == "__main__":
    unittest.main()
