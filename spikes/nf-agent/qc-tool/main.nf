nextflow.enable.types = true

record QcVerdict {
    sample: String
    total_reads: Integer
    adapters_need_trimming: Boolean
    failed_modules: List<String>
    reason: String
}

// Tool for the agent: runs as a normal SGE task (roslin profile), not in the driver.
// nf-agent 0.2.0 cannot pass Path inputs to tools yet, so the FASTQ is an absolute
// path on the shared filesystem, bound into the container explicitly.
process FASTQC {
    container 'https://depot.galaxyproject.org/singularity/fastqc:0.12.1--hdfd78af_0'
    containerOptions "-B ${params.data_root}"
    cpus 2
    memory 4.GB

    input:
    reads: String

    output:
    report: String = stdout()

    script:
    """
    ln -s ${reads} .
    fastqc --quiet --extract -t ${task.cpus} \$(basename ${reads}) >&2
    cat *_fastqc/summary.txt
    grep -A10 '>>Basic Statistics' *_fastqc/fastqc_data.txt
    """
}

agent qc_triage {
    model "openai/${params.model}"
    instruction '''You are a sequencing QC assistant. Always call the FASTQC tool on the file you are given
        before answering, and base your verdict only on the tool output.'''
    tools 'nf:module_run:FASTQC'

    input:
    fastq: String

    output:
    verdict: QcVerdict

    prompt:
    """
    Run FASTQC on the FASTQ file ${fastq} (pass this exact absolute path to the tool)
    and decide whether adapter trimming is needed.
    In your final answer, state explicitly: the sample name (file name without .fastq.gz),
    the "Total Sequences" value copied exactly from the tool output, and every module with status FAIL.
    """
}

workflow {
    def allowed = ['Qwen/Qwen3.5-397B-A17B-FP8', 'mistralai/Mistral-Small-4-119B-2603']
    if( !(params.model in allowed) )
        error "Model '${params.model}' is not in the free ELM allowlist: ${allowed}"

    qc_triage(channel.fromPath(params.reads).map { fq -> fq.toString() }).view()
}
