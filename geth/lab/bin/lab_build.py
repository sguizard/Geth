#!/usr/bin/env python3
"""Geth lab (EXPERIMENTAL), arm B bookkeeping: agent-written step scripts, their tests, the spec, the pipeline.

  lab_build.py write-step <run_dir> <name>            script (on stdin) -> steps/<name>.py + static check
  lab_build.py test-step <run_dir> <name> <from> <image> <models> <cpus>
                                                      run the step on the subset in the sandbox (an SGE task)
  lab_build.py check-spec <run_dir>                   spec (on stdin) -> build_spec.txt if every step
                                                      passed its test, in order, on its current code
  lab_build.py read <run_dir> <what>                  design | subset | spec | steps | step:<name> | test:<name> |
                                                      file:<name>/<file>
  lab_build.py save-review <run_dir> <round> <verdict>   issues (on stdin) -> review_<round>.txt
  lab_build.py render <run_dir> <image> <models> <data file>   pipeline/main.nf + nextflow.config from the spec

Agent text only reaches this script on stdin or as names checked against NAME, so it cannot change the
commands that run it. Every command prints its answer and exits 0, like every Geth tool.
"""
import hashlib
import csv
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab_step_check  # noqa: E402

NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
FILE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
CAPS = {"cpus": 8, "memory": 64, "minutes": 240}
RESULT_COLUMNS = {"cell_type", "gene", "log2fc", "padj"}
TEXT_TYPES = (".tsv", ".csv", ".txt", ".json", ".log")
HERE = os.path.dirname(os.path.abspath(__file__))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def stdin_text():
    return sys.stdin.read()


def log(run_dir, *fields):
    with open(os.path.join(run_dir, "build_log.tsv"), "a") as fh:
        fh.write("\t".join([time.strftime("%Y-%m-%dT%H:%M:%S")] + [str(f) for f in fields]) + "\n")


def step_path(run_dir, name):
    return os.path.join(run_dir, "steps", name + ".py")


def input_of(run_dir, source):
    if source == "input":
        return os.path.join(run_dir, "subset", "output.h5ad")
    return os.path.join(run_dir, "test", source, "output.h5ad")


def write_step(run_dir, name):
    if not NAME.match(name):
        return print("REFUSED: a step name is lower-case letters, digits and '_' (up to 40), starting with a letter")
    code = stdin_text()
    if not code.strip():
        return print("REFUSED: the script is empty")
    os.makedirs(os.path.join(run_dir, "steps"), exist_ok=True)
    path = step_path(run_dir, name)
    with open(path, "w") as fh:
        fh.write(code if code.endswith("\n") else code + "\n")
    problems = lab_step_check.check(path)
    report = "STEP CHECK: OK" if not problems else f"STEP CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems)
    with open(path[:-3] + ".check", "w") as fh:
        fh.write(report + "\n")
    log(run_dir, "write", name, "ok" if not problems else "refused", len(code.splitlines()))
    print(f"Saved steps/{name}.py ({len(code.splitlines())} lines).\n{report}")


def test_step(run_dir, name, source, image, models, cpus):
    if not NAME.match(name) or not (source == "input" or NAME.match(source)):
        return print("REFUSED: step names are lower-case letters, digits and '_'; the input is 'input' or a step name")
    path = step_path(run_dir, name)
    if not os.path.isfile(path):
        return print(f"REFUSED: no step '{name}': write it with WRITE_STEP first")
    check = open(path[:-3] + ".check").read() if os.path.isfile(path[:-3] + ".check") else ""
    if not check.startswith("STEP CHECK: OK"):
        return print(f"REFUSED: steps/{name}.py has not passed its check:\n{check}")
    src = input_of(run_dir, source)
    if not os.path.isfile(src):
        return print(f"REFUSED: no input '{source}': " + ("the subset is missing" if source == "input" else
                     f"step '{source}' has no successful test output yet"))
    out = os.path.join(run_dir, "test", name)
    if os.path.isdir(out):
        subprocess.run(["rm", "-rf", "--", out], check=False)
    os.makedirs(out)
    step_sha, input_sha = sha(path), sha(src)
    result = subprocess.run([os.path.join(HERE, "lab_sandbox.sh"), image, path, src, models, str(cpus), "20", out],
                            capture_output=True, text=True)
    text = "\n".join(l for l in (result.stdout + result.stderr).splitlines() if not l.startswith("INFO: "))
    m = re.search(r"SANDBOX EXIT: (\d+)", text)
    code = int(m.group(1)) if m else -1
    if code == 0 and not os.path.isfile(os.path.join(out, "output.h5ad")):
        code, text = -2, text + "\nThe step ended without writing its output AnnData (sys.argv[2])."
    with open(os.path.join(out, "test_meta.json"), "w") as fh:
        json.dump({"step_sha": step_sha, "input_from": source, "input_sha": input_sha, "exit": code}, fh)
    log(run_dir, "test", name, source, code)
    print(f"TEST of '{name}' on the subset (input: {source}): {'OK' if code == 0 else 'FAILED'}\n{text}"[:14000])


def parse_spec(text):
    rows, problems = [], []
    for i, line in enumerate([l for l in text.splitlines() if l.strip() and not l.startswith("#")], start=1):
        f = [x.strip() for x in line.split("|")]
        if len(f) != 4:
            problems.append(f"line {i}: write '<step> | <cpus> | <memory GB> | <minutes>'")
            continue
        try:
            row = {"step": f[0], "cpus": int(f[1]), "memory": int(re.sub(r"\s*GB$", "", f[2], flags=re.I)),
                   "minutes": int(f[3])}
        except ValueError:
            problems.append(f"line {i}: cpus, memory (GB) and minutes must be whole numbers")
            continue
        for k, cap in CAPS.items():
            if not 1 <= row[k] <= cap:
                problems.append(f"line {i}: {k} must be between 1 and {cap}")
        rows.append(row)
    return rows, problems


def check_spec(run_dir, text):
    rows, problems = parse_spec(text)
    if not rows and not problems:
        problems.append("the spec is empty")
    names = [r["step"] for r in rows]
    if len(set(names)) != len(names):
        problems.append("a step appears twice")
    for i, r in enumerate(rows):
        name, before = r["step"], ("input" if i == 0 else rows[i - 1]["step"])
        if not NAME.match(name) or not os.path.isfile(step_path(run_dir, name)):
            problems.append(f"'{name}': no such step")
            continue
        meta_path = os.path.join(run_dir, "test", name, "test_meta.json")
        meta = json.load(open(meta_path)) if os.path.isfile(meta_path) else {}
        if not meta:
            problems.append(f"'{name}' has not been tested")
        elif meta["exit"] != 0:
            problems.append(f"'{name}': its last test failed")
        elif meta["step_sha"] != sha(step_path(run_dir, name)):
            problems.append(f"'{name}' changed after its last test: test it again")
        elif meta["input_from"] != before:
            problems.append(f"'{name}' was tested on '{meta['input_from']}', but comes after '{before}' in the spec: test it on '{before}'")
        elif not os.path.isfile(input_of(run_dir, before)) or meta["input_sha"] != sha(input_of(run_dir, before)):
            problems.append(f"'{name}' was tested on an older output of '{before}': test it again")
    if rows and not problems:
        last = os.path.join(run_dir, "test", rows[-1]["step"], "summary.txt")
        if "obs 'cell_type'" not in (open(last).read() if os.path.isfile(last) else ""):
            problems.append("the last step's AnnData has no obs['cell_type'] (the annotation)")
        tables = [os.path.join(run_dir, "test", r["step"], t) for r in rows for t in ("de_results.tsv", "markers.tsv")]
        found = [t for t in tables if os.path.isfile(t)]
        if not found:
            problems.append("no step wrote de_results.tsv or markers.tsv")
        genes_file = os.path.join(run_dir, "subset", "genes.txt")
        known = set(open(genes_file).read().split()) if os.path.isfile(genes_file) else None
        for t in found:
            with open(t) as fh:
                table_rows = list(csv.DictReader(fh, delimiter="\t"))
            header = set(table_rows[0].keys()) if table_rows else set(open(t).readline().rstrip("\n").split("\t"))
            name = os.path.relpath(t, run_dir)
            if not RESULT_COLUMNS <= header:
                problems.append(f"{name} lacks the columns {', '.join(sorted(RESULT_COLUMNS - header))} (tab-separated)")
                continue
            genes = [r["gene"] for r in table_rows[:2000]]
            if known is not None and genes and sum(g in known for g in genes) < 0.5 * len(genes):
                problems.append(f"{name}: 'gene' must hold gene symbols, the var names (e.g. {sorted(known)[0]}); found e.g. {genes[0]}")
            labels = {r["cell_type"] for r in table_rows}
            if labels and all(re.fullmatch(r"\d+", l or "") for l in labels):
                problems.append(f"{name}: 'cell_type' holds numbers (cluster IDs?): put the cell-type label in cell_type "
                                "and the cluster in a 'cluster' column")
    if problems:
        log(run_dir, "spec", "refused", len(problems))
        return print(f"SPEC CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems))
    with open(os.path.join(run_dir, "build_spec.txt"), "w") as fh:
        fh.write("\n".join(f"{r['step']} | {r['cpus']} | {r['memory']} | {r['minutes']}" for r in rows) + "\n")
    log(run_dir, "spec", "ok", len(rows))
    print(f"SPEC CHECK: OK ({len(rows)} steps: {' -> '.join(names)})")


def read(run_dir, what):
    def text(path, limit=20000):
        if not os.path.isfile(path) or os.path.islink(path):
            return f"(no {os.path.relpath(path, run_dir)})"
        data = open(path, errors="replace").read()
        return data[:limit] + (f"\n[cut at {limit} characters]" if len(data) > limit else "")
    if what == "design":
        return print("\n\n".join(f"== {p}\n" + text(os.path.join(run_dir, f"lab_design_{p}.txt"))
                                 for p in ("steps", "statistics", "expected", "rationale")))
    if what == "subset":
        return print(text(os.path.join(run_dir, "subset", "summary.txt")))
    if what == "spec":
        return print(text(os.path.join(run_dir, "build_spec.txt")))
    if what == "steps":
        lines = []
        for f in sorted(os.listdir(os.path.join(run_dir, "steps"))) if os.path.isdir(os.path.join(run_dir, "steps")) else []:
            if f.endswith(".py"):
                name = f[:-3]
                check = text(os.path.join(run_dir, "steps", name + ".check")).splitlines()[0]
                meta_path = os.path.join(run_dir, "test", name, "test_meta.json")
                meta = json.load(open(meta_path)) if os.path.isfile(meta_path) else {}
                tested = "not tested" if not meta else f"last test {'OK' if meta['exit'] == 0 else 'FAILED'} on '{meta['input_from']}'"
                lines.append(f"{name}: {check}; {tested}")
        return print("\n".join(lines) or "(no steps yet)")
    m = re.match(r"^(step|test|file):(.+)$", what)
    if m and m.group(1) == "step" and NAME.match(m.group(2)):
        return print(text(step_path(run_dir, m.group(2))))
    if m and m.group(1) == "test" and NAME.match(m.group(2)):
        d = os.path.join(run_dir, "test", m.group(2))
        return print(f"== log (last 80 lines)\n" + "\n".join(text(os.path.join(d, "step_log.txt")).splitlines()[-80:])
                     + "\n\n== outputs\n" + text(os.path.join(d, "summary.txt")))
    if m and m.group(1) == "file":
        parts = m.group(2).split("/", 1)
        if len(parts) == 2 and NAME.match(parts[0]) and FILE.match(parts[1]) and ".." not in parts[1] \
                and parts[1].endswith(TEXT_TYPES):
            return print(text(os.path.join(run_dir, "test", parts[0], parts[1])))
    print("REFUSED: read 'design', 'spec', 'steps', 'step:<name>', 'test:<name>' or 'file:<name>/<table>' "
          f"(text files: {', '.join(TEXT_TYPES)})")


def save_review(run_dir, round_, verdict, issues, fallback=False):
    """The reviewer submits its verdict with SUBMIT_REVIEW; the final structured answer is only a fallback,
    because turning a long answer into a record can leak the model's own commentary into the issues."""
    path = os.path.join(run_dir, f"review_{round_}.txt")
    if fallback and os.path.isfile(path):
        log(run_dir, "review-record", round_, "ignored (submitted by tool)")
        return print("Review already submitted with SUBMIT_REVIEW:\n" + open(path).read())
    verdict = verdict.strip().lower()
    if not fallback and verdict not in ("approve", "revise"):
        return print("REFUSED: the verdict is 'approve' or 'revise'")
    verdict = verdict if verdict in ("approve", "revise") else "revise"
    lines = [l.strip().lstrip("-* ").strip() for l in issues.splitlines() if l.strip()]
    if verdict == "revise" and not lines:
        lines = ["(the reviewer asked for changes without naming them)"]
    with open(path, "w") as fh:
        fh.write(f"VERDICT: {verdict}\n" + "".join(f"- {l}\n" for l in lines))
    log(run_dir, "review", round_, verdict, len(lines), "record" if fallback else "tool")
    print(f"VERDICT: {verdict} ({len(lines)} issue(s))")


def render(run_dir, image, models, data_file):
    rows, problems = parse_spec(open(os.path.join(run_dir, "build_spec.txt")).read())
    if problems:
        sys.exit("build_spec.txt is invalid: " + "; ".join(problems))
    sandbox = os.path.join(HERE, "lab_sandbox.sh")
    pipe = os.path.join(run_dir, "pipeline")
    os.makedirs(os.path.join(pipe, "steps"), exist_ok=True)
    for r in rows:  # the pipeline runs a frozen copy of exactly the code that passed its test
        meta = json.load(open(os.path.join(run_dir, "test", r["step"], "test_meta.json")))
        code = open(step_path(run_dir, r["step"]), "rb").read()
        if hashlib.sha256(code).hexdigest() != meta["step_sha"] or meta["exit"] != 0:
            sys.exit(f"steps/{r['step']}.py is not the code that passed its test: check the spec again")
        with open(os.path.join(pipe, "steps", r["step"] + ".py"), "wb") as fh:
            fh.write(code)
    procs, calls = [], []
    for i, r in enumerate(rows, start=1):
        proc = f"S{i:02d}_{r['step']}"
        procs.append(f"""process {proc} {{
    tag '{r['step']}'
    cpus {r['cpus']}
    memory '{r['memory']} GB'
    time '{r['minutes'] + 15}m'
    publishDir "${{params.outdir}}/{i:02d}_{r['step']}", mode: 'copy', saveAs: {{ f -> f.startsWith('out/') ? f.substring(4) : null }}

    input:
    path h5ad

    output:
    path 'out/output.h5ad', emit: h5ad
    path 'out/**', emit: files

    script:
    \"\"\"
    {sandbox} --strict {image} {os.path.join(pipe, 'steps', r['step'] + '.py')} ${{h5ad}} {models} {r['cpus']} {r['minutes']} out
    \"\"\"
}}
""")
        source = "file(params.input)" if i == 1 else f"S{i - 1:02d}_{rows[i - 2]['step']}.out.h5ad"
        calls.append(f"    {proc}({source})")
    header = ("// Rendered by Geth (lab, arm B, EXPERIMENTAL) from build_spec.txt. The agents wrote the step scripts;\n"
              "// Geth wrote this file. Each step runs in the sandbox (geth/lab/bin/lab_sandbox.sh): no network, no\n"
              "// host files, only its input and its own folder.\n\n")
    with open(os.path.join(pipe, "main.nf"), "w") as fh:
        fh.write(header + "\n".join(procs) + "\nworkflow {\n" + "\n".join(calls) + "\n}\n")
    with open(os.path.join(pipe, "nextflow.config"), "w") as fh:
        fh.write(f"params.input  = '{data_file}'\nparams.outdir = '{os.path.join(run_dir, 'results')}'\n")
    print(f"Rendered {len(rows)} steps into {pipe}/main.nf")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "write-step":
        write_step(*args)
    elif cmd == "test-step":
        test_step(*args)
    elif cmd == "check-spec":
        check_spec(args[0], stdin_text())
    elif cmd == "read":
        read(*args)
    elif cmd == "save-review":
        save_review(args[0], args[1], args[2], stdin_text(), fallback="--fallback" in args[3:])
    elif cmd == "render":
        render(*args)
    else:
        sys.exit(__doc__)
