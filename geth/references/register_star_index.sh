#!/usr/bin/env bash
# Register a STAR genome index in Geth's reference catalogue, so that later nf-core/rnaseq and nf-core/scrnaseq
# runs reuse it instead of rebuilding it (about 30 minutes and 30 GB for a human genome).
# Usage: register_star_index.sh <catalogue_entry> <star_index_dir> "<how it was built>"
# e.g.   register_star_index.sh homo_sapiens_GRCh38_ens116 runs/pbmc/results/star/genome_generate/star \
#            "nf-core/scrnaseq 4.2.0 (save_reference=true)"
# The index must have been built from the entry's genome FASTA and annotation GTF (as listed in its README.txt)
# by a run whose plan used exactly those files. It is hard-linked into <entry>/star_<STAR version>/ when on the
# same file system (no extra space), copied otherwise, and described in the entry's README.txt and in
# geth_index.json, which Geth's plan check reads.
set -euo pipefail
[ -n "${GETH_REFERENCES:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"
[ $# -eq 3 ] || { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

entry=$GETH_REFERENCES/$1; src=$(cd "$2" && pwd -P); built_by=$3
readme=$entry/README.txt
[ -f "$readme" ] || { echo "No catalogue entry $entry (README.txt missing)" >&2; exit 1; }
for f in genomeParameters.txt SA SAindex Genome Log.out; do
    [ -s "$src/$f" ] || { echo "$src is not a complete STAR index ($f missing)" >&2; exit 1; }
done
version=$(grep -m1 -o 'STAR version=[^ ]*' "$src/Log.out" | cut -d= -f2)
[ -n "$version" ] || { echo "Cannot read the STAR version from $src/Log.out" >&2; exit 1; }
fasta=$(sed -n 's/^Genome FASTA: *//p' "$readme" | head -n 1)
gtf=$(sed -n 's/^Annotation GTF: *//p' "$readme" | head -n 1)
[ -n "$fasta" ] && [ -n "$gtf" ] || { echo "$readme lists no 'Genome FASTA:' and 'Annotation GTF:'" >&2; exit 1; }
overhang=$(awk '$1 == "sjdbOverhang" {print $2}' "$src/genomeParameters.txt")

dest=$entry/star_$version
[ -e "$dest" ] && { echo "$dest already exists" >&2; exit 1; }
cp -al "$src" "$dest" 2>/dev/null || { rm -rf "${dest:?}"; cp -a "$src" "$dest"; }
python3 -I - "$dest/geth_index.json" "$version" "$fasta" "$gtf" "$built_by" "$overhang" <<'EOF'
import datetime, json, sys
path, version, fasta, gtf, built_by, overhang = sys.argv[1:]
json.dump({"tool": "STAR", "version": version, "fasta": fasta, "gtf": gtf, "built_by": built_by,
           "sjdbOverhang": int(overhang) if overhang.isdigit() else overhang,
           "registered": str(datetime.date.today())}, open(path, "w"), indent=2)
EOF
echo "STAR index: $dest (STAR $version, sjdbOverhang $overhang, built from the FASTA and GTF above by $built_by; for nf-core/rnaseq and nf-core/scrnaseq runs with STAR $version: set star_index, keep fasta and gtf)" >> "$readme"
echo "Registered $dest"
tail -n 1 "$readme"
