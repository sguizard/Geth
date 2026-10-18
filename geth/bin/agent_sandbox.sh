#!/usr/bin/env bash
# Run one of Geth's agent drivers (a Nextflow run of geth/main.nf or geth/lab/main.nf) inside a container, on the
# machine Geth runs on (phase 12). The driver keeps the network (its agents call the model service) and can still
# submit scheduler jobs, but it only sees what its run needs:
#   read-write : the run folder, Nextflow's home (plugins, pipeline assets), and GETH_AGENT_SANDBOX_RW
#                (":"-separated: e.g. the container image cache the site's Nextflow config uses)
#   read-only  : Geth, this run's data folder (the driver's --data_dir, or data_dir.txt), the reference
#                catalogue, Java, Nextflow, the scheduler's client, the lab images, and folders given with --ro
# Nothing else of the data area is visible: not the other runs, not the lab's scoring truth.
# The API key reaches the agents through APPTAINERENV_ (never a command line or a file); every other variable is
# passed explicitly (clean environment). Used when GETH_AGENT_SANDBOX=yes (site.env).
#   agent_sandbox.sh <run dir> [--ro <folder>]... -- nextflow run ...
set -euo pipefail
run_dir=$1; shift
extra=()
while [ "${1:-}" = --ro ]; do extra+=("$2"); shift 2; done
[ "${1:-}" = -- ] && shift
command -v apptainer >/dev/null || { echo "agent_sandbox: apptainer is not available" >&2; exit 1; }
# The agent image: Python 3.12 and the usual command-line tools, nothing else
# (oras://community.wave.seqera.io/library/python_findutils_coreutils_gawk_pruned:54cf9ab304820814).
image=${GETH_AGENT_IMAGE:-$GETH_WORK_ROOT/geth/containers/geth_agent_54cf9ab304820814.sif}
borrow_find=no
if [ ! -f "$image" ] && [ -z "${GETH_AGENT_IMAGE:-}" ]; then  # not pulled yet: the lab image, with the host's find
    image=${GETH_LAB_IMAGE:-$GETH_WORK_ROOT/geth/containers/geth_lab_sc_f4e5ea0d66d15d6c.sif}
    borrow_find=yes
fi
[ -f "$image" ] || { echo "agent_sandbox: no image at $image (GETH_AGENT_IMAGE)" >&2; exit 1; }
real() { readlink -f "$1"; }

java_home=$(real "${JAVA_HOME:-$(dirname "$(dirname "$(real "$(command -v java)")")")}")
launcher=$(real "$(command -v nextflow)")
mkdir -p "$run_dir/.agent_home"
binds=(-B "$(real "$run_dir")" -B "$(real "$NXF_HOME")"
       -B "$GETH_HOME:$GETH_HOME:ro" -B "$java_home:$java_home:ro" -B "$launcher:$launcher:ro")
IFS=: read -r -a rw_extra <<< "${GETH_AGENT_SANDBOX_RW:-}"
for d in "${rw_extra[@]}"; do [ -n "$d" ] && [ -d "$d" ] && binds+=(-B "$(real "$d"):$(real "$d")"); done
data_dir=
prev=
for a in "$@"; do [ "$prev" = --data_dir ] && data_dir=$a; prev=$a; done
[ -z "$data_dir" ] && [ -f "$run_dir/data_dir.txt" ] && data_dir=$(cat "$run_dir/data_dir.txt")
for d in "$data_dir" "$GETH_REFERENCES" "$GETH_WORK_ROOT/geth/containers" "${SGE_ROOT:-}" \
         "${GETH_JAVA17_HOME:-}" "${extra[@]}"; do
    [ -n "$d" ] && [ -e "$d" ] && binds+=(-B "$(real "$d"):$(real "$d"):ro")
done
# The scheduler's ports come from the host's /etc/services, which the container does not see.
qmaster=$(getent services sge_qmaster 2>/dev/null | awk '{split($2, p, "/"); print p[1]}')
execd=$(getent services sge_execd 2>/dev/null | awk '{split($2, p, "/"); print p[1]}')

# Settings passed in through a file only you can read (never the key itself: that goes through APPTAINERENV_).
key_var=${GETH_LLM_API_KEY_VAR:-GETH_LLM_API_KEY}
env_file=$(real "$run_dir")/.agent_home/sandbox.env
umask 077
sq() { local v=${1//\'/\'\\\'\'}; printf "'%s'" "$v"; }   # apptainer's env file reads single quotes, not \ escapes
{
    echo "HOME=$(sq "$(real "$run_dir")/.agent_home")"
    echo "JAVA_HOME=$(sq "$java_home")"
    echo "PATH=$(sq "$java_home/bin:$(dirname "$launcher"):${SGE_ROOT:+$SGE_ROOT/bin/lx-amd64:}/opt/conda/bin:/usr/local/bin:/usr/bin:/bin")"
    for v in $(compgen -e | grep -E '^(GETH_|NXF_|SGE_)'); do
        [ "$v" = "$key_var" ] || echo "$v=$(sq "${!v}")"
    done
    [ -n "$qmaster" ] && echo "SGE_QMASTER_PORT=$qmaster"
    [ -n "$execd" ] && echo "SGE_EXECD_PORT=$execd"
    echo "USER=$(id -un)"
    echo "GETH_IN_AGENT_SANDBOX=yes"
} > "$env_file"
export "APPTAINERENV_$key_var=${!key_var:-}"

# The site's task prelude (e.g. ". /etc/profile.d/modules.sh; module load apptainer") also runs before the
# driver's local tools, inside the sandbox: a stub makes it a no-op there. Scheduler jobs run outside, as usual.
printf 'module() { :; }\nml() { :; }\n' > "$(real "$run_dir")/.agent_home/modules.sh"
binds+=(-B "$(real "$run_dir")/.agent_home/modules.sh:/etc/profile.d/modules.sh:ro")
[ $borrow_find = yes ] && binds+=(-B /usr/bin/find:/usr/bin/find:ro)

exec apptainer exec --containall --home "$(real "$run_dir")/.agent_home" "${binds[@]}" --pwd "$(pwd -P)" \
    --env-file "$env_file" "$image" "$@"
