#!/usr/bin/env python3
"""Check that every number and link in a Geth report can be traced to the run's facts.

Usage: check_report.py <report.md> <run_dir> <pipeline> <attempts>
Prints the report (fences stripped, plus a warning section when something cannot be traced)
and writes <run_dir>/report_check.txt.
Facts = collected results + approved plan + question + number of attempts + the error reports of the
attempts (a report on a failed run quotes them).
Small integers (<= 20) are not checked: they are counts of samples, files or attempts.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect_results import collect, raw_values  # noqa: E402

NUMBER = re.compile(r"(?<![\w.\-/])\d[\d,]*(?:\.\d+)?(?![\w/]|\.\d)")
URL = re.compile(r"https?://[^\s)>\]]+")
SCALES = (1, 100, 0.01, 1e-3, 1e-6)


def strip_fences(text):
    text = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.S)
    return m.group(1).strip() if m else text


def scrub(text):
    """Remove code spans, URLs, version strings and dates, which are not quantities; split ranges ("990-1,218",
    "83.5–85.4%") so that both ends are checked."""
    text = re.sub(r"`[^`]*`", " ", text)
    text = URL.sub(" ", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)
    text = re.sub(r"\d+\.\d+\.\d+", " ", text)
    return re.sub(r"(?<=\d)\s?[-–]\s?(?=\d)", " to ", text)


def numbers(text):
    out = []
    for m in NUMBER.finditer(text):
        token = m.group(0).rstrip(",")
        try:
            out.append((token, float(token.replace(",", ""))))
        except ValueError:
            pass
    return out


def traced(token, value, facts):
    decimals = len(token.split(".")[1]) if "." in token else 0
    for f in facts:
        for s in SCALES:
            if round(f * s, decimals) == value:
                return True
    return False


def check(report, run_dir, pipeline, attempts):
    """(summary line, untraced numbers, untraced links) of a report; writes nothing."""
    fact_text = collect(run_dir, pipeline) + f"\nattempts {attempts}\n"
    for f in ("question.txt", "plan_samplesheet.csv", "plan_params.json", "plan_rationale.txt"):
        p = os.path.join(run_dir, f)
        if os.path.isfile(p):
            fact_text += open(p).read() + "\n"
    for p in sorted(glob.glob(os.path.join(run_dir, "attempt_*", "error.txt"))):
        fact_text += open(p, errors="replace").read() + "\n"
    facts = {v for _, v in numbers(scrub(fact_text))} | set(raw_values(run_dir))

    checked, unverified = 0, []
    for token, value in numbers(scrub(report)):
        if value <= 20 and "." not in token:
            continue
        checked += 1
        if not traced(token, value, facts):
            unverified.append(token)
    links = [u for u in URL.findall(report) if u not in fact_text]

    summary = f"REPORT CHECK: {checked - len(unverified)}/{checked} numbers traced to the results"
    if unverified:
        summary += f"; not traced: {', '.join(sorted(set(unverified)))}"
    if links:
        summary += f"; untraced links: {', '.join(links)}"
    return summary, unverified, links


def main():  # check_report.py <report.raw.md> <run_dir> <pipeline> <attempts>: writes report_check.txt, prints the report
    report_path, run_dir, pipeline, attempts = sys.argv[1:5]
    report = strip_fences(open(report_path).read())
    summary, unverified, links = check(report, run_dir, pipeline, attempts)
    open(os.path.join(run_dir, "report_check.txt"), "w").write(summary + "\n")

    if unverified or links:
        report += ("\n\n---\n> **Automatic check:** these values could not be traced to the pipeline results "
                   "and may be wrong: " + ", ".join(sorted(set(unverified)) + links) + ".")
    print(report)


if __name__ == "__main__":
    main()
