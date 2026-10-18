#!/usr/bin/env bash
# Freeze the current commit for a benchmark, so development can go on while it runs: exports HEAD to
# $GETH_WORK_ROOT/snapshots/<commit> (once) and prints the path. Run the benchmark from the snapshot with your
# site file, in a clean environment:
#   s=$(bench/snapshot.sh)
#   env -u GETH_HOME -u GETH_RUNS_DIR GETH_SITE_ENV=$PWD/site/site.env $s/bench/bench_run.sh <tag> <run>:<dataset> ...
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
[ -n "${GETH_WORK_ROOT:-}" ] || source "$here/env.sh"
[ -z "$(git -C "$here" status --porcelain --untracked-files=no)" ] \
    || { echo "Commit your changes first: a snapshot holds the last commit only" >&2; exit 1; }
commit=$(git -C "$here" rev-parse --short=10 HEAD)
dest=$GETH_WORK_ROOT/snapshots/$commit
if [ ! -d "$dest" ]; then
    mkdir -p "$dest.part"
    git -C "$here" archive HEAD | tar -x -C "$dest.part"
    mv "$dest.part" "$dest"
fi
echo "$dest"
