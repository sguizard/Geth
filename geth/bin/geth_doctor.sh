#!/usr/bin/env bash
# Check a Geth installation and its site configuration (called by `geth doctor`, after env.sh).
# Prints one line per check; exit status 1 if anything needed is missing.
set -uo pipefail
problems=0
ok()   { printf '  ok    %-16s %s\n' "$1" "$2"; }
warn() { printf '  warn  %-16s %s\n' "$1" "$2"; }
bad()  { printf '  FAIL  %-16s %s\n' "$1" "$2"; problems=$((problems + 1)); }

commit=$(git -C "$GETH_HOME" rev-parse --short HEAD 2>/dev/null || true)
echo "Geth $(cat "$GETH_HOME/VERSION" 2>/dev/null || echo unknown)${commit:+ (commit $commit)} in $GETH_HOME"
echo "Site configuration: ${GETH_SITE_ENV:-$GETH_HOME/site/site.env}"
echo

echo "Folders"
for v in GETH_DATA_ROOT GETH_RUNS_DIR GETH_REFERENCES; do
    d=${!v}
    if [ -d "$d" ] && [ -w "$d" ]; then ok "$v" "$d"
    elif [ -d "$d" ]; then
        [ "$v" = GETH_RUNS_DIR ] && bad "$v" "$d is not writable" || ok "$v" "$d (read-only)"
    else bad "$v" "$d does not exist (mkdir -p it)"
    fi
done
case "$GETH_RUNS_DIR/" in
    "$GETH_DATA_ROOT"/*) ;;
    *) warn "follow-ups" "GETH_RUNS_DIR is outside GETH_DATA_ROOT: agents cannot read finished runs (geth plan --from)" ;;
esac
n=$(find "$GETH_REFERENCES" -mindepth 2 -maxdepth 2 -name README.txt 2>/dev/null | wc -l)
if [ "$n" -gt 0 ]; then ok "references" "$n catalogue entries"
else warn "references" "catalogue is empty: stage a genome (geth/references/stage_ensembl.sh)"
fi
echo

echo "Software"
if command -v nextflow > /dev/null; then
    nv=$(nextflow -version 2>/dev/null | grep -oE 'version [0-9]+\.[0-9]+\.[0-9]+' | head -n 1 | cut -d' ' -f2)
    if [ -z "$nv" ]; then bad "nextflow" "$(command -v nextflow) did not report a version (Java missing?)"
    elif printf '%s\n26.10.0\n' "$nv" | sort -V -C 2>/dev/null && [ "$nv" != 26.10.0 ]; then
        bad "nextflow" "$nv is too old: Geth needs 26.10 or later (GETH_NXF_VER)"
    else ok "nextflow" "$nv ($(command -v nextflow))"
    fi
else bad "nextflow" "not on PATH (https://www.nextflow.io/docs/latest/install.html)"
fi
if command -v java > /dev/null; then ok "java" "$(java -version 2>&1 | head -n 1)"
else bad "java" "not on PATH (Nextflow needs Java 17 or later)"
fi
engine=""
for e in apptainer singularity docker podman; do
    command -v "$e" > /dev/null && { engine="$e $("$e" --version 2>/dev/null | head -n 1)"; break; }
done
[ -n "$engine" ] && ok "containers" "$engine" || bad "containers" "no apptainer, singularity, docker or podman on PATH"
command -v python3 > /dev/null && ok "python3" "$(python3 --version 2>&1)" || bad "python3" "not on PATH"
if [ -n "${GETH_JAVA17_HOME:-}" ]; then
    [ -x "$GETH_JAVA17_HOME/bin/java" ] && ok "java 17" "$GETH_JAVA17_HOME" || bad "java 17" "$GETH_JAVA17_HOME/bin/java not found"
else warn "java 17" "GETH_JAVA17_HOME not set: nf-core/eager (DSL1) will not run"
fi
echo

echo "Nextflow settings"
if [ -n "${GETH_NF_CONFIG:-}" ]; then
    [ -f "$GETH_NF_CONFIG" ] && ok "GETH_NF_CONFIG" "$GETH_NF_CONFIG" || bad "GETH_NF_CONFIG" "$GETH_NF_CONFIG not found"
else warn "GETH_NF_CONFIG" "not set: Geth's own tasks use Nextflow's defaults (local executor, no containers)"
fi
[ -n "${GETH_NFCORE_PROFILE:-}" ] && ok "nf-core profile" "$GETH_NFCORE_PROFILE" \
    || warn "nf-core profile" "GETH_NFCORE_PROFILE not set: nf-core pipelines run without a container profile"
if [ -n "${GETH_NFCORE_CONFIG:-}" ]; then
    [ -f "$GETH_NFCORE_CONFIG" ] && ok "nf-core config" "$GETH_NFCORE_CONFIG" || bad "nf-core config" "$GETH_NFCORE_CONFIG not found"
fi
if [ "$GETH_GPU" = yes ]; then
    if [ -n "${GETH_GPU_CONFIG:-}" ] && [ ! -f "$GETH_GPU_CONFIG" ]; then bad "GPU" "$GETH_GPU_CONFIG not found"
    else ok "GPU" "yes${GETH_GPU_CONFIG:+ ($GETH_GPU_CONFIG)}"
    fi
else ok "GPU" "no (CellBender runs on CPUs)"
fi
echo

echo "Language model"
ok "endpoint" "$GETH_LLM_BASE_URL"
case " ${GETH_LLM_ALLOWED_MODELS//,/ } " in
    *" $GETH_LLM_MODEL "*) ok "model" "$GETH_LLM_MODEL (allowed)" ;;
    *) bad "model" "$GETH_LLM_MODEL is not in GETH_LLM_ALLOWED_MODELS ($GETH_LLM_ALLOWED_MODELS)" ;;
esac
if [ -z "${!GETH_LLM_API_KEY_VAR:-}" ]; then
    bad "API key" "\$$GETH_LLM_API_KEY_VAR is empty (export it in your shell profile)"
else
    ok "API key" "\$$GETH_LLM_API_KEY_VAR is set"
    # The key goes in a request header from Python: never on a command line, never printed.
    msg=$(python3 -I - <<'EOF'
import json, os, sys, urllib.error, urllib.request
base = os.environ["GETH_LLM_BASE_URL"].rstrip("/")
key = os.environ.get(os.environ["GETH_LLM_API_KEY_VAR"], "")
request = urllib.request.Request(base + "/models", headers={"Authorization": "Bearer " + key})
try:
    with urllib.request.urlopen(request, timeout=30) as r:
        ids = [m.get("id") for m in json.load(r).get("data", [])]
except urllib.error.HTTPError as e:
    print(f"FAIL the endpoint answered HTTP {e.code} ({'key refused' if e.code in (401, 403) else e.reason})")
    sys.exit()
except Exception as e:
    print(f"FAIL endpoint unreachable ({e.__class__.__name__}: {e})")
    sys.exit()
model = os.environ["GETH_LLM_MODEL"]
if model in ids:
    print(f"ok key accepted; {model} is served")
else:
    print(f"warn key accepted, but the endpoint does not list {model} ({len(ids)} models listed)")
EOF
)
    case "$msg" in
        ok*) ok "endpoint check" "${msg#ok }" ;;
        warn*) warn "endpoint check" "${msg#warn }" ;;
        *) bad "endpoint check" "${msg#FAIL }" ;;
    esac
fi
echo

if [ "$problems" -eq 0 ]; then
    echo "Geth is ready."
else
    echo "$problems problem(s) to fix: see docs/installation.md and docs/configuration.md."
    exit 1
fi
