/*
 * Geth lab (EXPERIMENTAL): the lab's scheduler jobs for Rannoch's lab agents (geth/harness/lab.py), one task per
 * launch, its output written to --out. The same processes as the tools of main.nf (copied: main.nf goes when the
 * Nextflow agents do).
 *
 *   --task inspect   --h5ad <file>                    LAB_INSPECT: a look at a count matrix
 *   --task subset    --data_file <file>               MAKE_SUBSET: the 3000-cell test subset (once per build)
 *   --task test_step --step <name> --input_from <x>   TEST_STEP: one step script on the subset, in the sandbox
 *   --task lint                                       LINT_PIPELINE: the agent-written main.nf (arm C)
 *   --task test_pipeline                              TEST_PIPELINE: the agent-written pipeline on the subset
 *   --task run_project --data_file <file>             RUN_PROJECT: the frozen arm C pipeline on the full data
 * Launched by bin/lab_job.sh. Parameters and the site's folders: nextflow.config next to this file.
 */
nextflow.enable.types = true

process LAB_INSPECT {
    container 'https://depot.galaxyproject.org/singularity/celltypist:1.7.1--pyhdfd78af_2'
    containerOptions "${params.lab_data.tokenize(':').collect { d -> '-B ' + d }.join(' ')}"
    cpus 2
    memory 16.GB
    time 1.h

    input:
    h5ad: String

    output:
    summary: String = stdout()

    script:
    """
    ok=0
    for root in ${params.lab_data.tokenize(':').join(' ')}; do
        case "${h5ad}" in "\$root"/*.h5ad) ok=1 ;; esac
    done
    if [ \$ok = 1 ]; then
        GETH_CACHE=\$PWD/.cache lab_inspect.py "${h5ad}" 2> inspect.err || tail -n 20 inspect.err
    else
        echo "REFUSED: only .h5ad files in the benchmark folders can be inspected"
    fi
    """
}

process MAKE_SUBSET {
    cpus 2
    memory 8.GB
    time 30.m

    input:
    data_file: String

    output:
    report: String = stdout()

    script:
    """
    if [ -s "${params.run_dir}/subset/output.h5ad" ]; then
        echo "subset ready"
    else
        lab_sandbox.sh --strict "${params.lab_image}" "\$(command -v lab_subset_step.py)" "${data_file}" /nonexistent 2 20 "${params.run_dir}/subset"
    fi
    """
}

process TEST_STEP {
    cpus 2
    memory 8.GB
    time 40.m

    input:
    name: String
    input_from: String

    output:
    report: String = stdout()

    script:
    def safe = name.replace("'", "'\\''")
    def source = input_from.replace("'", "'\\''")
    """
    lab_build.py test-step "${params.run_dir}" '${safe}' '${source}' "${params.lab_image}" "${params.lab_models}" 2
    """
}

process LINT_PIPELINE {  // a scheduler job: it starts the sandbox, which an agent sandbox cannot do
    cpus 1
    memory 2.GB
    time 15.m

    input:
    note: String

    output:
    report: String = stdout()

    script:
    """
    export LAB_JAVA_HOME="${params.lab_java_home}" LAB_NXF_LAUNCHER="${params.lab_nxf_launcher}" LAB_NXF_FRAMEWORK="${params.lab_nxf_framework}"
    lab_build.py lint-pipeline "${params.run_dir}" "${params.lab_image}"
    """
}

process TEST_PIPELINE {
    cpus 4
    memory 16.GB
    time 60.m

    input:
    note: String

    output:
    report: String = stdout()

    script:
    """
    export LAB_JAVA_HOME="${params.lab_java_home}" LAB_NXF_LAUNCHER="${params.lab_nxf_launcher}" LAB_NXF_FRAMEWORK="${params.lab_nxf_framework}"
    lab_build.py test-pipeline "${params.run_dir}" "${params.lab_image}" "${params.lab_models}" 4 14 40
    """
}

process RUN_PROJECT {
    cpus { params.full_cpus as int }
    memory { "${(params.full_memory as int) * task.attempt} GB" }
    time { "${((params.full_minutes as int) + 20) * task.attempt}m" }
    errorStrategy { task.exitStatus in [137, 140, 143] && task.attempt < 3 ? 'retry' : 'terminate' }
    maxRetries 2

    input:
    data_file: String

    output:
    report: String = stdout()

    script:
    """
    export LAB_JAVA_HOME="${params.lab_java_home}" LAB_NXF_LAUNCHER="${params.lab_nxf_launcher}" LAB_NXF_FRAMEWORK="${params.lab_nxf_framework}"
    lab_nf_sandbox.sh --strict "${params.lab_image}" "${params.run_dir}/pipeline_c" "${data_file}" "${params.lab_models}" \\
        ${params.full_cpus} ${(params.full_memory as int) * task.attempt - 2} ${(params.full_minutes as int) * task.attempt} "${params.run_dir}/full_c"
    """
}

workflow {
    if( !params.out || !params.run_dir || !params.run_dir.startsWith("${params.runs_dir}/lab/") )
        error "--out and --run_dir (under ${params.runs_dir}/lab/) are needed: source env.sh before running the lab"
    if( params.task == 'inspect' )            LAB_INSPECT(channel.of(params.h5ad)).subscribe { s -> file(params.out).text = s }
    else if( params.task == 'subset' )        MAKE_SUBSET(channel.of(params.data_file)).subscribe { s -> file(params.out).text = s }
    else if( params.task == 'test_step' )     TEST_STEP(channel.of(params.step), params.input_from as String).subscribe { s -> file(params.out).text = s }
    else if( params.task == 'lint' )          LINT_PIPELINE(channel.of('lint')).subscribe { s -> file(params.out).text = s }
    else if( params.task == 'test_pipeline' ) TEST_PIPELINE(channel.of('test')).subscribe { s -> file(params.out).text = s }
    else if( params.task == 'run_project' )   RUN_PROJECT(channel.of(params.data_file)).subscribe { s -> file(params.out).text = s }
    else error "--task must be inspect, subset, test_step, lint, test_pipeline or run_project"
}
