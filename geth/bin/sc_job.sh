#!/usr/bin/env bash
# One job of the single-cell toolbox for Rannoch's agents, through geth/jobs.nf and the site's Nextflow config
# (a scheduler job, like main.nf's SC_INSPECT and SC_ANALYSE): prints what the tool prints.
# Usage: sc_job.sh <run_dir> inspect <h5ad>
#        sc_job.sh <run_dir> analyse <design.txt>
# Always exits 0: a failure is reported as text.
set -uo pipefail
run_dir=$1; task=$2; arg=$3
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"
case "$run_dir" in
    "$GETH_RUNS_DIR"/*) ;;
    *) echo "STATUS: REFUSED - run_dir must be under $GETH_RUNS_DIR"; exit 0 ;;
esac

jobs="$run_dir/.harness/jobs"
mkdir -p "$jobs"
n=$(( $(find "$jobs" -maxdepth 1 -type d -name "${task}_*" | wc -l) + 1 ))
launch="$jobs/${task}_$n"
mkdir -p "$launch"
case $task in
    inspect) args=(--h5ad "$arg") ;;
    analyse) cp "$arg" "$launch/design.txt"; args=(--run_dir "$run_dir" --design "$launch/design.txt") ;;
    *) echo "STATUS: REFUSED - unknown task '$task'"; exit 0 ;;
esac
site=()
[ -n "${GETH_NF_CONFIG:-}" ] && site=(-c "$GETH_NF_CONFIG")
cd "$launch"
nextflow run "$GETH_HOME/geth/jobs.nf" "${site[@]}" --task "$task" "${args[@]}" --out "$launch/output.txt" \
    -w "$run_dir/geth_work" -ansi-log false > "$launch/nextflow.log" 2>&1
rc=$?
if [ $rc -eq 0 ] && [ -f "$launch/output.txt" ]; then
    cat "$launch/output.txt"
else
    echo "STATUS: FAILED - the toolbox job could not run (exit $rc); the end of its log:"
    grep -E 'ERROR|Error|error' "$launch/nextflow.log" | head -n 10
    tail -n 15 "$launch/nextflow.log"
fi
exit 0
