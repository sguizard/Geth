#!/usr/bin/env bash
# Stop what Geth is doing in a run folder (geth stop, geth lab stop): stop_driver.sh <run_dir>
#   1. The Geth command (the pid in .geth_<stage>.pid) is stopped first, so it starts no further stage.
#   2. Every Nextflow driver below it (Geth's, the nf-core pipeline's, a lab pipeline's) gets SIGTERM: each one
#      cancels its own scheduler jobs and local tasks. They get GETH_STOP_GRACE seconds (default 120).
#   3. What is left of the process tree (sandbox, agents' tools) gets SIGTERM, then SIGKILL.
#   4. Scheduler jobs still queued or running in the run folder's work folders are deleted.
# A stopped run keeps its work folders: geth run resumes it.
set -uo pipefail
run_dir=${1:?usage: stop_driver.sh <run_dir>}
source "$(dirname "$(readlink -f "$0")")/driver_slots.sh"
grace=${GETH_STOP_GRACE:-120}

descendants() {  # descendants <pid>...: every process below them, parents first
    ps -e -o pid=,ppid= | awk -v roots="$*" '
        { kids[$2] = kids[$2] " " $1 }
        END { n = split(roots, q, " "); for (i = 1; i <= n; i++) { m = split(kids[q[i]], c, " "); for (j = 1; j <= m; j++) q[++n] = c[j] }
              for (i = split(roots, r, " ") + 1; i <= n; i++) print q[i] }'
}
alive() { local p; for p in "$@"; do kill -0 "$p" 2>/dev/null && echo "$p"; done; }
is_nextflow() { tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null | grep -q 'nextflow\.cli\.Launcher\|nextflow-.*-one\.jar'; }

roots=() stages=()
for f in "$run_dir"/.geth_*.pid; do
    [ -f "$f" ] || continue
    read -r host pid _ < "$f" 2>/dev/null || continue
    [ -z "$pid" ] && { pid=$host; host=$(hostname); }
    if [ "$host" != "$(hostname)" ]; then
        echo "$(basename "$f" .pid | sed 's/^\.geth_//'): started on $host; run geth stop there." >&2
        continue
    fi
    stage=$(basename "$f" .pid | sed 's/^\.geth_//')
    if driver_alive "$f" && grep -qs geth "/proc/$pid/cmdline"; then
        roots+=("$pid"); stages+=("$stage")
    else
        rm -f "$f"  # left by a driver that ended without tidying up
    fi
done

# Scheduler jobs of this run: their working folder is inside it (Nextflow submits each task from its work dir).
run_jobs() {
    command -v qstat > /dev/null || return 0
    local real; real=$(readlink -f "$run_dir")
    qstat -u "$USER" 2>/dev/null | awk 'NR > 2 { print $1 }' | sort -u | while read -r id; do
        qstat -j "$id" 2>/dev/null | awk -v a="$run_dir/" -v b="$real/" \
            '$1 == "cwd:" && (index($2, a) == 1 || index($2, b) == 1) { f = 1 } END { exit !f }' && echo "$id"
    done
}

if [ ${#roots[@]} -eq 0 ]; then
    echo "Nothing is running in $(basename "$run_dir")."
else
    echo "Stopping $(basename "$run_dir") (${stages[*]}) ..."
    tree=($(descendants "${roots[@]}"))
    kill -TERM "${roots[@]}" 2>/dev/null
    drivers=()
    for p in "${tree[@]}"; do is_nextflow "$p" && drivers+=("$p"); done
    [ ${#drivers[@]} -gt 0 ] && kill -TERM "${drivers[@]}" 2>/dev/null
    waited=0
    while [ -n "$(alive "${drivers[@]}")" ] && [ $waited -lt "$grace" ]; do sleep 2; waited=$(( waited + 2 )); done
    left=($(alive "${roots[@]}" "${tree[@]}"))
    if [ ${#left[@]} -gt 0 ]; then
        kill -TERM "${left[@]}" 2>/dev/null; sleep 5
        left=($(alive "${left[@]}"))
        [ ${#left[@]} -gt 0 ] && kill -KILL "${left[@]}" 2>/dev/null
    fi
    # The nf-core launch it interrupted does not count towards the operator's attempts.
    last=$(find "$run_dir" -maxdepth 1 -type d -name 'attempt_*' | sed 's/.*attempt_//' | sort -n | tail -n 1)
    last=${last:+$run_dir/attempt_$last}
    [ -n "$last" ] && [ -f "$last/nextflow.log" ] && ! grep -qs 'Pipeline completed successfully' "$last/nextflow.log" \
        && date '+%F %T' > "$last/STOPPED"
    for s in "${stages[@]}"; do
        rm -f "$run_dir/.geth_$s.pid"
        [ -f "$run_dir/geth_$s.log" ] && echo "Geth: stopped by geth stop ($(whoami), $(date '+%F %T'))." >> "$run_dir/geth_$s.log"
    done
    echo "Stopped: ${#drivers[@]} Nextflow driver(s), $(( ${#tree[@]} + ${#roots[@]} )) process(es)."
fi

jobs=($(run_jobs))
if [ ${#jobs[@]} -gt 0 ]; then
    qdel "${jobs[@]}" > /dev/null 2>&1
    echo "Deleted ${#jobs[@]} scheduler job(s) left by the run: ${jobs[*]}"
fi
exit 0
