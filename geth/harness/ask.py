"""Asking the scientist (Rannoch R3): the ASK_USER tool and who answers it.

- In a terminal: the questions appear a few at a time, each with options and a recommended answer (Enter takes
  it, a number picks an option, anything else is a free answer, '?' shows why the agent asks).
- With an answers file (detached runs, benchmarks): a stand-in for the scientist answers from that file, which
  holds what the scientist knows in plain words; what the file does not say is answered "I don't know".
- With neither: every question gets "no one is available", and the agent uses its recommendations.
Every question and answer is kept in the run folder (plan_questions.md), for the person who approves the plan.
"""
import json
import os
import re
import time

from .agent import Tool
from .prose import MAX_WIDTH, wrap

UNKNOWN = "I don't know: use your recommendation."
NOBODY = "No one is available to answer: use your recommendation, and say so in the rationale."


class TerminalAsker:
    who = "the scientist, in the terminal"

    def __init__(self, tty="/dev/tty"):
        self.tty = tty

    def __call__(self, questions):
        answers = []
        with open(self.tty, "r") as tin, open(self.tty, "w") as tout:
            try:  # the questions are wrapped to the terminal they are asked in (stdout is the log)
                width = max(60, min(MAX_WIDTH, os.get_terminal_size(tout.fileno()).columns - 1))
            except OSError:
                width = MAX_WIDTH
            say = lambda text="": (tout.write(text + "\n"), tout.flush())
            say(f"\n  Geth has {len(questions)} question(s) for you. Enter takes the recommended answer.")
            for i, q in enumerate(questions, 1):
                options = [str(o) for o in q.get("options") or []]
                rec = str(q.get("recommended") or "")
                say("\n" + wrap(f"[{i}/{len(questions)}] {q.get('question', '')}", indent=2, width=width))
                for k, o in enumerate(options, 1):
                    say(wrap(f"{k}. {o}{'  (recommended)' if o == rec else ''}", indent=6, width=width, whole=True))
                if rec and rec not in options:
                    say(wrap(f"recommended: {rec}", indent=6, width=width, whole=True, labels=True))
                while True:
                    tout.write("  > ")
                    tout.flush()
                    line = tin.readline()
                    if not line:  # end of input: nobody there any more
                        answer = NOBODY
                        break
                    line = line.strip()
                    if line == "?":
                        say(wrap(f"why: {q.get('why') or 'no reason given'}", indent=4, width=width))
                        continue
                    if not line:
                        answer = rec or UNKNOWN
                    elif line.isdigit() and 1 <= int(line) <= len(options):
                        answer = options[int(line) - 1]
                    else:
                        answer = line
                    break
                answers.append(answer)
            say("  Thanks: planning goes on.\n")
        return answers


class TerminalProgress:
    """What the planner is doing, one line per step, for the person at the terminal (the log has the details)."""

    def __init__(self, tty="/dev/tty"):
        self.out, self.t0, self.waiting = open(tty, "w"), time.time(), False

    def _line(self, text, end="\n"):
        s = int(time.time() - self.t0)
        self.out.write(f"\r\033[K  [{s // 60}:{s % 60:02d}] {text}{end}")
        self.out.flush()
        self.waiting = end != "\n"

    def thinking(self):
        self._line("thinking…", end="")

    def before(self, name, raw):
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {}
        base = lambda k: os.path.basename(str(args.get(k, "")).rstrip("/")) or str(args.get(k, ""))
        text = {"LIST_FILES": lambda: f"Listing {base('dir')}/",
                "READ_TEXT": lambda: f"Reading {base('path')}",
                "INSPECT_READS": lambda: f"Measuring the reads of {base('path')}",
                "LIST_REFERENCES": lambda: "Looking up the reference catalogue",
                "activate_skill": lambda: f"Loading the {args.get('skill_name', '')} guide",
                "PIPELINE_OPTIONS": lambda: f"Browsing the options of nf-core/{args.get('pipeline', '')}"
                                            + (f": {args['section']}" if args.get("section") else "")
                                            + (f" ('{args['search']}')" if args.get("search") else ""),
                "SC_INSPECT": lambda: f"Inspecting the cells of {base('h5ad')} (a scheduler job)",
                "CHECK_PLAN": lambda: "Checking the plan",
                "SUBMIT_PLAN": lambda: "Submitting the plan",
                "ASK_USER": lambda: "Asking you"}.get(name, lambda: name)()
        self.pending = text
        if name in ("CHECK_PLAN", "SUBMIT_PLAN"):
            self._line(text + " …", end="")  # completed by after()
        else:
            self._line(text)

    def after(self, name, output):
        if name not in ("CHECK_PLAN", "SUBMIT_PLAN"):
            return
        first = output.splitlines()[0] if output else ""
        if first.startswith("PLAN CHECK: OK"):
            verdict = "OK" if name == "CHECK_PLAN" else "OK, plan saved"
        else:
            problems = [l[2:] for l in output.splitlines() if l.startswith("- ")]
            verdict = f"{first.replace('PLAN CHECK: ', '')}" + (f": {problems[0][:90]}" if problems else "")
        self._line(f"{self.pending} → {verdict}")

    def close(self):
        if self.waiting:
            self.out.write("\r\033[K")
            self.out.flush()


class FileAnswerer:
    """A stand-in for the scientist: answers only from what the answers file says. It looks facts up, so the model's
    thinking is turned off (Qwen on ELM: 4 s instead of 83 s for the same answer), where the service allows it."""
    who = "the answers file"
    NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

    def __init__(self, path, client):
        self.facts, self.client, self.extra = open(path).read(), client, self.NO_THINKING

    def __call__(self, questions):
        listing = "\n".join(f"{i}. {q.get('question', '')} (options: {', '.join(map(str, q.get('options') or [])) or 'free answer'})"
                            for i, q in enumerate(questions, 1))
        request = [
            {"role": "system", "content": "You are the scientist who owns this sequencing data. Answer the analyst's "
             "questions using only what you know, written below. Answer each question completely: give every detail you "
             "know that concerns it, with names, values and sequences copied exactly; nothing else. When what you "
             "know does not answer a question, answer exactly: " + UNKNOWN +
             "\n\nWhat you know:\n" + self.facts},
            {"role": "user", "content": listing + "\n\nReply with a JSON list of strings: one answer per question, in order."}]
        try:
            message = self.client.chat(request, extra=self.extra)
        except Exception as e:  # a service that does not know the setting: ask again without it
            if not self.extra or "400" not in str(e):
                raise
            self.extra = None
            message = self.client.chat(request)
        text = message.get("content") or ""
        m = re.search(r"\[.*\]", text, re.S)
        try:
            answers = [str(a) for a in json.loads(m.group(0))] if m else []
        except json.JSONDecodeError:
            answers = []
        return (answers + [UNKNOWN] * len(questions))[:len(questions)]


class Nobody:
    who = "nobody"

    def __call__(self, questions):
        return [NOBODY] * len(questions)


def ask_tool(asker, transcript, max_rounds=2, max_questions=5):
    state = {"rounds": 0}

    def run(questions):
        if not isinstance(questions, list) or not questions:
            return "ERROR: give a list of questions"
        if state["rounds"] >= max_rounds:
            return (f"REFUSED: you have already asked {max_rounds} rounds of questions. Use what you know and your "
                    "recommendations; say in the rationale what you assumed.")
        questions = [q if isinstance(q, dict) else {"question": str(q)} for q in questions][:max_questions]
        state["rounds"] += 1
        answers = asker(questions)
        with open(transcript, "a") as fh:
            if os.path.getsize(transcript) == 0:
                fh.write("# Questions to the scientist\n")
            fh.write(f"\n## Round {state['rounds']} (answered by {asker.who})\n")
            for q, a in zip(questions, answers):
                fh.write(f"\n**{q.get('question', '')}**\n")
                if q.get("why"):
                    fh.write(f"- why: {q['why']}\n")
                if q.get("options"):
                    fh.write(f"- options: {'; '.join(map(str, q['options']))}\n")
                if q.get("recommended"):
                    fh.write(f"- recommended: {q['recommended']}\n")
                fh.write(f"- answer: {a}\n")
        return "\n".join(f"Q{i}: {q.get('question', '')}\nA{i}: {a}" for i, (q, a) in enumerate(zip(questions, answers), 1))

    item = {"type": "object", "required": ["question", "why", "options", "recommended"], "properties": {
        "question": {"type": "string", "description": "one question, about one thing"},
        "why": {"type": "string", "description": "why it matters for the analysis"},
        "options": {"type": "array", "items": {"type": "string"}, "description": "2 to 4 likely answers"},
        "recommended": {"type": "string", "description": "the answer you would choose, and use if nobody knows"}}}
    return Tool("ASK_USER", f"Ask the scientist what the data cannot tell you. At most {max_questions} questions per "
                f"round and {max_rounds} rounds: ask everything you need in one round when you can.",
                {"type": "object", "required": ["questions"],
                 "properties": {"questions": {"type": "array", "items": item}}}, run)
