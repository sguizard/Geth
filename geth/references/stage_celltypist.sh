#!/usr/bin/env bash
# Add CellTypist cell-type annotation models to Geth's reference catalogue ($GETH_REFERENCES), for the
# single-cell downstream analysis. Available models: https://www.celltypist.org/models
# Usage: stage_celltypist.sh <entry_name> "<species, common name>" "<cells the models describe>" <model>...
# e.g.   stage_celltypist.sh celltypist_immune_v2 "Homo sapiens (human)" "human immune cells" Immune_All_Low Immune_All_High
set -euo pipefail
[ -n "${GETH_REFERENCES:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"
[ $# -ge 4 ] || { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

entry=$1; species=$2; cells=$3; shift 3
python3 -I - "$GETH_REFERENCES/$entry" "$species" "$cells" "$@" <<'EOF'
import datetime, json, os, sys, urllib.request

dest, species, cells, names = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
with urllib.request.urlopen("https://celltypist.cog.sanger.ac.uk/models/models.json", timeout=60) as r:
    catalogue = {m["filename"]: m for m in json.load(r)["models"]}
models = []
for name in names:
    filename = name if name.endswith(".pkl") else name + ".pkl"
    if filename not in catalogue:
        sys.exit(f"Unknown CellTypist model '{name}': see https://www.celltypist.org/models")
    models.append(catalogue[filename])
os.makedirs(dest, exist_ok=True)
dest = os.path.realpath(dest)  # the real path: the catalogue README records it for the agents

for m in models:
    path = os.path.join(dest, m["filename"])
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        with urllib.request.urlopen(m["url"], timeout=300) as r, open(path + ".part", "wb") as out:
            out.write(r.read())
        with open(path + ".part", "rb") as f:
            if f.read(1) != b"\x80":  # pickle protocol marker: not an error page
                sys.exit(f"Download of {m['url']} is not a model file")
        os.replace(path + ".part", path)
    print("OK", m["filename"])

pad = " " * len("Model files: ")
with open(os.path.join(dest, "README.txt"), "w") as f:
    f.write(f"Kind: CellTypist cell-type annotation models (single-cell RNA-seq), {cells}\n")
    f.write(f"Species: {species}\n")
    f.write("Models: " + ", ".join(f"{m['filename']} ({m['No_celltypes']} cell types: {m['details']})"
                                   for m in models) + "\n")
    f.write("Model files: " + f"\n{pad}".join(os.path.join(dest, m["filename"]) for m in models) + "\n")
    f.write("Source: https://www.celltypist.org/models ("
            + "; ".join(f"{m['filename']} {m['version']}, {m['date'][:10]}, {m['source']}" for m in models) + ")\n")
    f.write("Use: input must be log1p-normalised to 10,000 counts per cell with gene symbols (Geth's toolbox does this)\n")
    f.write(f"Staged: {datetime.date.today()}\n")
print(open(os.path.join(dest, "README.txt")).read(), end="")
EOF
