# Driver slots on a shared machine (sourced by geth and geth lab). A Nextflow driver is one JVM: planning and
# lab designs use one, a run uses two (Geth's and the nf-core pipeline's). GETH_MAX_DRIVERS (unset or 0: no
# limit) caps how many run at once on this machine; a command that would exceed it waits for a free slot.
# Each active driver leaves "<host> <pid> <drivers>" in a .geth_<mode>.pid file in its run folder.

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

sandboxed() {  # sandboxed <run_dir> [--ro <folder>]... -- <command...>: in the agent sandbox when the site asks
    if [ "${GETH_AGENT_SANDBOX:-no}" = yes ]; then
        "$GETH_HOME/geth/bin/agent_sandbox.sh" "$@"
    else
        while [ "$1" != -- ]; do shift; done
        shift
        "$@"
    fi
}
