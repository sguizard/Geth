# Geth environment: source this file (bash) before using Geth.
#   source /path/to/Geth/env.sh
# It loads the site configuration (site/site.env, or the file named by GETH_SITE_ENV) and derives Geth's
# settings from it. Every variable is described in docs/configuration.md.

GETH_HOME=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export GETH_HOME

_geth_site=${GETH_SITE_ENV:-$GETH_HOME/site/site.env}
if [ ! -f "$_geth_site" ]; then
    echo "Geth: no site configuration at $_geth_site" >&2
    echo "      Copy site/site.env.example to site/site.env and fill it in (docs/installation.md)." >&2
    unset _geth_site
    return 1 2>/dev/null || exit 1
fi
# shellcheck source=/dev/null
source "$_geth_site"
unset _geth_site

if [ -z "${GETH_WORK_ROOT:-}" ] || [ -z "${GETH_LLM_BASE_URL:-}" ] || [ -z "${GETH_LLM_MODEL:-}" ]; then
    echo "Geth: the site configuration must set GETH_WORK_ROOT, GETH_LLM_BASE_URL and GETH_LLM_MODEL" >&2
    return 1 2>/dev/null || exit 1
fi

# Derived settings (each can be set in the site configuration instead). Existing folders are resolved to
# their real path: Geth compares paths as text, and a symbolic link (e.g. /home -> /exports/home) would not match.
_geth_real() { if [ -d "$1" ]; then (cd "$1" && pwd -P); else printf '%s\n' "$1"; fi; }
GETH_WORK_ROOT=$(_geth_real "$GETH_WORK_ROOT"); export GETH_WORK_ROOT
GETH_DATA_ROOT=$(_geth_real "${GETH_DATA_ROOT:-$GETH_WORK_ROOT}"); export GETH_DATA_ROOT
GETH_RUNS_DIR=$(_geth_real "${GETH_RUNS_DIR:-$GETH_WORK_ROOT/runs}"); export GETH_RUNS_DIR
GETH_REFERENCES=$(_geth_real "${GETH_REFERENCES:-$GETH_WORK_ROOT/references}"); export GETH_REFERENCES
unset -f _geth_real
export GETH_LLM_ALLOWED_MODELS=${GETH_LLM_ALLOWED_MODELS:-$GETH_LLM_MODEL}
export GETH_LLM_API_KEY_VAR=${GETH_LLM_API_KEY_VAR:-GETH_LLM_API_KEY}
export GETH_GPU=${GETH_GPU:-no}
export NXF_HOME=${NXF_HOME:-$GETH_WORK_ROOT/nextflow}
# Images (Seqera Containers, pulled once into the work root): the lab's analysis image (scanpy, celltypist,
# pydeseq2, harmonypy, scikit-image, scikit-misc), and the small image the agents' drivers run in (GETH_AGENT_SANDBOX).
export GETH_LAB_IMAGE=${GETH_LAB_IMAGE:-$GETH_WORK_ROOT/geth/containers/geth_lab_sc_8ead628d7c7c6607.sif}
export GETH_AGENT_IMAGE=${GETH_AGENT_IMAGE:-$GETH_WORK_ROOT/geth/containers/geth_agent_54cf9ab304820814.sif}
export NXF_VER=${GETH_NXF_VER:-26.10.2}  # the version Geth's jobs (typed processes) are tested with

case ":$PATH:" in
    *":$GETH_HOME/geth:"*) ;;
    *) export PATH="$GETH_HOME/geth:$PATH" ;;  # the `geth` command
esac

# Geth only ever reads the key named by GETH_LLM_API_KEY_VAR: never let a tool pick up another provider key.
unset OPENAI_API_KEY OPENAI_BASE_URL ANTHROPIC_API_KEY

# Nextflow drivers often run on a shared login node: keep their JVMs small outside scheduler jobs.
if [ -z "${JOB_ID:-}${SLURM_JOB_ID:-}${PBS_JOBID:-}${LSB_JOBID:-}" ]; then
    export NXF_OPTS="${NXF_OPTS:--Xms512m -Xmx4g -XX:ActiveProcessorCount=${GETH_DRIVER_CPUS:-2}}"
fi

# Environment modules requested by the site (e.g. Java and apptainer on a cluster).
if [ -n "${GETH_MODULES:-}" ]; then
    type module >/dev/null 2>&1 || source /etc/profile.d/modules.sh 2>/dev/null
    # shellcheck disable=SC2086
    module load $GETH_MODULES >/dev/null 2>&1 || echo "Geth: could not load modules: $GETH_MODULES" >&2
fi
