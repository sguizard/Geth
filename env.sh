# Geth environment — source this at the start of every shell / job script:
#   source /exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth/env.sh

export GETH_HOME=/exports/cmvm/eddie/eb/groups/alaw3_grp/sguizard/Dev/github/Geth
export PERSEUS_VEIL=/exports/eddie/scratch/sguizard/Perseus_Veil

# Drop PATH entries from other groups' storage (forbidden area) and de-duplicate.
PATH=$(printf '%s' "$PATH" | tr ':' '\n' \
    | grep -v '^/exports/cmvm/eddie/eb/groups/jhope2_lmoffat3_isp_scrnaseq' \
    | awk 'NF && !seen[$0]++' | paste -sd: -)
export PATH="$PERSEUS_VEIL/nxf/bin:$PATH"

# nf-core roslin profile: SGE project code + shared apptainer cacheDir are driven by this variable.
export NXF_SGE_PROJECT=roslin_alaw3_grp
export NXF_HOME="$PERSEUS_VEIL/nxf/home"
export NXF_VER=26.10.2  # agent primitive needs >= 26.10

# Conda envs/packages go to scratch; the user's miniforge3 is read/execute only.
export CONDA_PKGS_DIRS="$PERSEUS_VEIL/conda_pkgs"
export CONDA_ENVS_DIRS="$PERSEUS_VEIL/envs"

# LLM access: free ELM models only. Never point anything at a paid provider.
export GETH_ELM_BASE_URL="https://elm.edina.ac.uk/api/v1"
export GETH_ALLOWED_MODELS="Qwen/Qwen3.5-397B-A17B-FP8 mistralai/Mistral-Small-4-119B-2603"
unset OPENAI_API_KEY OPENAI_BASE_URL ANTHROPIC_API_KEY

# Keep local work within the 4-thread limit on the shared login node.
if [ -z "${JOB_ID:-}" ]; then
    export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
    export NXF_OPTS="${NXF_OPTS:--Xms512m -Xmx4g -XX:ActiveProcessorCount=2}"
fi

if ! type module >/dev/null 2>&1; then
    source /etc/profile.d/modules.sh
fi
module load java/jdk-21.0.1 apptainer/1.4.4 >/dev/null 2>&1
