#!/usr/bin/env bash
# Launch the approved nf-core run for Geth's operator agent and print a short status digest.
# Usage: run_nfcore.sh <run_dir> <pipeline> <samplesheet.csv> <params.json> [<contrasts.csv> <analysis_profile>]
# (contrasts and analysis profile: downstream pipelines such as differentialabundance)
#
# Every call is one attempt (attempt_N/). Before launching, the attempt must pass:
#   1. the plan-diff gate  - same design as the approved plan; other changes only where the last error points
#   2. the plan check      - samplesheet and params valid for the pinned pipeline
# Runs resume from previous attempts. Always exits 0: a failing tool would kill the agent,
# so failures are reported as text.
set -uo pipefail
run_dir=$1; pipeline=${2#nf-core/}; sheet=$3; params=$4; contrasts=${5:-}; analysis_profile=${6:-}
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh
checks="$GETH_HOME/geth/bin/geth_checks.py"
max_attempts=5

case "$run_dir" in
    "$PERSEUS_VEIL"/geth/runs/*) ;;
    *) echo "STATUS: REFUSED - run_dir must be under $PERSEUS_VEIL/geth/runs"; exit 0 ;;
esac
if ! revision=$(python3 "$checks" revision "$pipeline"); then
    echo "STATUS: REFUSED - $revision"; exit 0
fi

n=$(( $(find "$run_dir" -maxdepth 1 -type d -name 'attempt_*' | wc -l) + 1 ))
if [ "$n" -gt "$max_attempts" ]; then
    echo "STATUS: REFUSED - attempt limit ($max_attempts) reached; stop and report the last error"
    exit 0
fi
attempt="$run_dir/attempt_$n"
mkdir -p "$attempt"
cp "$sheet" "$attempt/samplesheet.csv"
cp "$params" "$attempt/params.submitted.json"
parts=()
if [ -n "$contrasts" ] && [ -s "$contrasts" ]; then cp "$contrasts" "$attempt/contrasts.csv"; parts+=(--contrasts "$attempt/contrasts.csv"); fi
[ -n "$analysis_profile" ] && parts+=(--profile "$analysis_profile")
[ -f "$run_dir/plan_upstream.txt" ] && parts+=(--upstream "$(cat "$run_dir/plan_upstream.txt")")
echo "ATTEMPT: $n"

if ! python3 "$checks" gate "$run_dir" "$pipeline" "$attempt/samplesheet.csv" "$attempt/params.submitted.json" "${parts[@]}" > "$attempt/gate.txt" 2>&1; then
    echo "STATUS: REFUSED - this attempt departs from the approved plan (not launched):"
    cat "$attempt/gate.txt"
    echo "Resubmit the approved plan, changing only what the last error points to."
    echo "If the error cannot be fixed that way, stop and report it."
    exit 0
fi

if ! python3 "$checks" check-plan "$pipeline" "$attempt/samplesheet.csv" "$attempt/params.submitted.json" "$attempt/params.json" "${parts[@]}" > "$attempt/check.txt" 2>&1; then
    python3 "$checks" record "$run_dir" check "$attempt/samplesheet.csv" "$attempt/params.submitted.json" "$attempt/check.txt"
    echo "STATUS: FAILED - plan check (not launched):"
    cat "$attempt/check.txt"
    exit 0
fi

# Resources: small test data gets capped requests (fast scheduling); real data gets nf-core's own.
input_bytes=$(python3 -c 'import csv, os, sys
print(sum(os.path.getsize(v) for r in csv.DictReader(open(sys.argv[1])) for v in r.values()
          if v and v.startswith("/") and os.path.isfile(v)))' "$attempt/samplesheet.csv")
profiles=roslin
extra=()
if [ -n "$analysis_profile" ]; then
    profiles=roslin,$analysis_profile
    extra+=(--contrasts "$attempt/contrasts.csv")
fi
if [ "$input_bytes" -lt 2000000000 ]; then resources=test; else resources=production; fi

# Separate launch dir: the Geth driver itself runs in $run_dir, and -resume must not pick its session.
mkdir -p "$run_dir/nfcore"
cd "$run_dir/nfcore"
nextflow run "nf-core/$pipeline" -r "$revision" -profile "$profiles" "${extra[@]}" \
    -c "$GETH_HOME/geth/conf/$resources.config" \
    -params-file "$attempt/params.json" --input "$attempt/samplesheet.csv" \
    --outdir "$run_dir/results" -w "$run_dir/work" -resume -ansi-log false \
    > "$attempt/nextflow.log" 2>&1
rc=$?

echo "PIPELINE: nf-core/$pipeline $revision (resources: $resources)"
if [ $rc -eq 0 ]; then
    python3 "$checks" record "$run_dir" ok "$attempt/samplesheet.csv" "$attempt/params.submitted.json"
    echo "STATUS: SUCCESS"
    echo "OUTDIR: $run_dir/results"
    grep -iE 'WARN.*(skipp|fewer than|min_)' "$attempt/nextflow.log" | head -n 20
    exit 0
fi

{
    echo "STATUS: FAILED (exit $rc)"
    echo "--- error report (from the Nextflow log) ---"
    awk '/ERROR ~|Error executing process|Validation of pipeline parameters failed|The following invalid input values/{f=1} f' \
        "$attempt/nextflow.log" | head -n 60
    if ! grep -qE 'ERROR ~|Error executing process|Validation of' "$attempt/nextflow.log"; then
        tail -n 40 "$attempt/nextflow.log"
    fi
    workdir=$(grep -A1 'Work dir:' "$attempt/nextflow.log" | tail -n 1 | tr -d '[:space:]')
    if [ -n "$workdir" ] && [ -f "$workdir/.command.err" ]; then
        echo "--- stderr of the failed task (last 30 lines) ---"
        tail -n 30 "$workdir/.command.err"
    fi
} > "$attempt/error.txt"
python3 "$checks" record "$run_dir" nextflow "$attempt/samplesheet.csv" "$attempt/params.submitted.json" "$attempt/error.txt"
cat "$attempt/error.txt"
exit 0
