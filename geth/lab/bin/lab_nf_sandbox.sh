#!/usr/bin/env bash
# Geth lab (EXPERIMENTAL), arm C: run an agent-written Nextflow project in the sandbox, driver included.
#   lab_nf_sandbox.sh [--strict] <image> <project dir> <input.h5ad> <models dir> <cpus> <memory GB> <minutes> <out dir>
#   lab_nf_sandbox.sh --lint <image> <project dir>
# A Nextflow script is code that runs in its driver, so the whole run (driver and tasks) stays in the sandbox:
# the project (main.nf, bin/*.py) is copied to /in/project, the input to /in/input.h5ad, the models to /in/models,
# all read-only; Java and Nextflow come from the host, read-only (LAB_JAVA_HOME, LAB_NXF_LAUNCHER,
# LAB_NXF_FRAMEWORK). It runs offline from /work (writable, also the home) with Geth's config last: local
# executor within <cpus> and <memory>, no containers, no conda. No network, no host files, a clean environment.
# results/ comes back to <out dir> (regular files only), with the Nextflow log and a summary.
# Prints "SANDBOX EXIT: <code>" and exits 0 (a tool must), or with the run's code under --strict.
set -uo pipefail
mode=run
case "${1:-}" in --strict) mode=strict; shift ;; --lint) mode=lint; shift ;; esac
: "${LAB_JAVA_HOME:?}" "${LAB_NXF_LAUNCHER:?}" "${LAB_NXF_FRAMEWORK:?}"
command -v apptainer >/dev/null || { echo "SANDBOX EXIT: 127  apptainer is not available on $(hostname)"; [ $mode = strict ] && exit 127; exit 0; }
image=$1 project=$2
version=$(basename "$LAB_NXF_FRAMEWORK")
here=$(dirname "$(readlink -f "$0")")

box=$(mktemp -d "$PWD/sandbox.XXXXXX")
mkdir -p "$box/in/project/bin" "$box/in/models" "$box/work/.nxf/framework"
cp "$project/main.nf" "$box/in/project/main.nf"
for f in "$project"/bin/*.py; do [ -f "$f" ] && [ ! -L "$f" ] && cp "$f" "$box/in/project/bin/" && chmod +x "$box/in/project/bin/$(basename "$f")"; done
ln -s "/opt/nxf/framework/$version" "$box/work/.nxf/framework/$version"
env_list="JAVA_HOME=/opt/java,PATH=/opt/java/bin:/opt/conda/bin:/usr/local/bin:/usr/bin:/bin,NXF_HOME=/work/.nxf"
env_list+=",NXF_VER=$version,NXF_OFFLINE=true,NXF_DISABLE_CHECK_LATEST=true,NXF_ANSI_LOG=false"
env_list+=",XDG_CACHE_HOME=/work/.cache,NUMBA_CACHE_DIR=/work/.cache/numba,MPLCONFIGDIR=/work/.cache/mpl"
env_list+=",CELLTYPIST_FOLDER=/work/.cache/celltypist,PYTHONDONTWRITEBYTECODE=1,MPLBACKEND=Agg"
binds=(-B "$box/in:/in:ro" -B "$LAB_JAVA_HOME:/opt/java:ro" -B "$LAB_NXF_LAUNCHER:/opt/nxf/bin/nextflow:ro"
       -B "$LAB_NXF_FRAMEWORK:/opt/nxf/framework/$version:ro")

if [ $mode = lint ]; then
    apptainer exec --containall --home "$box/work:/work" --net --network none "${binds[@]}" --pwd /work --env "$env_list" \
        "$image" /opt/nxf/bin/nextflow lint /in/project/main.nf 2>&1 | grep -v '^INFO: ' | tail -n 60
    rm -rf "$box"
    exit 0
fi

input=$3 models=$4 cpus=$5 mem=$6 minutes=$7 out=$8
cp "$input" "$box/in/input.h5ad"
if [ -d "$models" ]; then cp "$models"/*.pkl "$box/in/models/" 2>/dev/null; fi
cat > "$box/in/geth.config" <<CONFIG
// Geth's settings for an agent-written pipeline, applied last.
process.executor = 'local'
executor.cpus = $cpus
executor.memory = '$mem GB'
apptainer.enabled = false
singularity.enabled = false
docker.enabled = false
podman.enabled = false
conda.enabled = false
CONFIG
start=$(date +%s)
timeout "${minutes}m" apptainer exec --containall --home "$box/work:/work" --net --network none "${binds[@]}" \
    --pwd /work --env "$env_list,OMP_NUM_THREADS=$cpus,OPENBLAS_NUM_THREADS=$cpus" "$image" \
    /opt/nxf/bin/nextflow run /in/project/main.nf -c /in/geth.config -w /work/work \
    --input /in/input.h5ad --outdir /work/results --models /in/models > "$box/console.log" 2>&1
code=$?
seconds=$(( $(date +%s) - start ))

mkdir -p "$out/results"
if [ -d "$box/work/results" ]; then
    (cd "$box/work/results" && find . -type f -print) | while IFS= read -r f; do
        mkdir -p "$out/results/$(dirname "$f")"
        cp "$box/work/results/$f" "$out/results/$f"
    done
fi
grep -v '^INFO: ' "$box/console.log" > "$out/nextflow_console.txt"
[ -f "$box/work/.nextflow.log" ] && [ ! -L "$box/work/.nextflow.log" ] && cp "$box/work/.nextflow.log" "$out/nextflow.log"
# the end of each failed task's error output, for the agent
for d in "$box"/work/work/*/*/; do
    [ -f "$d/.exitcode" ] && [ "$(cat "$d/.exitcode")" != 0 ] && [ -f "$d/.command.err" ] && \
        { echo "== $(head -n 1 "$d/.command.sh" 2>/dev/null | cut -c1-80) ($(basename "$(dirname "$d")")/$(basename "$d"))"; tail -n 25 "$d/.command.err"; }
done > "$out/failed_tasks.txt" 2>/dev/null
echo "$code" > "$out/exit_code.txt"
rm -rf "$box"

echo "SANDBOX EXIT: $code$([ $code -eq 124 ] && echo " (time limit of $minutes min reached)")  time: ${seconds}s"
echo "--- Nextflow output (last 40 lines) ---"
tail -n 40 "$out/nextflow_console.txt"
if [ -s "$out/failed_tasks.txt" ]; then echo "--- failed tasks: error output ---"; head -c 6000 "$out/failed_tasks.txt"; fi
echo "--- published to params.outdir ---"
(cd "$out/results" && find . -type f -printf '%P\t%s bytes\n' | sort | head -n 40)
summary_box=$(mktemp -d "$PWD/summary.XXXXXX")
apptainer exec --containall --home "$summary_box:/work" --net --network none -B "$out/results:/out:ro" \
    -B "$here/lab_h5ad.py:/geth/lab_h5ad.py:ro" --env "NUMBA_CACHE_DIR=/work/.n,MPLCONFIGDIR=/work/.m" \
    "$image" python3 -I /geth/lab_h5ad.py summary /out final.h5ad 2>&1 | grep -v '^INFO: ' > "$summary_box/summary.txt"
mv "$summary_box/summary.txt" "$out/summary.txt"
rm -rf "$summary_box"
cat "$out/summary.txt"
[ $mode = strict ] && exit "$code"
exit 0
