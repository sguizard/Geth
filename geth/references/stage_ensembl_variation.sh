#!/usr/bin/env bash
# Add Ensembl's known variants (VCF) and VEP cache to a genome entry of Geth's reference catalogue (made by
# stage_ensembl.sh), for germline variant calling with nf-core/sarek: known sites for base recalibration, and
# variant annotation with VEP. Downloads about 1-2 GB for a livestock genome: on a cluster, run it where
# downloads are allowed (e.g. as a job on a data-transfer queue). sarek builds the VCF's .tbi index itself.
# Usage: stage_ensembl_variation.sh <ensembl_species_dir> <assembly> <release>
# e.g.   stage_ensembl_variation.sh gallus_gallus bGalGal1.mat.broiler.GRCg7b 116
set -euo pipefail
[ -n "${GETH_REFERENCES:-}" ] || source "${GETH_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}/env.sh"
[ $# -eq 3 ] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

species=$1; assembly=$2; release=$3
base=https://ftp.ensembl.org/pub/release-$release/variation
entry=$GETH_REFERENCES/${species}_${assembly}_ens${release}
[ -f "$entry/README.txt" ] || { echo "No catalogue entry $entry: run stage_ensembl.sh first" >&2; exit 1; }
cd "$entry"

fetch() {  # fetch <url_dir> <file>: download once, check Ensembl's CHECKSUMS (BSD sum)
    if [ ! -s "$2" ]; then
        curl -fsSL --retry 3 -o "$2.part" "$1/$2"
        mv "$2.part" "$2"
    fi
    read -r exp_sum _ < <(curl -fsSL "$1/CHECKSUMS" | awk -v f="$2" '$3 == f')
    read -r got_sum _ < <(sum "$2")
    [ "$exp_sum" = "$got_sum" ] || { echo "Checksum mismatch for $2 ($got_sum, expected $exp_sum)" >&2; exit 1; }
    echo "OK $2"
}

vcf=$species.vcf.gz
fetch "$base/vcf/$species" "$vcf"

cache=${species}_vep_${release}_${assembly}.tar.gz
if [ ! -d "vep_cache/$species/${release}_${assembly}" ]; then
    fetch "$base/indexed_vep_cache" "$cache"
    mkdir -p vep_cache
    tar -xzf "$cache" -C vep_cache
    rm -f "$cache"
fi
[ -d "vep_cache/$species/${release}_${assembly}" ] || { echo "VEP cache not where expected" >&2; exit 1; }
echo "OK vep_cache/$species/${release}_${assembly}"

# Variant callers (nf-core/sarek) cannot index a gzip-compressed FASTA: keep an uncompressed copy.
fasta_gz=$(sed -n 's/^Genome FASTA: *//p' README.txt | head -n 1)
fasta=${fasta_gz%.gz}
if [ "$fasta" != "$fasta_gz" ] && [ ! -s "$fasta" ]; then
    gunzip -c "$fasta_gz" > "$fasta.part" && mv "$fasta.part" "$fasta"
fi
grep -q '^Genome FASTA (uncompressed' README.txt || echo "Genome FASTA (uncompressed, for nf-core/sarek and other variant callers): $fasta" >> README.txt
echo "OK $(basename "$fasta")"

grep -q '^Known variants VCF:' README.txt || cat >> README.txt <<EOF
Known variants VCF: $entry/$vcf (Ensembl $release variation: SNVs and indels; for nf-core/sarek use it as dbsnp and known_indels; sarek builds the .tbi)
VEP cache: $entry/vep_cache (VEP $release; for nf-core/sarek: vep_cache=$entry/vep_cache, vep_species=$species, vep_genome=$assembly, vep_cache_version=$release)
EOF
tail -n 2 README.txt
