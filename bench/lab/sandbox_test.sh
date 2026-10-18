#!/usr/bin/env bash
# Run the sandbox escape test (bench/lab/sandbox_escape_test.py) through lab_sandbox.sh, here or as an SGE job:
#   bench/lab/sandbox_test.sh [--nextflow] <image> <input.h5ad>     (--nextflow: arm C, the probe runs in a Nextflow driver)
#   qsub -cwd -j y -l h_rt=0:20:00 -l h_rss=8G -P <project> -v GETH_HOME=$GETH_HOME,GETH_SANDBOX_MODULE=<module> \
#        bench/lab/sandbox_test.sh <image> <input.h5ad>
# Prints the probe's JSON and SANDBOX TEST: PASS or FAIL.
set -uo pipefail
here=${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}
if [ "${1:-}" = --nextflow ]; then nextflow_probe=yes; shift; else nextflow_probe=no; fi
image=$1 input=$2
if ! command -v apptainer >/dev/null; then  # a bare SGE job: load the module the site's tasks use
    . /etc/profile.d/modules.sh && module load "${GETH_SANDBOX_MODULE:-apptainer}"
fi
echo "apptainer: $(apptainer --version)"
work=$(mktemp -d "${TMPDIR:-/tmp}/geth_sandbox_test.XXXXXX")
cd "$work" || exit 1
if [ $nextflow_probe = yes ]; then  # arm C: Groovy in the Nextflow driver probes the sandbox
    sed "s|^params.probe  = ''|params.probe  = '$here,$(dirname "$input"),$(dirname "$image")'|" \
        "$here/bench/lab/sandbox_nf_escape/main.nf" > main.nf.tmp && mkdir -p project/bin && mv main.nf.tmp project/main.nf
    "$here/geth/lab/bin/lab_nf_sandbox.sh" "$image" project "$input" /nonexistent 1 4 10 out > sandbox.txt
    cat sandbox.txt | head -n 8
    json=$(grep -o 'PROBE {.*}' out/nextflow_console.txt | sed 's/^PROBE //' | tail -n 1)
    links=$(find out -type l | wc -l)
    echo "links copied back to the host: $links"
    python3 - "$json" "$links" <<'PYEOF'
import json, sys
r = json.loads(sys.argv[1]) if sys.argv[1] else {"probe": "did not run"}
print("probe:", r)
bad = {k: v for k, v in r.items() if v}
if int(sys.argv[2]):
    bad["links_copied_back"] = int(sys.argv[2])
print("SANDBOX TEST (Nextflow driver):", "PASS" if not bad else f"FAIL {bad}")
PYEOF
    cd / && rm -rf "$work"
    exit 0
fi
# The step gets the folders to probe as extra arguments: append them to its argv via a wrapper copy.
sed "s|^probe_dirs = .*|probe_dirs = [\"$here\", \"$(dirname "$input")\", \"$(dirname "$image")\"]|" \
    "$here/bench/lab/sandbox_escape_test.py" > probe.py
"$here/geth/lab/bin/lab_sandbox.sh" "$image" probe.py "$input" /nonexistent 1 10 out > sandbox.txt
cat sandbox.txt
echo "host: $(hostname); secret-like variables outside the sandbox: $(env | cut -d= -f1 | grep -iE 'KEY|TOKEN|SECRET|^ELM' | tr '\n' ' ')"
json=$(grep '^{' out/step_log.txt | tail -n 1)
links=$(find out -type l | wc -l)
echo "links copied back to the host: $links"
python3 - "$json" "$links" <<'PYEOF'
import json, sys
r = json.loads(sys.argv[1]) if sys.argv[1] else {"probe": "did not run"}
bad = {k: v for k, v in r.items() if v and not (k == "home" and v == "/work")}
if int(sys.argv[2]):
    bad["links_copied_back"] = int(sys.argv[2])
print("SANDBOX TEST:", "PASS" if not bad and "probe" not in r else f"FAIL {bad}")
PYEOF
cd / && rm -rf "$work"
