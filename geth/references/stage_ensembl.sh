#!/usr/bin/env bash
# Add an Ensembl genome + annotation to Geth's reference catalogue ($GETH_REFERENCES).
# Downloads about 1 GB for a mammalian genome: on a cluster, run it where downloads are allowed
# (e.g. as a job on a data-transfer queue).
# Usage: stage_ensembl.sh <ensembl_species_dir> <assembly> <release> "<species, common name>"
# e.g.   stage_ensembl.sh homo_sapiens GRCh38 116 "Homo sapiens (human)"
# Uses the primary assembly when Ensembl provides one (no haplotypes/patches), else toplevel.
# Files are checked against Ensembl's CHECKSUMS (BSD `sum`).
set -euo pipefail
[ -n "${GETH_REFERENCES:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"

species=$1; assembly=$2; release=$3; label=$4
Species=${species^}
base=https://ftp.ensembl.org/pub/release-$release
dest=$GETH_REFERENCES/${species}_${assembly}_ens${release}
fasta=$Species.$assembly.dna.primary_assembly.fa.gz
curl -fsI "$base/fasta/$species/dna/$fasta" > /dev/null || fasta=$Species.$assembly.dna.toplevel.fa.gz
# The annotation of the release; species imported from Ensembl Genomes (e.g. yeast) carry that site's release
# number in the file name instead (Saccharomyces_cerevisiae.R64-1-1.63.gtf.gz in Ensembl 116).
gtf=$(curl -fsSL "$base/gtf/$species/" | grep -oE "$Species\.$assembly\.[0-9]+\.gtf\.gz" | sort -u | head -n 1)
[ -n "$gtf" ] || { echo "No annotation (GTF) for $species $assembly in $base/gtf/$species/" >&2; exit 1; }
mkdir -p "$dest"
cd "$dest"
dest=$(pwd -P)  # the real path: the catalogue README records it for the agents

fetch() {  # fetch <url_dir> <file>
    [ -s "$2" ] || curl -fsSL -o "$2.part" "$1/$2" && { [ -s "$2" ] || mv "$2.part" "$2"; }
    curl -fsSL "$1/CHECKSUMS" | awk -v f="$2" '$3 == f' > "$2.sum.expected"
    read -r exp_sum exp_blocks _ < "$2.sum.expected"
    read -r got_sum got_blocks < <(sum "$2")
    [ "$exp_sum" = "$got_sum" ] || { echo "Checksum mismatch for $2 ($got_sum, expected $exp_sum)" >&2; exit 1; }
    rm -f "$2.sum.expected"
    echo "OK $2"
}
fetch "$base/fasta/$species/dna" "$fasta"
fetch "$base/gtf/$species" "$gtf"

cat > README.txt <<EOF
Species: $label
Assembly: $assembly (Ensembl release $release, ${fasta#$Species.$assembly.dna.})
Genome FASTA: $dest/$fasta
Annotation GTF: $dest/$gtf
Source: $base
Staged: $(date +%F)
EOF
cat README.txt
