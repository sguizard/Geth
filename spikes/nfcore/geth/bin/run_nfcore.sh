#!/usr/bin/env bash
# Launch a pinned nf-core pipeline for Geth's operator agent and print a short status digest.
# Usage: run_nfcore.sh <run_dir> <pipeline> <samplesheet.csv> <params.json>
# Each call is one attempt (attempt_N/); runs resume from previous attempts.
# Always exits 0: a failing tool would kill the agent, so failures are reported as text.
set -uo pipefail
run_dir=$1; pipeline=${2#nf-core/}; sheet=$3; params=$4
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

case "$run_dir" in
    "$PERSEUS_VEIL"/spikes/nfcore/runs/*) ;;
    *) echo "STATUS: REFUSED - run_dir must be under $PERSEUS_VEIL/spikes/nfcore/runs"; exit 0 ;;
esac
case "$pipeline" in
    rnaseq)   revision=3.27.0 ;;
    scrnaseq) revision=4.2.0 ;;
    *) echo "STATUS: REFUSED - pipeline must be 'rnaseq' or 'scrnaseq' (got '$pipeline')"; exit 0 ;;
esac

mkdir -p "$run_dir"
n=$(( $(find "$run_dir" -maxdepth 1 -type d -name 'attempt_*' | wc -l) + 1 ))
attempt="$run_dir/attempt_$n"
mkdir -p "$attempt"
cp "$sheet" "$attempt/samplesheet.csv"

# Params must be a JSON object whose keys exist in the pinned pipeline schema
# (nf-core only warns about unknown params, so typos would be silently ignored).
# Geth owns input/outdir and the institutional config.
schema="$GETH_HOME/spikes/nfcore/schemas/$pipeline-$revision.json"
if ! python3 -I - "$params" "$attempt/params.json" "$schema" <<'EOF'
import difflib, json, sys
try:
    p = json.load(open(sys.argv[1]))
except ValueError as e:
    sys.exit(f"STATUS: FAILED - params_json is not valid JSON: {e}")
if not isinstance(p, dict):
    sys.exit("STATUS: FAILED - params_json must be a JSON object")
for k in ("input", "outdir", "custom_config_base", "custom_config_version"):
    p.pop(k, None)
schema = json.load(open(sys.argv[3]))
known = {k for g in (schema.get("$defs") or schema.get("definitions")).values() for k in g.get("properties", {})}
unknown = sorted(set(p) - known)
if unknown:
    print("STATUS: FAILED - unknown pipeline parameters (not launched):")
    for k in unknown:
        close = difflib.get_close_matches(k, known, n=3)
        print(f"  {k}: not a parameter of this pipeline" + (f"; did you mean {', '.join(close)}?" if close else ""))
    sys.exit(1)
json.dump(p, open(sys.argv[2], "w"), indent=2)
EOF
then
    echo "ATTEMPT: $n"
    exit 0
fi

# Separate launch dir: the Geth driver itself runs in $run_dir, and -resume must not pick its session.
mkdir -p "$run_dir/nfcore"
cd "$run_dir/nfcore"
nextflow run "nf-core/$pipeline" -r "$revision" -profile roslin \
    -c "$GETH_HOME/spikes/nfcore/geth/conf/nested.config" \
    -params-file "$attempt/params.json" --input "$attempt/samplesheet.csv" \
    --outdir "$run_dir/results" -w "$run_dir/work" -resume -ansi-log false \
    > "$attempt/nextflow.log" 2>&1
rc=$?

echo "ATTEMPT: $n"
echo "PIPELINE: nf-core/$pipeline $revision"
if [ $rc -eq 0 ]; then
    echo "STATUS: SUCCESS"
    echo "OUTDIR: $run_dir/results"
    grep -E '^(Completed at|Duration|CPU hours|Succeeded|Cached|Ignored|Failed)' "$attempt/nextflow.log" | tail -n 8
    grep -iE 'WARN.*(skipp|fewer than|min_)' "$attempt/nextflow.log" | head -n 20
    exit 0
fi

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
exit 0
