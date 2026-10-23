#!/usr/bin/env bash
# Run one analysis of the approved single-cell design for Geth's analyst agent (inside the toolbox container).
# Usage: sc_analyse.sh <run_dir> <design.txt>
# The first analysis must use the approved design unchanged; one justified revision of tunable keys follows
# at most (geth_checks.py gate). Always exits 0: failures are reported as text.
set -uo pipefail
run_dir=$1; design=$2
sheet="$run_dir/plan_samplesheet.csv"
max_attempts=4

n=$(( $(find "$run_dir" -maxdepth 1 -type d -name 'analysis_*' | wc -l) + 1 ))
if [ "$n" -gt "$max_attempts" ]; then
    echo "STATUS: REFUSED - attempt limit ($max_attempts) reached; stop and report"
    exit 0
fi
out="$run_dir/analysis_$n"
mkdir -p "$out"
cp "$design" "$out/design.submitted.txt"
echo "ANALYSIS: $n"

if ! geth_checks.py gate "$run_dir" sc_downstream "$sheet" "$out/design.submitted.txt" > "$out/gate.txt" 2>&1; then
    echo "STATUS: REFUSED - this design departs from what may be run now (not run):"
    cat "$out/gate.txt"
    exit 0
fi
if ! geth_checks.py check-plan sc_downstream "$sheet" "$out/design.submitted.txt" "$out/design.json" > "$out/check.txt" 2>&1; then
    echo "STATUS: FAILED - design check (not run):"
    cat "$out/check.txt"
    exit 0
fi

h5ad=$(python3 -c 'import csv, sys; print(next(csv.DictReader(open(sys.argv[1])))["h5ad"])' "$sheet")
export GETH_CACHE="$PWD/.cache"
if sc_downstream.py run "$h5ad" "$out/design.json" "$out" > "$out/summary.txt" 2> "$out/stderr.txt"; then
    geth_checks.py record "$run_dir" analysis "$sheet" "$out/design.json" "$out/summary.txt"
    touch "$out/SUCCEEDED"  # what an agent's success claim is checked against
    echo "STATUS: SUCCESS"
    echo "OUTDIR: $out"
    cat "$out/summary.txt"
else
    echo "STATUS: FAILED (toolbox error)"
    grep -vE 'Warning|warn' "$out/stderr.txt" | tail -n 30
fi
exit 0
