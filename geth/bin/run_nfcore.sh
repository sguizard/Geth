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
# Site settings: inherited from the Geth driver, or loaded from the repository's env.sh.
[ -n "${GETH_RUNS_DIR:-}" ] || source "$(cd "$(dirname "$0")/../.." && pwd)/env.sh"
checks="$GETH_HOME/geth/bin/geth_checks.py"
max_attempts=5

case "$run_dir" in
    "$GETH_RUNS_DIR"/*) ;;
    *) echo "STATUS: REFUSED - run_dir must be under $GETH_RUNS_DIR"; exit 0 ;;
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
# The plan's second sheet (contrasts for differentialabundance, multiplexed samples for scrnaseq), under the
# name and nf-core parameter the registry gives it.
read -r sheet2_param sheet2_file < <(python3 "$checks" sheet2 "$pipeline"; echo)
sheet2=""
if [ -n "$contrasts" ] && grep -q '[^[:space:]]' "$contrasts" 2>/dev/null; then
    sheet2="$attempt/${sheet2_file:-contrasts.csv}"  # a pipeline without one: the gate refuses it
    cp "$contrasts" "$sheet2"
    parts+=(--contrasts "$sheet2")
fi
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

# nf-core's own samplesheet checks count columns: write every column on every row.
python3 "$checks" normalise-sheet "$attempt/samplesheet.csv" "$attempt/samplesheet.csv"

# Resources: small test data on a small reference gets capped requests (fast scheduling); real data gets
# nf-core's own. A large genome needs large jobs whatever the read count (e.g. STAR loads a human index in RAM).
input_bytes=$(python3 -c 'import csv, os, sys
print(sum(os.path.getsize(v) for r in csv.DictReader(open(sys.argv[1])) for v in r.values()
          if v and v.startswith("/") and os.path.isfile(v)))' "$attempt/samplesheet.csv")
# Profiles: the site's (institutional or container profile), then the plan's analysis profile.
profiles=${GETH_NFCORE_PROFILE:-}
extra=()
[ -n "$analysis_profile" ] && profiles=${profiles:+$profiles,}$analysis_profile
[ -n "$sheet2" ] && [ -n "${sheet2_param:-}" ] && extra+=("--$sheet2_param" "$sheet2")
# CellBender runs on a GPU when the site has one (GETH_GPU=yes), unless the plan skips it.
if [ "$pipeline" = scrnaseq ] && [ "${GETH_GPU:-no}" = yes ] && \
        ! python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("skip_cellbender") in (True, "true") else 1)' "$attempt/params.json"; then
    profiles=${profiles:+$profiles,}gpu
    [ -n "${GETH_GPU_CONFIG:-}" ] && extra+=(-c "$GETH_GPU_CONFIG")
fi
profile_args=()
[ -n "$profiles" ] && profile_args=(-profile "$profiles")
reference_bytes=$(python3 "$checks" reference-size "$pipeline" "$attempt/params.json")
if [ "$input_bytes" -lt 2000000000 ] && [ "$reference_bytes" -lt 500000000 ]; then
    resources=test
else
    resources=production
fi

# Per-pipeline runtime: older pipelines pin their Nextflow (and Java), eager reads a TSV and takes max_* params.
eval "$(python3 "$checks" runtime "$pipeline")"
nested_env=()
[ -n "$pipeline_nxf_ver" ] && nested_env+=(NXF_VER="$pipeline_nxf_ver")
[ -n "$pipeline_java_home" ] && nested_env+=(JAVA_HOME="$pipeline_java_home" NXF_JAVA_HOME="$pipeline_java_home")
nested_env+=("${pipeline_env[@]}")
input="$attempt/samplesheet.csv"
if [ "$pipeline_input_format" = tsv ]; then
    python3 -c 'import csv, sys; csv.writer(sys.stdout, delimiter="\t", lineterminator="\n").writerows(csv.reader(open(sys.argv[1])))' \
        "$attempt/samplesheet.csv" > "$attempt/samplesheet.tsv"
    input="$attempt/samplesheet.tsv"
fi
[ -n "$pipeline_extra_config" ] && extra+=(-c "$GETH_HOME/geth/conf/$pipeline_extra_config")
# Memory that depends on the data (e.g. Kraken2 loads its database index in RAM).
python3 "$checks" resources "$pipeline" "$attempt/params.json" > "$attempt/resources.config"
[ -s "$attempt/resources.config" ] && extra+=(-c "$attempt/resources.config")
if [ -n "$pipeline_legacy_limits" ] && [ "$resources" = test ]; then
    extra+=(--max_cpus 4 --max_memory 16.GB --max_time 4.h)
fi
site_config=()
[ -n "${GETH_NFCORE_CONFIG:-}" ] && site_config=(-c "$GETH_NFCORE_CONFIG")  # applied last: the site wins

# Separate launch dir: the Geth driver itself runs in $run_dir, and -resume must not pick its session.
mkdir -p "$run_dir/nfcore"
cd "$run_dir/nfcore"
env "${nested_env[@]}" nextflow run "nf-core/$pipeline" -r "$revision" "${profile_args[@]}" "${extra[@]}" \
    -c "$GETH_HOME/geth/conf/$resources.config" "${site_config[@]}" \
    -params-file "$attempt/params.json" --input "$input" \
    --outdir "$run_dir/results" -w "$run_dir/work" -resume -ansi-log false \
    > "$attempt/nextflow.log" 2>&1
rc=$?

echo "PIPELINE: nf-core/$pipeline $revision (profiles: ${profiles:-none}; resources: $resources)"
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
    awk '/ERROR ~|Error executing process|Validation of pipeline parameters failed|The following invalid input values|\] ERROR:/{f=1} f' \
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
