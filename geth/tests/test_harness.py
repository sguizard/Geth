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
from harness.ask import UNKNOWN, FileAnswerer, Nobody, TerminalProgress, ask_tool  # noqa: E402
from harness.llm import from_output, to_input  # noqa: E402
from harness.tools import list_files, pipeline_options, read_text  # noqa: E402


def call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class FakeClient:
    """Answers with the scripted assistant messages, in order; remembers what it was sent."""
    model = "fake"

    def __init__(self, *replies):
        self.replies, self.seen, self.extras, self.usage = list(replies), [], [], {"requests": 0}

    def chat(self, messages, tools=None, extra=None):
        self.seen.append([dict(m) for m in messages])
        self.extras.append(extra)
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


class Questions(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.transcript = os.path.join(self.dir, "plan_questions.md")
        open(self.transcript, "w").close()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_rounds_are_capped_and_kept_for_the_person_who_approves(self):
        q = {"question": "Which primers?", "why": "ampliseq trims them", "options": ["515F/806R", "341F/785R"],
             "recommended": "515F/806R"}
        tool = ask_tool(Nobody(), self.transcript, max_rounds=2, max_questions=2).func
        out = tool(questions=[q, q, q])
        self.assertEqual(out.count("Q"), 2 + out.count("Q3"))  # at most 2 questions per round
        self.assertIn("No one is available", out)
        tool(questions=[q])
        self.assertIn("REFUSED", tool(questions=[q]))
        text = open(self.transcript).read()
        self.assertIn("## Round 2 (answered by nobody)", text)
        self.assertIn("- recommended: 515F/806R", text)

    def test_file_answerer_answers_only_from_the_file(self):
        facts = os.path.join(self.dir, "answers.txt")
        open(facts, "w").write("Primers: 515F GTGYCAGCMGCCGCGGTAA and 806R GGACTACNVGGGTWTCTAAT.\n")
        client = FakeClient({"content": 'Here: ["515F GTGYCAGCMGCCGCGGTAA, 806R GGACTACNVGGGTWTCTAAT", "' + UNKNOWN + '"]'})
        answers = FileAnswerer(facts, client)([{"question": "Which primers?"}, {"question": "Which sequencer?"}])
        self.assertEqual(answers[1], UNKNOWN)
        self.assertIn("GTGYCAGCMGCCGCGGTAA", answers[0])
        self.assertIn("Primers: 515F", client.seen[0][0]["content"])  # the facts go to the stand-in only
        self.assertEqual(client.extras[0], {"chat_template_kwargs": {"enable_thinking": False}})  # a lookup: no thinking
        self.assertEqual(FileAnswerer(facts, FakeClient({"content": "no list"}))([{"question": "x"}]), [UNKNOWN])


class Options(unittest.TestCase):

    def test_sections_section_and_search(self):
        tool = pipeline_options().func
        self.assertIn("alignment_options", tool(pipeline="rnaseq"))
        self.assertNotIn("institutional_config_options", tool(pipeline="rnaseq"))
        self.assertIn("--aligner (string, default 'star_salmon'", tool(pipeline="rnaseq", section="alignment_options"))
        self.assertIn("--primer_fwd", tool(pipeline="ampliseq", search="primer"))
        self.assertNotIn("--outdir", tool(pipeline="rnaseq", section="input_output_options"))  # Geth sets it
        self.assertIn("No parameter schema", tool(pipeline="nope"))


class StuckGuard(unittest.TestCase):

    def test_same_refusal_nudges_then_stops(self):
        refusal = "PLAN CHECK: 1 problem(s)\n- db_path does not exist"
        submit = Tool("SUBMIT", "final", string_params(answer="a"), lambda answer: refusal, final=True, check=True)
        client = FakeClient(*[{"content": "", "tool_calls": [call("SUBMIT", answer="same")]}] * 10)
        agent = Agent("t", "You test.", [submit], client, max_turns=20, log=lambda m: None, stuck_hint="Ask the scientist.")
        self.assertIsNone(agent.run("go", done=lambda name, out: out.startswith("PLAN CHECK: OK")))
        self.assertEqual(client.usage["requests"], 6)  # stopped after 6 identical refusals, not 20 turns
        nudges = [m["content"] for m in client.seen[-1] if m["role"] == "user" and "refused the same" in m["content"]]
        self.assertEqual(len(nudges), 1)
        self.assertIn("Ask the scientist.", nudges[0])


class Progress(unittest.TestCase):

    def test_one_line_per_step_for_the_person_watching(self):
        out = tempfile.NamedTemporaryFile("w", delete=False)
        out.close()
        try:
            p = TerminalProgress(tty=out.name)
            p.thinking()
            p.before("READ_TEXT", json.dumps({"path": "/data/delivery/README.txt"}))
            p.before("activate_skill", {"skill_name": "nfcore-rnaseq"})
            p.thinking()
            p.before("CHECK_PLAN", "{}")
            p.after("CHECK_PLAN", "PLAN CHECK: 1 problem(s)\n- samplesheet line 2: 'fastq_1' is empty")
            p.before("SUBMIT_PLAN", "{}")
            p.after("SUBMIT_PLAN", "PLAN CHECK: OK")
            p.close()
            text = open(out.name).read()
            for expected in ("thinking…", "Reading README.txt", "Loading the nfcore-rnaseq guide",
                             "Checking the plan → 1 problem(s): samplesheet line 2: 'fastq_1' is empty",
                             "Submitting the plan → OK, plan saved"):
                self.assertIn(expected, text)
        finally:
            os.remove(out.name)


class Budget(unittest.TestCase):
    """A paid model's budget is a hard cap: the next request's input plus its longest answer must fit in it."""

    def test_a_request_that_could_cross_the_budget_is_not_sent(self):
        from harness.llm import Client, ModelError
        env = {"GETH_MODEL_MODEL": "paid", "GETH_MODEL_BASE_URL": "http://localhost:1", "GETH_MODEL_PRICES": "2,0.2,10",
               "GETH_MODEL_BUDGET_USD": "0.10", "GETH_MODEL_API_KEY_VAR": "TEST_KEY", "TEST_KEY": "x"}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            client = Client("GETH_MODEL")
            small = [{"role": "user", "content": "x" * 4000}]           # ~1,000 tokens: $0.002 of input
            self.assertAlmostEqual(client._room(small, None), 9800, delta=10)  # $0.098 left: ~9,800 output tokens
            client.usage["usd"] = 0.0995
            with self.assertRaises(ModelError):                          # room for 50 tokens only: not sent
                client._room(small, None)
            client.usage["usd"] = 0.0
            with self.assertRaises(ModelError):                          # 200,000 tokens of input: $0.40
                client._room([{"role": "user", "content": "x" * 800000}], None)
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.update({k: v})


class ResponsesApi(unittest.TestCase):
    """OpenAI's Responses API (GPT-6 refuses tools with reasoning in chat completions: the pilots of 2026-10-22)."""

    def test_answers_become_chat_messages_and_go_back_with_their_reasoning(self):
        output = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "SECRET"},
                  {"type": "function_call", "call_id": "call_1", "name": "READ_TEXT", "arguments": '{"path": "/d/README.txt"}',
                   "status": "completed", "id": "fc_1"},
                  {"type": "reasoning", "id": "rs_2", "summary": []}]  # no encrypted content: cannot go back
        message, keep = from_output(output)
        self.assertEqual(message["tool_calls"][0]["id"], "call_1")
        self.assertEqual(message["tool_calls"][0]["function"]["name"], "READ_TEXT")
        self.assertEqual([k.get("type") for k in keep], ["reasoning", "function_call"])
        self.assertNotIn("status", keep[1])
        messages = [{"role": "system", "content": "You plan."}, {"role": "user", "content": "go"},
                    {"role": "assistant", "content": "", "tool_calls": message["tool_calls"]},
                    {"role": "tool", "tool_call_id": "call_1", "content": "Two samples."},
                    {"role": "assistant", "content": "Done."}]  # an answer the client did not keep: rebuilt
        items = to_input(messages, [keep])
        self.assertEqual(items[2]["encrypted_content"], "SECRET")
        self.assertEqual(items[3]["type"], "function_call")
        self.assertEqual(items[4], {"type": "function_call_output", "call_id": "call_1", "output": "Two samples."})
        self.assertEqual(items[5], {"role": "assistant", "content": "Done."})
        text, _ = from_output([{"type": "message", "content": [{"type": "output_text", "text": "Plan ready."}]}])
        self.assertEqual(text, {"content": "Plan ready."})


if __name__ == "__main__":
    unittest.main()
