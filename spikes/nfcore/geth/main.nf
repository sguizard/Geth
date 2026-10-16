/*
 * Geth spike 3: agents plan, run, fix and report an nf-core analysis.
 *   planner  — inspects the data folder, picks rnaseq/scrnaseq, writes samplesheet + params
 *   operator — launches the pinned pipeline, reads failures, fixes and retries (≤ 3 attempts)
 *   reporter — writes a Markdown report from the real results
 * All tools are local processes on the submit host; the nf-core runs submit their own SGE jobs.
 */
nextflow.enable.types = true

record AnalysisPlan {
    pipeline: String
    samplesheet_csv: String
    params_json: String
    rationale: String
}

record RunOutcome {
    succeeded: Boolean
    attempts: Integer
    outdir: String
    fixes_applied: List<String>
    last_error: String
}

// ---------------------------------------------------------------- tools

process LIST_FILES {
    executor 'local'
    scratch false

    input:
    dir: String

    output:
    listing: String = stdout()

    script:
    """
    case "${dir}" in
        ${params.data_root}/*) find "${dir}" -maxdepth 3 \\( -type f -o -type l \\) -printf '%p\\t%s bytes\\n' | sort | head -n 300 ;;
        *) echo "REFUSED: only folders under ${params.data_root} can be listed" ;;
    esac
    """
}

process READ_TEXT {
    executor 'local'
    scratch false

    input:
    path: String

    output:
    text: String = stdout()

    script:
    """
    case "${path}" in
        ${params.data_root}/*.gz) echo "(first 8 lines, decompressed)"; zcat "${path}" | head -n 8 ;;
        ${params.data_root}/*) head -c 8000 "${path}" ;;
        *) echo "REFUSED: only files under ${params.data_root} can be read" ;;
    esac
    """
}

process RUN_NFCORE {
    executor 'local'
    scratch false
    time 6.h

    input:
    pipeline: String
    samplesheet_csv: String
    params_json: String

    output:
    digest: String = stdout()

    script:
    """
cat > samplesheet.csv <<'GETH_EOF'
${samplesheet_csv.trim()}
GETH_EOF
cat > params.json <<'GETH_EOF'
${params_json.trim()}
GETH_EOF
run_nfcore.sh "${params.run_dir}" "${pipeline}" samplesheet.csv params.json
    """
}

process COLLECT_RESULTS {
    executor 'local'
    scratch false

    input:
    pipeline: String

    output:
    summary: String = stdout()

    script:
    """
    collect_results.py "${params.run_dir}/results" "${pipeline}"
    """
}

// ---------------------------------------------------------------- agents

agent planner {
    model "openai/${params.model}"
    instruction '''You are Geth, a bioinformatics analysis planner. You turn a scientist's request and a
        sequencing data folder into a run plan for exactly one nf-core pipeline: "rnaseq" (bulk RNA-seq,
        nf-core/rnaseq) or "scrnaseq" (single-cell RNA-seq, nf-core/scrnaseq).
        Always inspect the folder first: list it, then read every README/metadata text file in it.
        Load the skill of the pipeline you choose and follow its rules exactly.
        Use absolute paths. Only use files that appear in the listing; never invent files.'''
    tools 'nf:module_run:LIST_FILES', 'nf:module_run:READ_TEXT'
    skills 'nfcore-rnaseq', 'nfcore-scrnaseq'
    maxIterations 20

    input:
    question: String
    data_dir: String

    output:
    plan: AnalysisPlan

    prompt:
    """
    Request: ${question}
    Data folder: ${data_dir}

    In your final answer give: the pipeline ("rnaseq" or "scrnaseq"); the complete samplesheet CSV text
    with its header line; the pipeline parameters as one JSON object (do not include "input" or "outdir");
    and a short rationale that explains how files were grouped into samples.
    """
}

agent operator {
    model "openai/${params.model}"
    instruction '''You are Geth's pipeline operator. You execute an analysis plan with the RUN_NFCORE tool.
        If the tool reports STATUS: FAILED, read the error, change only what the error points to (samplesheet
        rows/columns or parameters), and call RUN_NFCORE again: the run resumes where it stopped.
        Make at most 3 RUN_NFCORE calls in total. Never switch pipeline. Never claim success unless the
        tool printed STATUS: SUCCESS.'''
    tools 'nf:module_run:RUN_NFCORE'
    maxIterations 10

    input:
    plan: AnalysisPlan

    output:
    outcome: RunOutcome

    prompt:
    """
    Execute this plan now: call RUN_NFCORE with its pipeline, samplesheet_csv and params_json.
    In your final answer state: whether the run succeeded, how many RUN_NFCORE calls you made,
    the OUTDIR printed by the tool (or "none"), every fix you applied (or none), and the last error (or "none").
    """
}

agent reporter {
    model "openai/${params.model}"
    instruction '''You are Geth's reporting assistant. You write concise, factual analysis reports in Markdown
        for biologists. Use only numbers that appear in the tool output or in the inputs; never estimate,
        round differently or invent values. Say clearly when something is missing.'''
    tools 'nf:module_run:COLLECT_RESULTS'
    maxIterations 5

    input:
    question: String
    tuple(plan: AnalysisPlan, outcome: RunOutcome)

    output:
    stdout()

    prompt:
    """
    Original request: ${question}
    Call COLLECT_RESULTS once with the plan's pipeline, then write the report with these sections:
    Summary; Samples (how input files were grouped); Quality control (table of per-sample key metrics);
    Results; Caveats and next steps. If the run failed, explain why and what to fix instead.
    Return only the Markdown report.
    """
}

// ---------------------------------------------------------------- bookkeeping

process SAVE_PLAN {
    executor 'local'

    input:
    plan: AnalysisPlan

    exec:
    def d = file(params.run_dir)
    d.mkdirs()
    d.resolve('plan_samplesheet.csv').text = plan.samplesheet_csv.trim() + '\n'
    d.resolve('plan_params.json').text = plan.params_json.trim() + '\n'
    d.resolve('plan_rationale.txt').text = "pipeline: ${plan.pipeline}\n\n${plan.rationale}\n"
}

process SAVE_OUTCOME {
    executor 'local'

    input:
    outcome: RunOutcome

    exec:
    file(params.run_dir).resolve('outcome.txt').text = """\
        succeeded: ${outcome.succeeded}
        attempts: ${outcome.attempts}
        outdir: ${outcome.outdir}
        fixes_applied: ${outcome.fixes_applied}
        last_error: ${outcome.last_error}
        """.stripIndent()
}

process SAVE_REPORT {
    executor 'local'

    input:
    report: String

    exec:
    file(params.run_dir).resolve('report.md').text = report
}

workflow {
    def allowed = ['Qwen/Qwen3.5-397B-A17B-FP8', 'mistralai/Mistral-Small-4-119B-2603']
    if( !(params.model in allowed) )
        error "Model '${params.model}' is not in the free ELM allowlist: ${allowed}"
    if( !params.run_dir.startsWith("${params.data_root}/spikes/nfcore/runs/") )
        error "run_dir must be under ${params.data_root}/spikes/nfcore/runs/"

    def plan = planner(params.question, params.data_dir)
    SAVE_PLAN(plan)
    if( !params.plan_only ) {
        def outcome = operator(plan)
        SAVE_OUTCOME(outcome)
        SAVE_REPORT(reporter(params.question, plan.combine(outcome)))
    }
}
