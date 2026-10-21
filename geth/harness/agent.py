"""Geth's agent loop (Rannoch): a model, a few tools, skills loaded on demand, budgets and a trace.

The loop is deliberately small. What makes an agent trustworthy stays outside it: the tools are Geth's checks
(geth_checks.py), and a plan only counts once the final tool has accepted it.
- A tool never kills the agent: any failure comes back to the model as text.
- The agent ends when its final tool accepts the answer, or when its turns run out (one last turn is offered
  to call the final tool).
- Every request, answer and tool call goes to a JSON-lines trace (never the API key).
"""
import json
import os
import re
import time


class Tool:
    def __init__(self, name, description, parameters, func, final=False):
        self.name, self.description, self.parameters, self.func, self.final = name, description, parameters, func, final

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
    def __init__(self, name, instruction, tools, client, skills=None, max_turns=25, trace_path=None, log=print):
        self.name, self.client, self.max_turns, self.log = name, client, max_turns, log
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
        specs = [t.spec() for t in self.tools.values()]
        self.log(f"[agent {self.name}] model {self.client.model} · tools: {', '.join(self.tools)}")
        self.trace(event="start", model=self.client.model, tools=list(self.tools), prompt=prompt)
        for turn in range(1, self.max_turns + 2):
            if turn == self.max_turns + 1:
                messages.append({"role": "user", "content": f"You have used your {self.max_turns} turns. Call "
                                 f"{' or '.join(self.final)} now with your best answer."})
            message = self.client.chat(messages, specs)
            calls = message.get("tool_calls") or []
            text = message.get("content") or ""
            # Only standard fields go back (some servers add reasoning fields they do not accept as input).
            messages.append({"role": "assistant", "content": text,
                             **({"tool_calls": calls} if calls else {})})
            self.trace(event="answer", turn=turn, content=text, tool_calls=calls, usage=dict(self.client.usage))
            if text.strip():
                self.log(f"[agent {self.name}] {text.strip()}")
            if not calls:
                messages.append({"role": "user", "content": "Use your tools to continue. When your answer is "
                                 f"ready and checked, call {' or '.join(self.final)}."})
                continue
            for call in calls:
                name, args, output = self.call_tool(call)
                self.log(f"[agent {self.name}]   → {name}({', '.join(f'{k}={str(v)[:60]!r}' for k, v in args.items())})")
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": output})
                self.trace(event="tool", turn=turn, name=name, arguments=args, output=output)
                if name in self.final and done(name, output):
                    self.trace(event="end", turn=turn, usage=dict(self.client.usage))
                    self.log(f"[agent {self.name}] done in {turn} turn(s); usage: {self.client.usage}")
                    return output
        self.trace(event="end", turn=self.max_turns + 1, usage=dict(self.client.usage), finished=False)
        self.log(f"[agent {self.name}] stopped without a final answer after {self.max_turns} turns")
        return None
