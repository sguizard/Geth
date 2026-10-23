#!/usr/bin/env bash
# geth lab: EXPERIMENTAL agent-designed analyses (phase 11). Not for real analyses.
#
#   geth lab design <data_dir> "<question>" <name> [--no-skill]   a designer agent writes an analysis design;
#                                                                  nothing runs on the data
#   geth lab show <name>                                           print the design and its format check
#   geth lab list                                                  all lab runs and where they stand
#   geth lab judge <name> <design run> <design run> [...]          a judge agent compares designs of the same
#                                                                  request and writes the best one
#   geth lab build <design run> <name> [--no-skill]                arm B: an engineer agent implements a checked
#                                                                  design as step scripts (tested on a subset in a
#                                                                  sandbox), a reviewer agent checks them (2 rounds
#                                                                  at most), then Geth runs them on the full data
#   geth lab build-c <design run> <name>                           arm C: the engineer writes the whole Nextflow
#                                                                  pipeline; its driver runs only in the sandbox
#   geth lab stop <name>                                           stop a lab run and its scheduler jobs
#
# The lab works only on benchmark data (GETH_LAB_DATA, default $GETH_DATA_ROOT/testdata) and writes to
# $GETH_RUNS_DIR/lab/<name>. The agents: geth/harness/lab.py; their scheduler jobs: geth/lab/jobs.nf.
source "$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)/env.sh" || exit 1
set -euo pipefail
export GETH_LAB_DATA=${GETH_LAB_DATA:-$GETH_DATA_ROOT/testdata}
lab=$GETH_RUNS_DIR/lab
source "$GETH_HOME/geth/bin/driver_slots.sh"

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
banner() { echo "*** Geth lab: EXPERIMENTAL, not for real analyses ***" >&2; }
run_dir_of() {
    [[ "${1:-}" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Run names may only use letters, digits, '.', '_' and '-'." >&2; exit 1; }
    echo "$lab/$1"
}
lab_stage() {  # lab_stage <run_dir> <mode> <tag> [params...]: one lab stage, one driver slot (its jobs' Nextflow)
    local d=$1 mode=$2 tag=$3 rc
    shift 3
    acquire_slots "$d" "$tag" 1
    if [ "$mode" = run_c ]; then  # no agent: the frozen arm C pipeline's full run, one scheduler job
        local p=()
        while [ $# -gt 0 ]; do case $1 in --lab_*|--data_file|--full_*) p+=("$1" "$2"); shift 2 ;; *) shift ;; esac; done
        (cd "$d" && sandboxed "$d" -- timeout "$(stage_limit "$mode")" nextflow run "$GETH_HOME/geth/lab/jobs.nf" "${site[@]}" \
            --task run_project --run_dir "$d" "${p[@]}" --out "$d/full_c_report.txt" \
            -w "$d/geth_work" -with-trace "$d/geth_trace_$tag.txt" -ansi-log false > "$d/geth_$tag.log" 2>&1)
    else
        sandboxed "$d" -- timeout "$(stage_limit "$mode")" env PYTHONPATH="$GETH_HOME/geth" python3 -m harness.lab \
            --mode "$mode" --run_dir "$d" --data_dir "$(cat "$d/data_dir.txt")" "$@" > "$d/geth_$tag.log" 2>&1
    fi
    rc=$?
    explain_timeout $rc "$mode" "$d/geth_$tag.log"
    rm -f "$d/.geth_$tag.pid"
    return $rc
}
build_state() { echo "$2" > "$1/build_state.txt"; }
show_build() {
    local d=$1 f
    echo "Question : $(cat "$d/question.txt")"
    echo "Arm      : $(cat "$d/lab_arm.txt")"
    echo "State    : $(cat "$d/build_state.txt" 2>/dev/null || echo -)"
    echo "Agents   : $([ -d "$d/.agent_home" ] && echo "driver in the agent sandbox" || echo "driver not sandboxed") (agent-written code always runs in the lab sandbox)"
    if [ -f "$d/build_spec_c.txt" ]; then
        echo; echo "== pipeline (written by the agent): $(cd "$d/project" 2>/dev/null && ls main.nf bin/*.py 2>/dev/null | tr '\n' ' ')"
        echo "   full run: $(head -n 1 "$d/build_spec_c.txt") (cpus | memory GB | minutes)"
    else
        echo; echo "== spec (step | cpus | memory GB | minutes)"; sed 's/^/  /' "$d/build_spec.txt" 2>/dev/null || echo "  none yet"
    fi
    for f in "$d"/review_[0-9].txt; do [ -f "$f" ] && { echo; echo "== $(basename "$f" .txt)"; sed 's/^/  /' "$f"; }; done
    for f in "$d"/engineer_notes_*.txt; do [ -f "$f" ] && { echo; echo "== $(basename "$f" .txt)"; sed 's/^/  /' "$f"; }; done
    if [ -d "$d/results" ]; then
        echo; echo "== results ($d/results)"
        (cd "$d/results" && find . -type f ! -name step_log.txt ! -name exit_code.txt ! -name summary.txt -printf '  %P\t%s bytes\n' | sort)
    fi
}
show() {
    local d=$1
    [ -f "$d/design_from.txt" ] && { show_build "$d"; return; }
    echo "Question : $(cat "$d/question.txt")"
    echo "Arm      : $(cat "$d/lab_arm.txt")"
    for f in steps statistics expected rationale; do
        echo; echo "== $f"; grep -v '^# EXPERIMENTAL' "$d/lab_design_$f.txt" | sed 's/^/  /'
    done
    echo; cat "$d/lab_design_check.txt"
}

cmd=${1:-}; shift || true
banner
site=()
[ -n "${GETH_NF_CONFIG:-}" ] && site=(-c "$GETH_NF_CONFIG")
case "$cmd" in
    design)
        [ $# -ge 3 ] || usage
        data_dir=$(readlink -f "$1"); question=$2; d=$(run_dir_of "$3"); skill=true
        [ "${4:-}" = "--no-skill" ] && skill=false
        [ -e "$d" ] && { echo "Lab run '$3' already exists: choose another name." >&2; exit 1; }
        mkdir -p "$d"
        cd "$d"
        echo "$data_dir" > "$d/data_dir.txt"
        lab_stage "$d" design design --question "$question" --lab_skill "$skill" \
            || { echo "Design failed: see $d/geth_design.log" >&2; exit 1; }
        show "$d"
        ;;
    show)
        [ $# -eq 1 ] || usage
        show "$(run_dir_of "$1")"
        ;;
    list)
        [ $# -eq 0 ] || usage
        printf '%-30s %-16s %-22s %s\n' RUN DATA ARM STATE
        for d in "$lab"/*/; do
            d=${d%/}
            [ -d "$d" ] || continue
            pid=$(ls "$d"/.geth_*.pid 2>/dev/null | head -n 1 || true)
            if [ -n "$pid" ] && driver_alive "$pid"; then state=$(basename "$pid" .pid | sed 's/^\.geth_//; s/_/ round /')
            elif [ -f "$d/build_state.txt" ]; then
                state=$(cat "$d/build_state.txt")
                case $state in done*|failed*|stopped*) ;; *) state="$state (waiting for a slot)" ;; esac
            elif [ -f "$d/lab_design_check.txt" ]; then state=$(head -n 1 "$d/lab_design_check.txt")
            elif grep -qs 'stopped by geth stop' "$d/geth_design.log"; then state="stopped"
            elif [ -f "$d/geth_design.log" ]; then state="failed (see geth_design.log)"
            else state="waiting for a slot"
            fi
            data=$(basename "$(cat "$d/data_dir.txt" 2>/dev/null || echo -)")
            arm=$(cat "$d/lab_arm.txt" 2>/dev/null || echo -)
            printf '%-30s %-16s %-22s %s\n' "$(basename "$d")" "$data" "$arm" "$state"
        done
        ;;
    build)
        [ $# -eq 2 ] || { [ $# -eq 3 ] && [ "$3" = --no-skill ]; } || usage
        src=$(run_dir_of "$1"); d=$(run_dir_of "$2"); skill=true
        [ "${3:-}" = --no-skill ] && skill=false
        head -n 1 "$src/lab_design_check.txt" 2>/dev/null | grep -q '^DESIGN CHECK: OK' \
            || { echo "Lab run '$1' has no checked design: run geth lab design first." >&2; exit 1; }
        [ -e "$d" ] && { echo "Lab run '$2' already exists: choose another name." >&2; exit 1; }
        data=("$(cat "$src/data_dir.txt")"/*.h5ad)
        [ ${#data[@]} -eq 1 ] && [ -f "${data[0]}" ] || { echo "The design's data folder must hold exactly one .h5ad file." >&2; exit 1; }
        mkdir -p "$d"
        cp "$src"/lab_design_{steps,statistics,expected,rationale}.txt "$src/question.txt" "$src/data_dir.txt" "$d/"
        echo "$1" > "$d/design_from.txt"
        if [ "$skill" = true ]; then echo "B1 build, from design $1" > "$d/lab_arm.txt"
        else echo "B0 build (no coding skill), from design $1" > "$d/lab_arm.txt"; fi
        cd "$d"
        verdict=none
        for round in 1 2; do
            rm -f "$d/build_spec.txt"  # every round must check its own spec
            build_state "$d" "engineer round $round"
            lab_stage "$d" engineer "engineer_$round" --build_round "$round" --data_file "${data[0]}" --lab_skill "$skill" \
                || { build_state "$d" "failed: engineer round $round (see geth_engineer_$round.log)"; echo "Engineer round $round failed: see $d/geth_engineer_$round.log" >&2; exit 1; }
            [ -f "$d/build_spec.txt" ] || { build_state "$d" "failed: no checked spec after round $round"; echo "The engineer ended round $round without a checked spec." >&2; exit 1; }
            build_state "$d" "review round $round"
            lab_stage "$d" review "review_$round" --build_round "$round" \
                || { build_state "$d" "failed: review round $round (see geth_review_$round.log)"; echo "Review round $round failed: see $d/geth_review_$round.log" >&2; exit 1; }
            verdict=$(sed -n 's/^VERDICT: //p' "$d/review_$round.txt")
            [ "$verdict" = approve ] && break
        done
        build_state "$d" "full run (review: $verdict)"
        python3 "$GETH_HOME/geth/lab/bin/lab_build.py" render "$d" "$GETH_LAB_IMAGE" \
            "${GETH_LAB_MODELS:-$GETH_REFERENCES/celltypist_immune_v2}" "${data[0]}" \
            || { build_state "$d" "failed: could not render the pipeline"; exit 1; }
        acquire_slots "$d" pipeline 1
        nextflow run "$d/pipeline/main.nf" -c "$d/pipeline/nextflow.config" "${site[@]}" -w "$d/pipeline_work" \
            -with-trace "$d/pipeline_trace.txt" -ansi-log false > "$d/pipeline_run.log" 2>&1 && rc=0 || rc=$?
        rm -f "$d/.geth_pipeline.pid"
        if [ $rc -eq 0 ]; then build_state "$d" "done (review: $verdict)"; else build_state "$d" "failed: full run (review: $verdict; see pipeline_run.log)"; fi
        show_build "$d"
        exit $rc
        ;;
    judge)
        [ $# -ge 3 ] || usage
        d=$(run_dir_of "$1"); shift
        [ -e "$d" ] && { echo "Lab run '$(basename "$d")' already exists: choose another name." >&2; exit 1; }
        first=$(run_dir_of "$1")
        for r in "$@"; do
            src=$(run_dir_of "$r")
            head -n 1 "$src/lab_design_check.txt" 2>/dev/null | grep -q '^DESIGN CHECK: OK' \
                || { echo "Lab run '$r' has no checked design." >&2; exit 1; }
            cmp -s "$src/question.txt" "$first/question.txt" && cmp -s "$src/data_dir.txt" "$first/data_dir.txt" \
                || { echo "Lab run '$r' answers another request or data: a judge compares designs of the same request." >&2; exit 1; }
        done
        mkdir -p "$d"
        cp "$first/question.txt" "$first/data_dir.txt" "$d/"
        printf '%s\n' "$@" > "$d/judged_from.txt"
        letter=A
        for r in "$@"; do  # the designs, labelled A, B, C... (the judge does not see their run names or scores)
            src=$(run_dir_of "$r")
            { echo "== Design $letter"
              for part in steps statistics expected rationale; do
                  echo "$part:"; grep -v '^# EXPERIMENTAL' "$src/lab_design_$part.txt"; echo
              done; } >> "$d/candidates.txt"
            letter=$(echo "$letter" | tr 'A-Y' 'B-Z')
        done
        cd "$d"
        lab_stage "$d" judge judge || { echo "Judging failed: see $d/geth_judge.log" >&2; exit 1; }
        show "$d"
        ;;
    build-c)
        [ $# -eq 2 ] || usage
        src=$(run_dir_of "$1"); d=$(run_dir_of "$2")
        head -n 1 "$src/lab_design_check.txt" 2>/dev/null | grep -q '^DESIGN CHECK: OK' \
            || { echo "Lab run '$1' has no checked design: run geth lab design first." >&2; exit 1; }
        [ -e "$d" ] && { echo "Lab run '$2' already exists: choose another name." >&2; exit 1; }
        data=("$(cat "$src/data_dir.txt")"/*.h5ad)
        [ ${#data[@]} -eq 1 ] && [ -f "${data[0]}" ] || { echo "The design's data folder must hold exactly one .h5ad file." >&2; exit 1; }
        # Java and Nextflow for the sandboxed driver: the ones this Geth runs with, read-only in the sandbox
        java_home=$(readlink -f "${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}")
        tools=(--lab_java_home "$java_home" --lab_nxf_launcher "$(readlink -f "$(command -v nextflow)")"
               --lab_nxf_framework "$NXF_HOME/framework/$NXF_VER" --data_file "${data[0]}")
        [ -d "$NXF_HOME/framework/$NXF_VER" ] || { echo "No Nextflow $NXF_VER in $NXF_HOME/framework" >&2; exit 1; }
        mkdir -p "$d"
        cp "$src"/lab_design_{steps,statistics,expected,rationale}.txt "$src/question.txt" "$src/data_dir.txt" "$d/"
        echo "$1" > "$d/design_from.txt"
        echo "C build (agent-written Nextflow), from design $1" > "$d/lab_arm.txt"
        cd "$d"
        verdict=none
        for round in 1 2; do
            rm -f "$d/build_spec_c.txt"
            build_state "$d" "engineer round $round"
            lab_stage "$d" engineer_c "engineer_$round" --build_round "$round" "${tools[@]}" \
                || { build_state "$d" "failed: engineer round $round (see geth_engineer_$round.log)"; exit 1; }
            [ -f "$d/build_spec_c.txt" ] || { build_state "$d" "failed: no checked pipeline after round $round"; exit 1; }
            build_state "$d" "review round $round"
            lab_stage "$d" review_c "review_$round" --build_round "$round" "${tools[@]}" \
                || { build_state "$d" "failed: review round $round (see geth_review_$round.log)"; exit 1; }
            verdict=$(sed -n 's/^VERDICT: //p' "$d/review_$round.txt")
            [ "$verdict" = approve ] && break
        done
        python3 "$GETH_HOME/geth/lab/bin/lab_build.py" freeze-c "$d" || { build_state "$d" "failed: could not freeze the project"; exit 1; }
        read -r cpus memory minutes < <(head -n 1 "$d/build_spec_c.txt" | tr -d '|')
        build_state "$d" "full run (review: $verdict)"
        lab_stage "$d" run_c pipeline --full_cpus "$cpus" --full_memory "$memory" --full_minutes "$minutes" "${tools[@]}" && rc=0 || rc=$?
        rm -rf "$d/results" && [ -d "$d/full_c/results" ] && cp -r "$d/full_c/results" "$d/results"
        if [ $rc -eq 0 ]; then build_state "$d" "done (review: $verdict)"; else build_state "$d" "failed: full run (review: $verdict; see geth_pipeline.log)"; fi
        show_build "$d"
        exit $rc
        ;;
    stop)
        [ $# -eq 1 ] || usage
        d=$(run_dir_of "$1")
        [ -d "$d" ] || { echo "No lab run named '$1'." >&2; exit 1; }
        "$GETH_HOME/geth/bin/stop_driver.sh" "$d"
        if [ -f "$d/build_state.txt" ]; then
            case $(cat "$d/build_state.txt") in done*|failed*|stopped*) ;; *) build_state "$d" "stopped ($(cat "$d/build_state.txt"))" ;; esac
        fi
        ;;
    *) usage ;;
esac
