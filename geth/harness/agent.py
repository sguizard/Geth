"""Geth's agent loop (Rannoch): a model, a few tools, skills loaded on demand, budgets and a trace.

The loop is deliberately small. What makes an agent trustworthy stays outside it: the tools are Geth's checks
(geth_checks.py), and a plan only counts once the final tool has accepted it.
- A tool never kills the agent: any failure comes back to the model as text.
- The agent ends when its final tool accepts the answer, or when its turns run out (one last turn is offered
  to call the final tool).
- When a check refuses the same thing again and again, the agent is told to stop resubmitting and to ask or
  explain instead; if it still insists, the loop ends (a stuck agent spent 25 turns resubmitting one plan).
- Every request, answer and tool call goes to a JSON-lines trace (never the API key).
"""
import json
import os
import re
import time


class Tool:
    def __init__(self, name, description, parameters, func, final=False, check=False):
        self.name, self.description, self.parameters, self.func = name, description, parameters, func
        self.final, self.check = final, check  # final: its acceptance ends the loop; check: a refusal counts

    def spec(self):
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


def string_params(**fields):
    """JSON schema of an object whose fields are all required strings: {name: description}."""
    return {"type": "object", "properties": {k: {"type": "string", "description": v} for k, v in fields.items()},
            "required": list(fields)}


def load_skills(folder):
    """Skills: geth/skills/<name>/SKILL.md, with a name and description in their front matter."""
    skills = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        text = open(path).read()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
        head, body = (m.group(1), m.group(2)) if m else ("", text)
        desc = re.search(r"^description:\s*(.*)$", head, re.M)
        skills[name] = (desc.group(1).strip() if desc else "", body.strip())
    return skills


def skill_tool(skills):
    def activate(skill_name):
        if skill_name not in skills:
            return f"ERROR: no skill named '{skill_name}'. Skills: {', '.join(skills)}"
        return skills[skill_name][1]
    return Tool("activate_skill", "Load a skill: expert instructions for one task or pipeline. Load the skill of "
                "the pipeline you choose before planning it, and follow its rules exactly.",
                string_params(skill_name="the skill's name, from the list of skills"), activate)


class Agent:
    def __init__(self, name, instruction, tools, client, skills=None, max_turns=25, trace_path=None, log=print,
                 nudge_after=3, give_up_after=6, stuck_hint="", progress=None, text_answer=None):
        self.name, self.client, self.max_turns, self.log = name, client, max_turns, log
        # text_answer=(tool, argument, min_chars): a plain-text answer at least that long is handed to that tool,
        # rather than asking the model to write it all again as a tool call (a reporter's report: one minute each)
        self.text_answer = text_answer
        self.progress = progress  # optional: thinking(), before(name, args), after(name, output) for a person watching
        self.nudge_after, self.give_up_after, self.stuck_hint = nudge_after, give_up_after, stuck_hint
        self.tools = {t.name: t for t in tools}
        if skills:
            self.tools["activate_skill"] = skill_tool(skills)
            instruction += "\n\nSkills (load one with activate_skill):\n" + "\n".join(
                f"- {k}: {desc}" for k, (desc, _) in skills.items())
        self.final = [t.name for t in tools if t.final]
        self.instruction = instruction
        self.trace_path = trace_path

    def trace(self, **record):
        if self.trace_path:
            with open(self.trace_path, "a") as fh:
                fh.write(json.dumps(dict(time=round(time.time(), 3), agent=self.name, **record)) + "\n")

    def call_tool(self, call):
        name = call.get("function", {}).get("name", "")
        raw = call.get("function", {}).get("arguments") or "{}"
        tool = self.tools.get(name)
        if tool is None:
            return name, {}, f"ERROR: there is no tool named '{name}'. Tools: {', '.join(self.tools)}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as e:
            return name, {}, f"ERROR: the arguments are not valid JSON ({e}); call {name} again"
        try:
            return name, args, str(tool.func(**args))
        except TypeError as e:
            return name, args, f"ERROR: wrong arguments for {name} ({e}); expected {list(tool.parameters['properties'])}"
        except Exception as e:  # a tool never kills the agent
            return name, args, f"ERROR: {name} failed: {type(e).__name__}: {e}"

    def run(self, prompt, done=lambda name, output: True):
        """Run until a final tool's output satisfies done(name, output); returns that output, or None."""
        messages = [{"role": "system", "content": self.instruction}, {"role": "user", "content": prompt}]
        refused, streak = None, 0  # the last refusal of a check tool, and how many times in a row
        specs = [t.spec() for t in self.tools.values()]
        self.log(f"[agent {self.name}] model {self.client.model} · tools: {', '.join(self.tools)}")
        self.trace(event="start", model=self.client.model, tools=list(self.tools), prompt=prompt)
        for turn in range(1, self.max_turns + 2):
            if turn == self.max_turns + 1:
                messages.append({"role": "user", "content": f"You have used your {self.max_turns} turns. Call "
                                 f"{' or '.join(self.final)} now with your best answer."})
            if self.progress:
                self.progress.thinking()
            message = self.client.chat(messages, specs)
            calls = message.get("tool_calls") or []
            text = message.get("content") or ""
            # Only standard fields go back (some servers add reasoning fields they do not accept as input).
            messages.append({"role": "assistant", "content": text,
                             **({"tool_calls": calls} if calls else {})})
            self.trace(event="answer", turn=turn, content=text, tool_calls=calls, usage=dict(self.client.usage))
            if text.strip():
                self.log(f"[agent {self.name}] {text.strip()}")
            if not calls and self.text_answer and len(text.strip()) >= self.text_answer[2]:
                name, arg = self.text_answer[:2]
                output = self.call_tool({"function": {"name": name, "arguments": {arg: text}}})[2]
                self.log(f"[agent {self.name}]   → {name}(the answer's text)")
                self.trace(event="tool", turn=turn, name=name, arguments={arg: "(the answer's text)"}, output=output,
                           from_text=True)
                if name in self.final and done(name, output):
                    self.trace(event="end", turn=turn, usage=dict(self.client.usage))
                    self.log(f"[agent {self.name}] done in {turn} turn(s); usage: {self.client.usage}")
                    return output
                messages.append({"role": "user", "content": f"Your answer was handed to {name}, which says:\n{output}"})
                continue
            if not calls:
                messages.append({"role": "user", "content": "Use your tools to continue. When your answer is "
                                 f"ready and checked, call {' or '.join(self.final)}."})
                continue
            for call in calls:
                if self.progress:
                    self.progress.before(call.get("function", {}).get("name", ""), call.get("function", {}).get("arguments"))
                name, args, output = self.call_tool(call)
                if self.progress:
                    self.progress.after(name, output)
                self.log(f"[agent {self.name}]   → {name}({', '.join(f'{k}={str(v)[:60]!r}' for k, v in args.items())})")
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": output})
                self.trace(event="tool", turn=turn, name=name, arguments=args, output=output)
                passed = done(name, output)
                if name in self.final and passed:
                    self.trace(event="end", turn=turn, usage=dict(self.client.usage))
                    self.log(f"[agent {self.name}] done in {turn} turn(s); usage: {self.client.usage}")
                    return output
                tool = self.tools.get(name)
                if tool is not None and tool.check:
                    if passed:
                        refused, streak = None, 0
                    else:
                        streak = streak + 1 if output == refused else 1
                        refused = output
                        if streak == self.nudge_after:
                            messages.append({"role": "user", "content": f"The check has refused the same problems "
                                             f"{streak} times. Do not submit the same thing again: fix exactly what it "
                                             f"names. {self.stuck_hint}".strip()})
                            self.trace(event="nudge", turn=turn, streak=streak)
                        elif streak >= self.give_up_after:
                            self.trace(event="end", turn=turn, usage=dict(self.client.usage), finished=False, stuck=True)
                            self.log(f"[agent {self.name}] stopped: the check refused the same problems {streak} times")
                            return None
        self.trace(event="end", turn=self.max_turns + 1, usage=dict(self.client.usage), finished=False)
        self.log(f"[agent {self.name}] stopped without a final answer after {self.max_turns} turns")
        return None
