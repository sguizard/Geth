#!/usr/bin/env python3
"""Geth lab (EXPERIMENTAL): checks and bookkeeping for agent-designed single-cell analyses.

  lab_checks.py check-design <steps.txt> <statistics.txt> [<expected.txt> --save-checked <run_dir>]
      Check the FORMAT of a design (not its science, which the benchmark scores): every required step is
      present, each line has its five fields. A design that passes is kept in <run_dir>/.checked_design.
  lab_checks.py save-design <run_dir> <steps.txt> <statistics.txt> <expected.txt> <rationale.txt>
      Write the design files into the run folder, each marked EXPERIMENTAL. If the final answer fails the
      format check but a version passed during design, that version is used (the structured answer of the
      agent runtime sometimes drops fields).

A design is three lists of lines:
  steps:      <step> | <method> | <tool> | <key parameters> | <why>
  statistics: <comparison> | <unit of replication> | <test or model> | <design formula> | <multiple testing>
  expected:   free text, one expectation per line
"""
import os
import shutil
import sys

STEPS = ("qc", "doublets", "normalisation", "feature_selection", "dimensionality_reduction", "integration",
         "clustering", "annotation", "differential_expression")
BANNER = "# EXPERIMENTAL (Geth lab): agent-designed analysis, not for real analyses.\n"


def lines(text):
    return [l.strip() for l in (text or "").splitlines() if l.strip() and not l.strip().startswith("#")]


def check_design(steps_text, stats_text):
    problems, seen = [], []
    for i, line in enumerate(lines(steps_text), start=1):
        fields = [f.strip() for f in line.split("|")]
        if len(fields) != 5:
            problems.append(f"steps line {i}: needs 5 fields '<step> | <method> | <tool> | <key parameters> | <why>' (got {len(fields)})")
            continue
        if fields[0] not in STEPS:
            problems.append(f"steps line {i}: step '{fields[0]}' is not one of {', '.join(STEPS)}")
        seen.append(fields[0])
    for step in STEPS:
        if step not in seen:
            problems.append(f"step '{step}' is missing (write 'none' as the method if you decide to skip it, and why)")
    for i, line in enumerate(lines(stats_text), start=1):
        if len(line.split("|")) != 5:
            problems.append(f"statistics line {i}: needs 5 fields '<comparison> | <unit of replication> | <test or model> | "
                            f"<design formula> | <multiple testing>'")
    if not lines(stats_text):
        problems.append("statistics: at least one line (the comparison the question asks for)")
    return problems


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "check-design":
        problems = check_design(open(argv[2]).read(), open(argv[3]).read())
        if not problems and "--save-checked" in argv:
            keep = os.path.join(argv[argv.index("--save-checked") + 1], ".checked_design")
            os.makedirs(keep, exist_ok=True)
            for name, path in (("steps.txt", argv[2]), ("statistics.txt", argv[3]), ("expected.txt", argv[4])):
                shutil.copyfile(path, os.path.join(keep, name))
        print("DESIGN CHECK: OK" if not problems else f"DESIGN CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems))
        return 0
    if cmd == "save-design":
        run_dir = argv[2]
        steps, stats, expected, rationale = argv[3:7]
        note = ""
        keep = os.path.join(run_dir, ".checked_design")
        if check_design(open(steps).read(), open(stats).read()) and os.path.isdir(keep):
            steps, stats, expected = (os.path.join(keep, f) for f in ("steps.txt", "statistics.txt", "expected.txt"))
            note = "\n(Geth lab: the final answer lost part of the design; the last version that passed CHECK_DESIGN is used.)"
        for name, path in (("lab_design_steps.txt", steps), ("lab_design_statistics.txt", stats),
                           ("lab_design_expected.txt", expected), ("lab_design_rationale.txt", rationale)):
            open(os.path.join(run_dir, name), "w").write(BANNER + open(path).read().strip() + "\n")
        if note:
            open(os.path.join(run_dir, "lab_design_rationale.txt"), "a").write(note.strip() + "\n")
        problems = check_design(open(steps).read(), open(stats).read())
        result = "DESIGN CHECK: OK" if not problems else f"DESIGN CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems)
        open(os.path.join(run_dir, "lab_design_check.txt"), "w").write(result + "\n")
        print(result)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
