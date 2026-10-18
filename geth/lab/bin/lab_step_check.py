#!/usr/bin/env python3
"""Geth lab (EXPERIMENTAL): static check of an analysis step written by an agent, before it may run.

Usage: lab_step_check.py <step.py>
A step is a Python script run as  python3 <step.py> <input.h5ad> <output.h5ad>  inside a sandbox (pinned
container, no network, no home folder, only its own work folder writable). It reads argv[1], writes argv[2], and
may write tables (.tsv, .csv, .json) and figures (.png, .pdf) in its working folder. Reference models are in
./models. The checks are fixed rules on the parsed code (nothing is run). This check catches obvious misuse early and tells the agent why; the sandbox is what enforces it.
"""
import ast
import sys

ALLOWED_MODULES = {  # what the lab image holds (geth/lab/README: GETH_LAB_IMAGE), plus harmless standard modules
    "anndata", "scanpy", "celltypist", "numpy", "pandas", "scipy", "sklearn", "statsmodels", "matplotlib",
    "seaborn", "pydeseq2", "harmonypy", "igraph", "leidenalg", "json", "math", "re", "sys", "os", "collections",
    "itertools", "functools", "warnings", "pathlib", "typing", "dataclasses", "csv", "gzip", "statistics",
    "logging", "time", "datetime", "textwrap", "string",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint", "input"}
FORBIDDEN_ATTRS = {"system", "popen", "spawnl", "spawnv", "execv", "execl", "fork", "kill", "rmtree", "chmod",
                   "chown", "symlink", "remove", "unlink", "rmdir", "removedirs", "putenv"}


def check(path, need_argv=True):
    source = open(path).read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as e:
        return [f"syntax error line {e.lineno}: {e.msg}"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if name.split(".")[0] not in ALLOWED_MODULES:
                    problems.append(f"line {node.lineno}: module '{name}' is not allowed (allowed: {', '.join(sorted(ALLOWED_MODULES))})")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                problems.append(f"line {node.lineno}: '{node.func.id}()' is not allowed")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                problems.append(f"line {node.lineno}: '.{node.func.attr}()' is not allowed in a step")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/") \
                and len(node.value) > 1 and not node.value.startswith("/tmp"):
            problems.append(f"line {node.lineno}: absolute path '{node.value[:60]}': read argv[1] and ./models, write in the working folder")
    if need_argv and "sys.argv" not in source:
        problems.append("the step must read its input from sys.argv[1] and write its output AnnData to sys.argv[2]")
    return problems


if __name__ == "__main__":
    problems = check(sys.argv[1])
    print("STEP CHECK: OK" if not problems else f"STEP CHECK: {len(problems)} problem(s)\n" + "\n".join(f"- {p}" for p in problems))
