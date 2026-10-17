#!/usr/bin/env bash
# Baseline (no agents): run an nf-core pipeline's own test profile on Eddie with the roslin profile, to check
# the pipeline itself works here before Geth plans it. One pipeline at a time (Nextflow driver on node1q01).
# Usage: baseline.sh <pipeline> [<revision>]   (revision defaults to the one pinned in geth_checks.py)
# Result line: <pipeline> <revision> <exit> <tasks> <wall time>; logs in $PERSEUS_VEIL/geth/baselines/<pipeline>/
set -uo pipefail
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh
here=$(cd "$(dirname "$0")/.." && pwd)

pipeline=$1
revision=${2:-$(python3 "$here/geth/bin/geth_checks.py" revision "$pipeline")} || { echo "$revision"; exit 1; }
out=$PERSEUS_VEIL/geth/baselines/$pipeline
mkdir -p "$out"
cd "$out"
start=$(date +%s)
eval "$(python3 "$here/geth/bin/geth_checks.py" runtime "$pipeline")"
nested_env=()
[ -n "$pipeline_nxf_ver" ] && nested_env+=(NXF_VER="$pipeline_nxf_ver")
[ -n "$pipeline_java_home" ] && nested_env+=(JAVA_HOME="$pipeline_java_home" NXF_JAVA_HOME="$pipeline_java_home")
nested_env+=("${pipeline_env[@]}")
extra=()
[ -n "$pipeline_extra_config" ] && extra+=(-c "$here/geth/conf/$pipeline_extra_config")
env "${nested_env[@]}" nextflow run "nf-core/$pipeline" -r "$revision" -profile test,roslin -c "$here/geth/conf/test.config" "${extra[@]}" \
    --outdir "$out/results" -w "$out/work" -ansi-log false > "$out/run.log" 2>&1
rc=$?
tasks=$(grep -cE '^\[PROCESS|Submitted process' "$out/run.log")  # new and pre-24 Nextflow log formats
echo "$pipeline $revision exit=$rc tasks=$tasks wall=$(( ($(date +%s) - start) / 60 ))min"
[ $rc -eq 0 ] || grep -m3 -A8 -E 'ERROR ~|Error executing process' "$out/run.log"
