#!/usr/bin/env bash
# Project benchmark, plan only (R5a): the coordinator proposes a project's steps for each scenario, scored by
# bench/eval_project.py. Nothing is approved or run. Deliveries: bench/stage_projects.sh, stage_testdata.sh,
# stage_public.sh (airway), stage_index_tests.sh (pbmc_index_test), bench/lab/stage_kang.sh.
# Usage: bench_project.sh <tag> <repeats> <scenario> [<scenario> ...]
#   scenarios: sc_cells bulk_de multiomics noref smallrna kang_gap kang_lab
# Results: $GETH_BENCH_DIR/<tag>.jsonl
set -uo pipefail
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/.." && pwd)/env.sh"

tag=$1; repeats=$2; shift 2
geth=$GETH_HOME/geth/geth
out=${GETH_BENCH_DIR:-$GETH_WORK_ROOT/bench}/$tag.jsonl
mkdir -p "$(dirname "$out")"
t=$GETH_DATA_ROOT/testdata
declare -A data=( [sc_cells]=$t/pbmc_index_test [bulk_de]=$GETH_DATA_ROOT/data/airway_GSE52778
    [multiomics]=$t/project_multiomics_yeast [noref]=$t/project_yeast_noref [smallrna]=$t/project_smallrna
    [kang_gap]=$t/lab_kang2018 [kang_lab]=$t/lab_kang2018 )
declare -A question=(
    [sc_cells]="Which cell types are in this PBMC sample, and what are their marker genes?"
    [bulk_de]="Which genes change expression when these airway smooth muscle cells are treated with dexamethasone?"
    [multiomics]="Quantify gene expression in the RNA-seq samples, and find the open chromatin regions in the ATAC-seq samples."
    [noref]="Quantify gene expression in these yeast RNA-seq samples."
    [smallrna]="Which microRNAs are expressed in these samples, and which differ between the knock-out clone and the parental line?"
    [kang_gap]="Which genes respond to interferon-beta in each immune cell type of these PBMCs?"
    [kang_lab]="Which genes respond to interferon-beta in each immune cell type of these PBMCs?" )

{
trap 'echo "Interrupted: stopping ${name:-} ..." >&2; [ -n "${name:-}" ] && "$geth" legion stop "$name" >&2; exit 130' INT TERM
for scenario in "$@"; do
    [ -n "${question[$scenario]:-}" ] || { echo "unknown scenario: $scenario" >&2; continue; }
    lab=(); [ "$scenario" = kang_lab ] && lab=(--lab)
    for i in $(seq 1 "$repeats"); do
        name=${tag}_${scenario}_$i
        t0=$(date +%s)
        "$geth" legion new "${data[$scenario]}" "${question[$scenario]}" "$name" "${lab[@]}" < /dev/null > /dev/null 2>&1 \
            && status=ok || status=failed
        t1=$(date +%s)
        p=$GETH_RUNS_DIR/projects/$name
        python3 "$GETH_HOME/bench/eval_project.py" "$p" "$scenario" | python3 -c 'import json, os, sys
d = json.load(sys.stdin)
p, status, seconds = sys.argv[1], sys.argv[2], int(sys.argv[3])
log = os.path.join(p, "geth_project_plan.log")
usage = [l for l in open(log, errors="replace") if l.startswith("Model usage:")] if os.path.isfile(log) else []
qa = os.path.join(p, "project_questions.md")
d.update(status=status, minutes=round(seconds / 60, 1),
         questions=open(qa).read().count("\n**") if os.path.isfile(qa) else 0,
         **({"model_usage": json.loads(usage[-1].split(":", 1)[1])} if usage else {}))
print(json.dumps(d))' "$p" "$status" "$(( t1 - t0 ))" || echo "{\"run\": \"$name\", \"error\": \"scoring failed\"}"
    done
done
} | tee -a "$out"
