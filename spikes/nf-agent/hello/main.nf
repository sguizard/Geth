nextflow.enable.types = true

agent qa {
    model "openai/${params.model}"
    instruction 'You are a concise bioinformatics assistant.'

    input:
    question: String

    output:
    stdout()

    prompt:
    """
    Answer in at most two sentences: ${question}
    """
}

workflow {
    def allowed = ['Qwen/Qwen3.5-397B-A17B-FP8', 'mistralai/Mistral-Small-4-119B-2603']
    if( !(params.model in allowed) )
        error "Model '${params.model}' is not in the free ELM allowlist: ${allowed}"

    qa(channel.of('What does FastQC check?', 'Why trim adapters before alignment?')).view()
}
