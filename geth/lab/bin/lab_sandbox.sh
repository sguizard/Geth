#!/usr/bin/env bash
# Geth lab (EXPERIMENTAL): run one agent-written analysis step in a sandbox.
#   lab_sandbox.sh [--strict] <image> <step.py> <input.h5ad> <models dir> <cpus> <minutes> <out dir>
# The step sees two folders only: /in (read-only: step.py, input.h5ad, models/) and /work (read-write, empty).
# It runs as  python3 /in/step.py /in/input.h5ad /work/output.h5ad  from /work, with no network, no home
# folder, no host files, and a clean environment (no keys, no site settings). The regular files it writes in
# /work (also its home folder) are then moved to <out dir>; links are dropped, so nothing written inside can point outside.
# Prints "SANDBOX EXIT: <code>", the end of the step's log and the files written. Exits 0 (a tool must), or
# with the step's code under --strict (pipelines).
set -uo pipefail
strict=no
[ "${1:-}" = --strict ] && { strict=yes; shift; }
[ $# -eq 7 ] || { echo "usage: lab_sandbox.sh [--strict] <image> <step.py> <input.h5ad> <models dir> <cpus> <minutes> <out dir>" >&2; exit 2; }
image=$1 step=$2 input=$3 models=$4 cpus=$5 minutes=$6 out=$7
command -v apptainer >/dev/null || { echo "SANDBOX EXIT: 127  apptainer is not available on $(hostname)"; [ "$strict" = yes ] && exit 127; exit 0; }

box=$(mktemp -d "$PWD/sandbox.XXXXXX")
mkdir -p "$box/in/models" "$box/work/.cache" "$out"
cp "$step" "$box/in/step.py"
cp "$input" "$box/in/input.h5ad"
if [ -d "$models" ]; then cp "$models"/*.pkl "$box/in/models/" 2>/dev/null; fi
ln -s /in/models "$box/work/models"   # ./models inside the sandbox
env_list="XDG_CACHE_HOME=/work/.cache,NUMBA_CACHE_DIR=/work/.cache/numba,MPLCONFIGDIR=/work/.cache/mpl"
env_list+=",CELLTYPIST_FOLDER=/work/.cache/celltypist,PYTHONDONTWRITEBYTECODE=1,MPLBACKEND=Agg"
env_list+=",OMP_NUM_THREADS=$cpus,OPENBLAS_NUM_THREADS=$cpus,MKL_NUM_THREADS=$cpus,NUMBA_NUM_THREADS=$cpus"

start=$(date +%s)
timeout "${minutes}m" apptainer exec --containall --home "$box/work:/work" --net --network none \
    -B "$box/in:/in:ro" --pwd /work --env "$env_list" \
    "$image" python3 /in/step.py /in/input.h5ad /work/output.h5ad > "$box/log.txt" 2>&1
code=$?
seconds=$(( $(date +%s) - start ))

# Keep regular files only (never links), outside the caches.
(cd "$box/work" && find . -path ./.cache -prune -o -type f -print) | while IFS= read -r f; do
    mkdir -p "$out/$(dirname "$f")"
    mv "$box/work/$f" "$out/$f"
done
grep -v '^INFO: ' "$box/log.txt" > "$out/step_log.txt"
echo "$code" > "$out/exit_code.txt"
rm -rf "$box"

echo "SANDBOX EXIT: $code$([ $code -eq 124 ] && echo " (time limit of $minutes min reached)")  time: ${seconds}s"
echo "--- step log (last 60 lines) ---"
tail -n 60 "$out/step_log.txt"
echo "--- files written ---"
(cd "$out" && find . -type f ! -name step_log.txt ! -name exit_code.txt ! -name summary.txt -printf '%P\t%s bytes\n' | sort | head -n 50)
# What the step wrote, read in the sandbox too (the files are the agent's).
summary_box=$(mktemp -d "$PWD/summary.XXXXXX")
apptainer exec --containall --home "$summary_box:/work" --net --network none -B "$out:/out:ro" \
    -B "$(dirname "$(readlink -f "$0")")/lab_h5ad.py:/geth/lab_h5ad.py:ro" --env "NUMBA_CACHE_DIR=/work/.n,MPLCONFIGDIR=/work/.m" \
    "$image" python3 -I /geth/lab_h5ad.py summary /out 2>&1 | grep -v '^INFO: ' > "$summary_box/summary.txt"
mv "$summary_box/summary.txt" "$out/summary.txt"
rm -rf "$summary_box"
cat "$out/summary.txt"
[ "$strict" = yes ] && exit "$code"
exit 0
