#!/usr/bin/env python3
"""Agents' text made readable for people: one sentence per line, wrapped to the terminal (at most 100 columns).

Agents write long paragraphs on one line (a plan's rationale, a coordinator's decision, a question). Geth shows them
through wrap(); the files keep what the agent wrote. Lists keep their marker with the text aligned under it, and
lines that look like tables or code are left as they are. Standard library only, and no import from the harness
package, so that bash can run it as a script and geth/bin can import it.

Usage: prose.py [--indent N] [--width N] [--whole] [--labels] < text
  --whole    wrap without breaking paragraphs into sentences (error messages, logs, pipe-separated lines)
  --labels   a leading "key: " (up to 30 characters) is a label: the text wraps aligned after it
"""
import argparse
import os
import re
import sys
import textwrap

MAX_WIDTH = 100
# A sentence ends at . ! or ? (perhaps followed by a closing bracket or quote), before a space and a capital or digit.
END = re.compile(r"[.!?][)\]\"']*\s+(?=[\"'(\[]?[A-Z0-9])")
# ... but not after an abbreviation or an initial.
ABBREVIATION = re.compile(r"(?:\b(?:e\.g|i\.e|etc|vs|cf|approx|ca|al|Fig|fig|no|No|vol|Dr|St)|(?<![\w.])[A-Z])\.[)\]\"']*$")
TABLE = re.compile(r"^\s*(?:\||\+-)|\t|\S {3,}\S")  # Markdown or column tables, tab-separated lines
MARKER = re.compile(r"^(?:[-*•]|\d{1,2}[.)]|->|\[\d+/\d+\]|[A-Za-z]{1,6}:)\s+")  # "- ", "1. ", "-> ", "[1/3] ", "Q: "
LABEL = re.compile(r"^[A-Za-z_][\w ()/'-]{0,29}:\s+")


def term_width(maximum=MAX_WIDTH):
    """The terminal's width (stdout, stderr or stdin), at most `maximum`; GETH_TEXT_WIDTH overrides it."""
    if os.environ.get("GETH_TEXT_WIDTH", "").isdigit():
        return max(40, int(os.environ["GETH_TEXT_WIDTH"]))
    for fd in (1, 2, 0):
        try:
            return max(60, min(maximum, os.get_terminal_size(fd).columns - 1))
        except OSError:
            continue
    return maximum


def sentences(text):
    """Split a paragraph into its sentences (conservatively: when in doubt, keep them together)."""
    parts, start = [], 0
    for m in END.finditer(text):
        if ABBREVIATION.search(text[start:m.start() + len(m.group(0).rstrip())]):  # up to the stop and its closers
            continue
        parts.append(text[start:m.end()].strip())
        start = m.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def wrap(text, indent=0, width=None, whole=False, labels=False, hang=2):
    """The text, wrapped for reading. indent: spaces before every line; hang: extra indent of a sentence's
    continuation lines (so that each sentence's start stands out)."""
    width = width or term_width()
    out, fenced = [], False
    for line in str(text).splitlines() or [""]:
        if line.strip().startswith("```"):
            fenced = not fenced
        if fenced or line.strip().startswith("```") or not line.strip() or TABLE.search(line):
            out.append(" " * indent + line if line.strip() else "")
            continue
        lead = " " * (indent + len(line) - len(line.lstrip()))
        body = line.strip()
        m = MARKER.match(body) or (LABEL.match(body) if labels else None)
        prefix = m.group(0) if m else ""
        rest = body[len(prefix):]
        pad = lead + " " * len(prefix)
        for i, s in enumerate([rest] if whole else sentences(rest)):
            out.extend(textwrap.wrap(s, width, initial_indent=(lead + prefix) if i == 0 else pad,
                                     subsequent_indent=pad + " " * hang,
                                     break_long_words=False, break_on_hyphens=False) or [lead + prefix])
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--indent", type=int, default=0)
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--whole", action="store_true")
    ap.add_argument("--labels", action="store_true")
    a = ap.parse_args()
    text = sys.stdin.read()
    if text.strip():
        print(wrap(text.rstrip("\n"), indent=a.indent, width=a.width or None, whole=a.whole, labels=a.labels))


if __name__ == "__main__":
    main()
