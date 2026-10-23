#!/usr/bin/env bash
# Geth lab (EXPERIMENTAL): one lab job for Rannoch's lab agents, through geth/lab/jobs.nf and the site's Nextflow
# config (a scheduler job, like main.nf's LAB_INSPECT, MAKE_SUBSET, TEST_STEP...): prints what the tool prints.
# Usage: lab_job.sh <run_dir> <task> [--<param> <value> ...]   (tasks and their parameters: geth/lab/jobs.nf)
# Always exits 0: a failure is reported as text.
set -uo pipefail
run_dir=$1; task=$2; shift 2
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../../.." && pwd)/env.sh"
case "$run_dir" in
    "$GETH_RUNS_DIR"/lab/*) ;;
    *) echo "STATUS: REFUSED - run_dir must be under $GETH_RUNS_DIR/lab"; exit 0 ;;
esac

jobs="$run_dir/.harness/jobs"
mkdir -p "$jobs"
n=$(( $(find "$jobs" -maxdepth 1 -type d -name "${task}_*" | wc -l) + 1 ))
launch="$jobs/${task}_$n"
mkdir -p "$launch"
site=()
[ -n "${GETH_NF_CONFIG:-}" ] && site=(-c "$GETH_NF_CONFIG")
cd "$launch"
nextflow run "$GETH_HOME/geth/lab/jobs.nf" "${site[@]}" --task "$task" --run_dir "$run_dir" "$@" --out "$launch/output.txt" \
    -w "$run_dir/geth_work" -ansi-log false > "$launch/nextflow.log" 2>&1
rc=$?
if [ $rc -eq 0 ] && [ -f "$launch/output.txt" ]; then
    cat "$launch/output.txt"
else
    echo "FAILED: the lab job '$task' could not run (exit $rc); the end of its log:"
    grep -E 'ERROR|Error|error' "$launch/nextflow.log" | head -n 10
    tail -n 15 "$launch/nextflow.log"
fi
exit 0
