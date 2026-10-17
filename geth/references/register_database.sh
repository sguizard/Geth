#!/usr/bin/env bash
# Register a profiling database that already exists somewhere (e.g. a shared, read-only folder) in Geth's reference
# catalogue, without copying it, and write ready-made nf-core/taxprofiler databases sheets for it.
# Usage: register_database.sh <entry_name> <kraken2|metaphlan> <database_folder> "<description>"
# e.g.   register_database.sh kraken2_standard_20250402 kraken2 /shared/k2_standard_20250402 \
#            "Kraken2 standard 2025-04-02: RefSeq archaea, bacteria, viral, plasmid, human, UniVec_Core"
# Kraken2 databases with Bracken files get a Kraken2+Bracken sheet (Bracken read length 150, or the
# closest available); MetaPhlAn databases get a MetaPhlAn sheet.
set -euo pipefail
[ -n "${GETH_REFERENCES:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"
[ $# -eq 4 ] || { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

entry=$GETH_REFERENCES/$1; tool=$2; db=$(cd "$3" && pwd -P); description=$4
mkdir -p "$entry"
python3 -I - "$entry" "$tool" "$db" "$description" <<'EOF'
import datetime, glob, os, re, sys

entry, tool, db, description = sys.argv[1:]
size_gb = sum(os.path.getsize(p) for p in glob.glob(os.path.join(db, "*")) if os.path.isfile(p)) / 1e9
lines = [f"Kind: {tool} database for nf-core/taxprofiler (taxonomic profiling of metagenomic reads)",
         f"Database: {description}",
         f"Database folder: {db} (outside the catalogue, read-only)"]
if tool == "kraken2":
    if not os.path.isfile(os.path.join(db, "hash.k2d")):
        sys.exit(f"{db} is not a Kraken2 database (no hash.k2d)")
    hash_gb = os.path.getsize(os.path.join(db, "hash.k2d")) / 1e9
    lengths = sorted(int(m.group(1)) for p in glob.glob(os.path.join(db, "database*mers.kmer_distrib"))
                     if (m := re.search(r"database(\d+)mers", p)))
    sheet = ["tool,db_name,db_params,db_type,db_path", f"kraken2,{os.path.basename(entry)},,short;long,{db}"]
    if lengths:
        length = min(lengths, key=lambda n: abs(n - 150))
        sheet.append(f"bracken,{os.path.basename(entry)},;-r {length},short,{db}")
        lines.append(f"Bracken: read lengths {', '.join(map(str, lengths))} available; the sheet uses {length}")
    name = "databases_kraken2_bracken.csv" if lengths else "databases_kraken2.csv"
    lines.append(f"Memory: Kraken2 loads the {hash_gb:.0f} GB index in RAM: Geth asks for enough memory for its jobs")
elif tool == "metaphlan":
    if not glob.glob(os.path.join(db, "*.pkl")):
        sys.exit(f"{db} is not a MetaPhlAn database (no .pkl)")
    sheet = ["tool,db_name,db_params,db_type,db_path", f"metaphlan,{os.path.basename(entry)},,short;long,{db}"]
    name = "databases_metaphlan.csv"
else:
    sys.exit(f"unknown tool '{tool}' (kraken2 or metaphlan)")
open(os.path.join(entry, name), "w").write("\n".join(sheet) + "\n")
lines += [f"taxprofiler databases sheet: {os.path.join(entry, name)} (set databases=<this file>)",
          f"Size: {size_gb:.0f} GB", f"Registered: {datetime.date.today()}"]
open(os.path.join(entry, "README.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
EOF
