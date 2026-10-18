#!/usr/bin/env bash
# Score an arm B build with bench/lab/eval_build.py, inside the lab image (read-only binds, no network).
#   bench/lab/score_build.sh <build run dir> <kang2018|pbmc1k>
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
[ -n "${GETH_RUNS_DIR:-}" ] || source "$here/env.sh" >/dev/null
run=$(readlink -f "$1") dataset=$2
input=$(ls "$(cat "$run/data_dir.txt")"/*.h5ad)
truth=$GETH_WORK_ROOT/lab_truth/kang2018
tmp=$(mktemp -d)
apptainer exec --containall --home "$tmp:/work" --net --network none -B "$run:$run:ro" -B "$truth:$truth:ro" \
    -B "$(dirname "$input"):$(dirname "$input"):ro" -B "$here/bench/lab/eval_build.py:/geth/eval_build.py:ro" \
    --env NUMBA_CACHE_DIR=/work/.n,MPLCONFIGDIR=/work/.m \
    "$GETH_LAB_IMAGE" \
    python3 -I /geth/eval_build.py "$run" "$dataset" "$truth" "$input" 2>&1 | grep -v '^INFO: \|WARNING'
rm -rf "$tmp"
