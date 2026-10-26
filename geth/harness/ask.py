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
import threading
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
    """What an agent is doing, one line per step, for the person at the terminal (the log has the details).

    who: the agent's role, shown when several agents take turns (geth run, geth legion run). A long tool (a pipeline
    run, a scheduler job) keeps one line that is refreshed every 30 seconds with the time and, for a pipeline, its
    progress (watch(name): a short state, or ""). A check's verdict ends the line of the step that asked for it."""

    LONG = {"RUN_NFCORE", "SC_ANALYSE", "SC_INSPECT", "LAB_INSPECT", "TEST_STEP", "TEST_PIPELINE", "LINT_PIPELINE"}
    VERDICT = {"CHECK_PLAN", "SUBMIT_PLAN", "CHECK_STEPS", "SUBMIT_STEPS", "DECIDE", "SUBMIT_REPORT", "SUBMIT_OUTCOME",
               "RUN_NFCORE", "SC_ANALYSE", "SAVE_ANNOTATIONS", "CHECK_DESIGN", "SUBMIT_DESIGN", "WRITE_STEP", "TEST_STEP",
               "SAVE_SPEC", "WRITE_FILE", "LINT_PIPELINE", "TEST_PIPELINE", "SAVE_PIPELINE", "SUBMIT_NOTES", "SUBMIT_REVIEW"}

    def __init__(self, tty="/dev/tty", who="", watch=None, every=30):
        try:
            import signal  # a stage may run in the background of the terminal: its lines must not stop it
            signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        except (ValueError, OSError, AttributeError):
            pass
        try:
            self.out = open(tty, "w")
        except OSError:  # no terminal after all: say nothing
            self.out = None
        self.t0, self.waiting, self.who, self.watch, self.every = time.time(), False, who, watch, every
        self.pending, self.stop, self.lock = "", None, threading.Lock()

    def _line(self, text, end="\n"):
        if self.out is None:
            return
        s = int(time.time() - self.t0)
        clock = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
        line = f"  [{clock}] {self.who + ': ' if self.who else ''}{text}"
        if end != "\n":  # a line rewritten in place must fit the window: a wrapped one would leave its first rows
            try:
                width = os.get_terminal_size(self.out.fileno()).columns - 1
            except (OSError, ValueError):
                width = 0
            if 20 < width < len(line):
                line = line[:width - 1] + "…"
        with self.lock:
            self.out.write(f"\r\033[K{line}{end}")
            self.out.flush()
            self.waiting = end != "\n"

    def thinking(self):
        """Waiting for the model: the line keeps its clock running, and says so when the wait is long."""
        self._stop()
        self.pending, started = "thinking…", time.time()
        self._line(self.pending, end="")
        self._tick(None, lambda: "thinking…" + (f" (the model has been answering for {int(time.time() - started) // 60} min)"
                                                 if time.time() - started >= 120 else ""))

    def before(self, name, raw):
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {}
        args = args if isinstance(args, dict) else {}
        base = lambda k: os.path.basename(str(args.get(k, "")).rstrip("/")) or str(args.get(k, ""))
        changed = [k.split("_")[0] for k in ("samplesheet_csv", "params_json", "contrasts_csv", "profile") if args.get(k)]
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
                "ASK_USER": lambda: "Asking you",
                # the coordinator (geth legion)
                "LIST_CAPABILITIES": lambda: "Reading what Geth can run",
                "SEARCH_NFCORE": lambda: f"Searching nf-core for '{args.get('words', '')}'",
                "FIND_GENOME": lambda: f"Looking up the {args.get('species', '')} genome in Ensembl",
                "CHECK_STEPS": lambda: "Checking the steps",
                "SUBMIT_STEPS": lambda: "Submitting the steps",
                "READ_STEP": lambda: f"Reading step {args.get('step', '')}'s run",
                "DECIDE": lambda: "Deciding what happens next",
                # the operator, the analyst and the reporter (geth run)
                "RUN_NFCORE": lambda: f"Running nf-core/{str(args.get('pipeline', '')).replace('nf-core/', '')} "
                                      + (f"with a new {' and '.join(changed)}" if changed else "as approved"),
                "SC_ANALYSE": lambda: "Running the single-cell analysis (a scheduler job)",
                "SAVE_ANNOTATIONS": lambda: "Saving the cluster annotations",
                "SUBMIT_OUTCOME": lambda: "Reporting the outcome",
                "COLLECT_RESULTS": lambda: "Collecting the results",
                "SUBMIT_REPORT": lambda: "Submitting the report",
                # the lab
                "LAB_LIST_FILES": lambda: f"Listing {base('dir')}/",
                "LAB_READ_TEXT": lambda: f"Reading {base('path')}",
                "LAB_INSPECT": lambda: f"Inspecting {base('h5ad')} (a scheduler job)",
                "CHECK_DESIGN": lambda: "Checking the design",
                "SUBMIT_DESIGN": lambda: "Submitting the design",
                "WRITE_STEP": lambda: f"Writing step {args.get('name', '')}",
                "TEST_STEP": lambda: f"Testing step {args.get('name', '')} on the subset (a scheduler job)",
                "READ_BUILD": lambda: f"Reading {args.get('what', 'the build')}",
                "SAVE_SPEC": lambda: "Saving the spec",
                "WRITE_FILE": lambda: f"Writing {args.get('path_name', '')}",
                "LINT_PIPELINE": lambda: "Linting the pipeline (a scheduler job)",
                "TEST_PIPELINE": lambda: "Testing the pipeline on the subset (a scheduler job)",
                "READ_PROJECT": lambda: f"Reading {args.get('what', 'the project')}",
                "SAVE_PIPELINE": lambda: "Saving the pipeline",
                "SUBMIT_NOTES": lambda: "Handing over to the reviewer",
                "SUBMIT_REVIEW": lambda: f"Giving the verdict: {args.get('verdict', '')}"}.get(name, lambda: name)()
        self._stop()
        self.pending = text
        if name in self.VERDICT:
            self._line(text + " …", end="")  # completed by after()
            if name in self.LONG:
                self._tick(name)
        else:
            self._line(text)

    def _tick(self, name, render=None):
        """Refresh the waiting line (a long tool, or the model's answer) until the next step ends it."""
        self.stop = threading.Event()

        def run(stop=self.stop):
            while not stop.wait(self.every):
                try:
                    text = render() if render else f"{self.pending} … {self.watch(name) if self.watch else ''}".rstrip()
                except Exception:  # the progress line must never break the stage
                    text = self.pending
                if not stop.is_set():
                    self._line(text, end="")
        threading.Thread(target=run, daemon=True).start()

    def _stop(self):
        if self.stop:
            self.stop.set()
            self.stop = None

    @staticmethod
    def verdict(name, output):
        lines = [l.strip() for l in (output or "").strip().splitlines() if l.strip()]
        first = lines[0] if lines else "(no output)"
        status = next((l for l in lines if l.startswith("STATUS:")), "")
        problems = [l[2:] for l in lines if l.startswith("- ")]
        short = lambda t: t if len(t) <= 100 else t[:97] + "…"
        for check in ("PLAN CHECK: ", "STEP CHECK: ", "DESIGN CHECK: ", "SPEC CHECK: ", "PIPELINE CHECK: "):
            if first.startswith(check):
                if first.startswith(check + "OK"):
                    return {"SUBMIT_PLAN": "OK, plan saved", "SUBMIT_STEPS": "OK, steps saved",
                            "SUBMIT_DESIGN": "OK, design saved"}.get(name, "OK")
                return short(first.replace(check, "") + (f": {problems[0]}" if problems else ""))
        if status:
            if status.startswith("STATUS: SUCCESS"):
                return "success"
            error = next((l for l in lines if re.search(r"ERROR|Error|error", l) and not l.startswith("---")), "")
            return short(status.replace("STATUS: ", "").lower() + (f": {error}" if error else ""))
        if first.startswith(("REPORT SAVED. ", "NOT SAVED. ")):
            rest = first.split(". ", 1)[1].replace("REPORT CHECK: ", "")
            return short(("saved, " if first.startswith("REPORT") else "sent back to correct, ") + rest)
        if first.startswith("DECISION SAVED: "):
            return first.replace("DECISION SAVED: ", "")
        if first.startswith(("OUTCOME SAVED", "NOTES SAVED", "ANNOTATIONS SAVED")):
            return "saved"
        return short(first)

    def after(self, name, output):
        self._stop()
        if name not in self.VERDICT:
            return
        self._line(f"{self.pending} → {self.verdict(name, output)}")

    def close(self):
        self._stop()
        if self.out is not None and self.waiting:
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
