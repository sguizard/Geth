/*
 * Geth's scheduler jobs for Rannoch's agents (geth/harness): one task per launch, submitted through the site's
 * Nextflow configuration like every other Geth job, its output written to --out. (The Nextflow agents of
 * main.nf run the same processes as their tools.)
 *
 *   --task inspect --h5ad <file>                     the single-cell toolbox's look at a count matrix
 *   --task analyse --run_dir <dir> --design <file>   one analysis of an approved single-cell design
 *
 * Launched by bin/sc_job.sh, which says what failed when the job itself could not run.
 */
nextflow.enable.types = true

// Parameters: --task, --h5ad, --design, --run_dir, --out; the site's folders come from nextflow.config next to
// this file, which Nextflow loads with it.

// The single-cell toolbox (bin/sc_downstream.py) in the pinned CellTypist container: as main.nf.
process SC_INSPECT {
    container 'https://depot.galaxyproject.org/singularity/celltypist:1.7.1--pyhdfd78af_2'
    containerOptions "-B ${params.data_root} -B ${params.references} -B ${params.runs_dir}"
    cpus 1
    memory 16.GB
    time 1.h

    input:
    h5ad: String

    output:
    summary: String = stdout()

    script:
    """
    case "${h5ad}" in
        ${params.data_root}/*.h5ad) GETH_CACHE=\$PWD/.cache sc_downstream.py inspect "${h5ad}" 2> inspect.err || tail -n 20 inspect.err ;;
        *) echo "REFUSED: only .h5ad files under ${params.data_root} can be inspected" ;;
    esac
    """
}

process SC_ANALYSE {
    container 'https://depot.galaxyproject.org/singularity/celltypist:1.7.1--pyhdfd78af_2'
    containerOptions "-B ${params.data_root} -B ${params.references} -B ${params.runs_dir}"
    cpus 4
    memory 32.GB
    time 4.h

    input:
    design: String

    output:
    digest: String = stdout()

    script:
    """
cat > design.txt <<'GETH_EOF'
${design.trim()}
GETH_EOF
export GETH_REFERENCES="${params.references}"
sc_analyse.sh "${params.run_dir}" design.txt
    """
}

workflow {
    if( !params.out || !params.runs_dir )
        error "Geth's site settings are missing, or --out: source env.sh before running Geth's jobs"
    if( params.task == 'inspect' ) {
        SC_INSPECT(channel.of(params.h5ad as String)).subscribe { s -> file(params.out).text = s }
    }
    else if( params.task == 'analyse' ) {
        if( !params.run_dir || !params.run_dir.startsWith("${params.runs_dir}/") )
            error "run_dir must be under ${params.runs_dir}/"
        SC_ANALYSE(channel.of(file(params.design).text)).subscribe { s -> file(params.out).text = s }
    }
    else {
        error "--task must be 'inspect' or 'analyse'"
    }
}
