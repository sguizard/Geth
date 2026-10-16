#!/usr/bin/env bash
# Add an Ensembl genome + annotation to Geth's reference catalogue ($PERSEUS_VEIL/references).
# Usage: stage_ensembl.sh <ensembl_species_dir> <assembly> <release> "<species, common name>"
# e.g.   stage_ensembl.sh homo_sapiens GRCh38 116 "Homo sapiens (human)"
# Uses the primary assembly when Ensembl provides one (no haplotypes/patches), else toplevel.
# Files are checked against Ensembl's CHECKSUMS (BSD `sum`).
set -euo pipefail
source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

species=$1; assembly=$2; release=$3; label=$4
Species=${species^}
base=https://ftp.ensembl.org/pub/release-$release
dest=$PERSEUS_VEIL/references/${species}_${assembly}_ens${release}
fasta=$Species.$assembly.dna.primary_assembly.fa.gz
curl -fsI "$base/fasta/$species/dna/$fasta" > /dev/null || fasta=$Species.$assembly.dna.toplevel.fa.gz
gtf=$Species.$assembly.$release.gtf.gz
mkdir -p "$dest"
cd "$dest"

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
