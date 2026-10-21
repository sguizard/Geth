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

from .agent import Tool

UNKNOWN = "I don't know: use your recommendation."
NOBODY = "No one is available to answer: use your recommendation, and say so in the rationale."


class TerminalAsker:
    who = "the scientist, in the terminal"

    def __init__(self, tty="/dev/tty"):
        self.tty = tty

    def __call__(self, questions):
        answers = []
        with open(self.tty, "r") as tin, open(self.tty, "w") as tout:
            say = lambda text="": (tout.write(text + "\n"), tout.flush())
            say(f"\n  Geth has {len(questions)} question(s) for you. Enter takes the recommended answer.")
            for i, q in enumerate(questions, 1):
                options = [str(o) for o in q.get("options") or []]
                rec = str(q.get("recommended") or "")
                say(f"\n  [{i}/{len(questions)}] {q.get('question', '')}")
                for k, o in enumerate(options, 1):
                    say(f"      {k}. {o}{'   (recommended)' if o == rec else ''}")
                if rec and rec not in options:
                    say(f"      recommended: {rec}")
                while True:
                    tout.write("  > ")
                    tout.flush()
                    line = tin.readline()
                    if not line:  # end of input: nobody there any more
                        answer = NOBODY
                        break
                    line = line.strip()
                    if line == "?":
                        say(f"    why: {q.get('why') or 'no reason given'}")
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


class FileAnswerer:
    """A stand-in for the scientist: answers only from what the answers file says."""
    who = "the answers file"

    def __init__(self, path, client):
        self.facts, self.client = open(path).read(), client

    def __call__(self, questions):
        listing = "\n".join(f"{i}. {q.get('question', '')} (options: {', '.join(map(str, q.get('options') or [])) or 'free answer'})"
                            for i, q in enumerate(questions, 1))
        message = self.client.chat([
            {"role": "system", "content": "You are the scientist who owns this sequencing data. Answer the analyst's "
             "questions using only what you know, written below. Answer each question completely: give every detail you "
             "know that concerns it, with names, values and sequences copied exactly; nothing else. When what you "
             "know does not answer a question, answer exactly: " + UNKNOWN +
             "\n\nWhat you know:\n" + self.facts},
            {"role": "user", "content": listing + "\n\nReply with a JSON list of strings: one answer per question, in order."}])
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
