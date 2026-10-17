#!/usr/bin/env bash
# geth lab: EXPERIMENTAL agent-designed analyses (phase 11). Not for real analyses.
#
#   geth lab design <data_dir> "<question>" <name> [--no-skill]   a designer agent writes an analysis design;
#                                                                  nothing runs on the data
#   geth lab show <name>                                           print the design and its format check
#
# The lab works only on benchmark data (GETH_LAB_DATA, default $GETH_DATA_ROOT/testdata) and writes to
# $GETH_RUNS_DIR/lab/<name>.
source "$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)/env.sh" || exit 1
set -euo pipefail
export GETH_LAB_DATA=${GETH_LAB_DATA:-$GETH_DATA_ROOT/testdata}
lab=$GETH_RUNS_DIR/lab

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
banner() { echo "*** Geth lab: EXPERIMENTAL, not for real analyses ***" >&2; }
run_dir_of() {
    [[ "${1:-}" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Run names may only use letters, digits, '.', '_' and '-'." >&2; exit 1; }
    echo "$lab/$1"
}
show() {
    local d=$1
    echo "Question : $(cat "$d/question.txt")"
    echo "Arm      : $(cat "$d/lab_arm.txt")"
    for f in steps statistics expected rationale; do
        echo; echo "== $f"; grep -v '^# EXPERIMENTAL' "$d/lab_design_$f.txt" | sed 's/^/  /'
    done
    echo; cat "$d/lab_design_check.txt"
}

cmd=${1:-}; shift || true
banner
case "$cmd" in
    design)
        [ $# -ge 3 ] || usage
        data_dir=$(readlink -f "$1"); question=$2; d=$(run_dir_of "$3"); skill=true
        [ "${4:-}" = "--no-skill" ] && skill=false
        [ -e "$d" ] && { echo "Lab run '$3' already exists: choose another name." >&2; exit 1; }
        mkdir -p "$d"
        site=()
        [ -n "${GETH_NF_CONFIG:-}" ] && site=(-c "$GETH_NF_CONFIG")
        cd "$d"
        nextflow run "$GETH_HOME/geth/lab/main.nf" -c "$GETH_HOME/geth/lab/nextflow.config" "${site[@]}" \
            --mode design --question "$question" --data_dir "$data_dir" --run_dir "$d" --lab_skill "$skill" \
            -w "$d/geth_work" -with-trace "$d/geth_trace_design.txt" -ansi-log false > "$d/geth_design.log" 2>&1 \
            || { echo "Design failed: see $d/geth_design.log" >&2; exit 1; }
        show "$d"
        ;;
    show)
        [ $# -eq 1 ] || usage
        show "$(run_dir_of "$1")"
        ;;
    *) usage ;;
esac
