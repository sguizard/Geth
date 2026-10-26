# Driver slots on a shared machine (sourced by geth and geth lab). A Nextflow driver is one JVM: a run uses one
# (the nf-core pipeline's), a lab stage one (its jobs'), a plan none (one for a single-cell follow-up). GETH_MAX_DRIVERS
# (unset or 0: no limit) caps how many run at once on this machine; a command that would exceed it waits for a slot.
# Each active driver leaves "<host> <pid> <drivers>" in a .geth_<mode>.pid file in its run folder.

geth_version() {  # the VERSION file, the commit when Geth runs from a git clone, and whether the code was changed
    local commit changed=
    commit=$(git -C "$GETH_HOME" rev-parse --short HEAD 2>/dev/null || true)
    [ -n "$commit" ] && [ -n "$(git -C "$GETH_HOME" status --porcelain --untracked-files=no 2>/dev/null)" ] \
        && changed=", with local changes"
    echo "Geth $(cat "$GETH_HOME/VERSION" 2>/dev/null || echo unknown)${commit:+ (commit $commit$changed)}"
}

record_version() {  # record_version <run_dir> <stage>: which Geth worked on this run, and when (geth_version.txt)
    printf '%s %s %s\n' "$2" "$(date '+%F %T')" "$(geth_version)" >> "$1/geth_version.txt"
}

slots_in_use() {
    local used=0 f host pid n
    for f in "$GETH_RUNS_DIR"/*/.geth_*.pid "$GETH_RUNS_DIR"/lab/*/.geth_*.pid; do
        [ -f "$f" ] || continue
        read -r host pid n < "$f" 2>/dev/null || continue
        [ -z "$pid" ] && { pid=$host; host=$(hostname); }   # older pid files: "<pid>" only
        [ "$host" = "$(hostname)" ] || continue
        kill -0 "$pid" 2>/dev/null && grep -qs geth "/proc/$pid/cmdline" && used=$(( used + ${n:-1} ))
    done
    echo "$used"
}

acquire_slots() {  # acquire_slots <run_dir> <mode> <drivers>: wait for free slots, then record this driver
    local dir=$1 mode=$2 need=$3 max=${GETH_MAX_DRIVERS:-0} waited=0 used
    if ! [ "$max" -gt 0 ] 2>/dev/null; then
        echo "$(hostname) $$ $need" > "$dir/.geth_$mode.pid"
        return 0
    fi
    [ "$need" -gt "$max" ] && need=$max
    exec 9> "/tmp/geth-driver-slots-$(id -u).lock"  # slots are per machine: a local lock
    while :; do
        flock 9
        used=$(slots_in_use)
        if [ $(( used + need )) -le "$max" ]; then
            echo "$(hostname) $$ $need" > "$dir/.geth_$mode.pid"
            flock -u 9
            return 0
        fi
        flock -u 9
        [ $(( waited % 300 )) -eq 0 ] && echo "Waiting for a free slot: $used Nextflow driver(s) running on $(hostname), limit $max (GETH_MAX_DRIVERS)." >&2
        sleep 30; waited=$(( waited + 30 ))
    done
}

driver_alive() {  # driver_alive <pid file>
    local host pid n
    [ -f "$1" ] || return 1
    read -r host pid n < "$1" 2>/dev/null || return 1
    [ -z "$pid" ] && { pid=$host; host=$(hostname); }
    [ "$host" = "$(hostname)" ] && kill -0 "$pid" 2>/dev/null
}

stage_limit() {  # stage_limit <mode>: how long an agent stage may run (a hung agent must not hold its slot forever)
    case $1 in
        run|pipeline) echo "${GETH_RUN_TIMEOUT:-72h}" ;;
        engineer*) echo "${GETH_ENGINEER_TIMEOUT:-4h}" ;;
        *) echo "${GETH_AGENT_TIMEOUT:-2h}" ;;
    esac
}

explain_timeout() {  # explain_timeout <exit code> <mode> <log>: say plainly when a stage hit its time limit
    if [ "$1" -eq 124 ]; then
        local msg="Geth: the $2 stage was stopped after its time limit ($(stage_limit "$2")); raise it in site.env (GETH_AGENT_TIMEOUT, GETH_ENGINEER_TIMEOUT or GETH_RUN_TIMEOUT) if the run was making progress."
        echo "$msg" >> "$3"
        echo "$msg" >&2
    fi
}

sandboxed() {  # sandboxed <run_dir> [--ro <folder>]... -- <command...>: in the agent sandbox when the site asks
    if [ "${GETH_AGENT_SANDBOX:-no}" = yes ]; then
        "$GETH_HOME/geth/bin/agent_sandbox.sh" "$@"
    else
        while [ "$1" != -- ]; do shift; done
        shift
        "$@"
    fi
}

use_model() {  # use_model <name> [<budget USD>]: a model a person chose for this command (--model), within a budget
    # The site defines it as GETH_MODEL_<NAME>_* (or GETH_PLANNER_<NAME>_*, the Geth 2.0.0 name): MODEL, PRICES,
    # BUDGET_USD, and optionally API, REASONING, BASE_URL, API_KEY_VAR. Exported as GETH_MODEL_* for the agents.
    local name=$1 budget=${2:-} up k v w
    [[ "$name" =~ ^[A-Za-z0-9_]+$ ]] || { echo "Model names use letters, digits and '_' (got '$name')." >&2; return 1; }
    up=${name^^}
    for k in MODEL PRICES BUDGET_USD API REASONING BASE_URL API_KEY_VAR; do
        v=GETH_MODEL_${up}_$k; w=GETH_PLANNER_${up}_$k
        if [ -n "${!v:-}" ]; then export "GETH_MODEL_$k=${!v}"
        elif [ -n "${!w:-}" ]; then export "GETH_MODEL_$k=${!w}"; fi
    done
    [ -n "${GETH_MODEL_MODEL:-}" ] || { echo "No model '$name' in the site settings (GETH_MODEL_${up}_MODEL)." >&2; return 1; }
    [ -n "$budget" ] && export GETH_MODEL_BUDGET_USD=$budget
    export GETH_MODEL_BASE_URL=${GETH_MODEL_BASE_URL:-$GETH_LLM_BASE_URL}
    export GETH_MODEL_API_KEY_VAR=${GETH_MODEL_API_KEY_VAR:-$GETH_LLM_API_KEY_VAR}
    unset GETH_PLANNER_MODEL  # one chosen model at a time
}

# What a chosen model costs. Every agent stage on it adds "<run>:<stage> <usd> <model>" to a spend file
# (GETH_MODEL_SPEND, else the run's own model_spend.txt). A command that starts several stages (geth legion run,
# geth lab) has a total, GETH_MODEL_TOTAL_USD (its --budget): each stage gets what is left of it, counted in the
# spend file from the line where the command started (GETH_MODEL_SPEND_FROM), and a stage that would find nothing
# left is not started. Commands started by it (a project's steps) inherit all of this. The agents' client writes
# its running usage to GETH_MODEL_USAGE_FILE after every request, so a stage stopped by its time limit is counted.
model_total() {  # model_total <USD> [<spend file>]: this command's total; without a file, its first stage's run
    export GETH_MODEL_TOTAL_USD=$1
    if [ -n "${2:-}" ]; then
        touch "$2"
        export GETH_MODEL_SPEND=$2 GETH_MODEL_SPEND_FROM; GETH_MODEL_SPEND_FROM=$(wc -l < "$2")
    fi
}

paid_stage_start() {  # paid_stage_start <run_dir> <tag> <log>: 1 when the command's total is spent (stage not started)
    [ -n "${GETH_MODEL_MODEL:-}" ] || return 0
    export GETH_MODEL_USAGE_FILE="$1/.model_usage_$2.json"
    rm -f "$GETH_MODEL_USAGE_FILE"
    [ -n "${GETH_MODEL_TOTAL_USD:-}" ] || return 0
    [ -n "${GETH_MODEL_SPEND:-}" ] || model_total "$GETH_MODEL_TOTAL_USD" "$1/model_spend.txt"
    local left
    left=$(python3 -c '
import os, sys
total, path, start = float(sys.argv[1]), sys.argv[2], int(sys.argv[3])
lines = open(path).readlines()[start:] if os.path.isfile(path) else []
print(f"{total - sum(float(l.split()[1]) for l in lines if len(l.split()) > 1):.4f}")' \
        "$GETH_MODEL_TOTAL_USD" "$GETH_MODEL_SPEND" "${GETH_MODEL_SPEND_FROM:-0}")
    if ! python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) > 0.01 else 1)' "$left"; then
        echo "Budget spent: \$$GETH_MODEL_TOTAL_USD for this command on $GETH_MODEL_MODEL (see $GETH_MODEL_SPEND); $2 not started." \
            | tee -a "$3" >&2
        return 1
    fi
    export GETH_MODEL_BUDGET_USD=$left
}

paid_stage_end() {  # paid_stage_end <run_dir> <tag> <log>: what the stage spent, into the spend file
    [ -n "${GETH_MODEL_MODEL:-}" ] || return 0
    python3 -c '
import json, os, sys
usage_file, log, tag, model = sys.argv[1:5]
try:  # the client running usage: there even when the stage was stopped
    usd = json.load(open(usage_file)).get("usd", 0)
except (OSError, ValueError):
    lines = [l for l in open(log, errors="replace") if l.startswith("Model usage:")] if os.path.isfile(log) else []
    usd = json.loads(lines[-1].split(":", 1)[1]).get("usd", 0) if lines else 0
print(tag, f"{float(usd or 0):.4f}", model)' "${GETH_MODEL_USAGE_FILE:-}" "$3" "$(basename "$1"):$2" "$GETH_MODEL_MODEL" \
        >> "${GETH_MODEL_SPEND:-$1/model_spend.txt}"
    rm -f "${GETH_MODEL_USAGE_FILE:-}"
}

model_spent() {  # model_spent <spend file>: "$X.XX on <model> (<n> stages)", or nothing
    [ -s "$1" ] || return 0
    python3 -c '
import sys
rows = [l.split() for l in open(sys.argv[1]) if len(l.split()) >= 3]
print(f"${sum(float(r[1]) for r in rows):.2f} on {(chr(44) + chr(32)).join(sorted({r[2] for r in rows}))} ({len(rows)} stages)")' "$1"
}
