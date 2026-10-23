#!/usr/bin/env bash
# Project benchmark, end to end (R5b, R5c): plan a project, approve its steps and every step's plan automatically
# (benchmark data only), run it, and score where each step ended and the project report's check.
# Usage: bench_project_run.sh <tag> <name>:<scenario> ...   (scenarios: bench/bench_project.sh, plus:
#   yeast_de   yeast RNA-seq without reference, DE wild type vs uninduced RAP1 -> reference, rnaseq, differentialabundance
#              (the test reads are too few for DESeq2: only 141 genes reach 10 counts)
#   bulk_de    airway, 8 human samples (24 GB): rnaseq, then DE dexamethasone vs untreated, about 2.5 hours)
# Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; shift
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
t=$GETH_DATA_ROOT/testdata
declare -A data=( [sc_cells]=$t/pbmc_index_test [yeast_de]=$t/project_yeast_noref [kang_lab]=$t/lab_kang2018
                  [bulk_de]=$GETH_DATA_ROOT/data/airway_GSE52778 )
declare -A question=(
    [sc_cells]="Which cell types are in this PBMC sample, and what are their marker genes?"
    [yeast_de]="Which genes differ in expression between the wild type and the uninduced RAP1 strain?"
    [kang_lab]="Which genes respond to interferon-beta in each immune cell type of these PBMCs?"
    [bulk_de]="Which genes change expression when these airway smooth muscle cells are treated with dexamethasone?" )

{
trap 'echo "Interrupted: stopping ${name:-} ..." >&2; [ -n "${name:-}" ] && "$geth" project stop "$name" >&2; exit 130' INT TERM
for item in "$@"; do
    IFS=: read -r name scenario <<< "$item"
    lab=(); [ "$scenario" = kang_lab ] && lab=(--lab)
    p=$GETH_RUNS_DIR/projects/$name
    t0=$(date +%s)
    [ -d "$p" ] || "$geth" project new "${data[$scenario]}" "${question[$scenario]}" "$name" "${lab[@]}" < /dev/null > /dev/null 2>&1
    "$geth" project approve "$name" --yes > /dev/null 2>&1
    t1=$(date +%s)
    "$geth" project run "$name" --yes < /dev/null > "$p/bench_run.out" 2>&1; rc=$?
    t2=$(date +%s)
    python3 - "$p" "$scenario" "$rc" "$(( t1 - t0 ))" "$(( t2 - t1 ))" <<'PY' || echo "{\"run\": \"$name\", \"error\": \"scoring failed\"}"
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["GETH_HOME"], "geth", "bin"))
import geth_project as gp
p, scenario, rc, plan_s, run_s = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
doc = gp.load(os.path.join(p, "steps.json"), {}) or {}
reviews = gp.load(os.path.join(p, "reviews.json"), {}) or {}
print(json.dumps({"run": os.path.basename(p), "scenario": scenario, "exit": rc,
                  "steps": {s["id"]: f"{s['kind']}:{s.get('pipeline') or s.get('species') or ''}:{gp.status(p, s)}" for s in doc.get("steps", [])},
                  "reviews": {k: v.get("action") for k, v in reviews.items()},
                  "report_check": gp.read(os.path.join(p, "report_check.txt")).strip(),
                  "plan_min": round(plan_s / 60, 1), "run_min": round(run_s / 60, 1)}))
PY
done
} | tee -a "$out"
