/*
 * Geth v1: Qwen agents plan, run, fix and report an nf-core analysis on Eddie.
 *
 *   --mode plan : planner inspects the data folder and writes plan_* files into run_dir
 *   (a person reviews and approves the plan: `geth approve`)
 *   --mode run  : operator launches the approved plan (gated retries), reporter writes report.md,
 *                 every number in the report is checked against the results
 *
 * Tools run as local processes on the submit host; the nf-core runs submit their own SGE jobs.
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

process CHECK_PLAN {
    executor 'local'
    scratch false

    input:
    pipeline: String
    samplesheet_csv: String
    params_json: String

    output:
    report: String = stdout()

    script:
    """
cat > samplesheet.csv <<'GETH_EOF'
${samplesheet_csv.trim()}
GETH_EOF
cat > params.json <<'GETH_EOF'
${params_json.trim()}
GETH_EOF
geth_checks.py check-plan "${pipeline}" samplesheet.csv params.json || true
    """
}

process RUN_NFCORE {
    executor 'local'
    scratch false
    time 12.h

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
    collect_results.py "${params.run_dir}" "${pipeline}"
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
        Use absolute paths. Only use files that appear in the listing; never invent files.
        Before answering, call CHECK_PLAN with your pipeline, samplesheet and parameters, fix every problem
        it reports, and repeat until it prints "PLAN CHECK: OK".'''
    tools 'nf:module_run:LIST_FILES', 'nf:module_run:READ_TEXT', 'nf:module_run:CHECK_PLAN'
    skills 'nfcore-rnaseq', 'nfcore-scrnaseq'
    maxIterations 25

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
    and a short rationale that explains how files were grouped into samples and why each parameter is set.
    """
}

agent operator {
    model "openai/${params.model}"
    instruction '''You are Geth's pipeline operator. You execute a plan that a person has approved, using the
        RUN_NFCORE tool. First call it with the approved samplesheet and parameters exactly as given.
        If the tool reports STATUS: FAILED, change only what the error names and call RUN_NFCORE again:
        the run resumes where it stopped. Never change sample names, file assignments or the pipeline.
        If the tool reports STATUS: REFUSED, your change was not allowed: go back to the approved plan.
        Make at most 3 RUN_NFCORE calls. If the error cannot be fixed within these rules, stop and report it.
        Never claim success unless the tool printed STATUS: SUCCESS.'''
    tools 'nf:module_run:RUN_NFCORE'
    maxIterations 10

    input:
    plan: AnalysisPlan

    output:
    outcome: RunOutcome

    prompt:
    """
    Execute the approved plan now: call RUN_NFCORE with its pipeline, samplesheet_csv and params_json.
    In your final answer state: whether the run succeeded, how many RUN_NFCORE calls you made,
    the OUTDIR printed by the tool (or "none"), every change you made to the plan (or none),
    and the last error (or "none").
    """
}

agent reporter {
    model "openai/${params.model}"
    instruction '''You are Geth's reporting assistant. You write concise, factual analysis reports in Markdown
        for biologists. Copy tables and numbers from the COLLECT_RESULTS output exactly as printed: do not
        convert units, recompute, round differently, estimate ratios or invent values. Do not add links.
        Say clearly when something is missing. Interpret results in the light of the data actually used
        (for example a reference subset, or tiny test data) before suggesting lab or sequencing changes.'''
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
    Summary; Samples (how input files were grouped, from the plan); Quality control (copy the QC tables);
    Results; Caveats and next steps. If the run failed, explain why and what a person should check instead.
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
    d.resolve('plan_pipeline.txt').text = plan.pipeline.trim().replace('nf-core/', '') + '\n'
    d.resolve('plan_samplesheet.csv').text = plan.samplesheet_csv.trim() + '\n'
    d.resolve('plan_params.json').text = plan.params_json.trim() + '\n'
    d.resolve('plan_rationale.txt').text = plan.rationale.trim() + '\n'
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
        changes_to_plan: ${outcome.fixes_applied}
        last_error: ${outcome.last_error}
        """.stripIndent()
}

process FINALIZE_REPORT {
    executor 'local'
    scratch false

    input:
    tuple(report: String, outcome: RunOutcome)

    output:
    check: String = stdout()

    script:
    """
cat > report.raw.md <<'GETH_EOF'
${report}
GETH_EOF
pipeline=\$(cat "${params.run_dir}/plan_pipeline.txt")
check_report.py report.raw.md "${params.run_dir}" "\$pipeline" "${outcome.attempts}" > "${params.run_dir}/report.md"
cat "${params.run_dir}/report_check.txt"
    """
}

workflow {
    if( params.model != 'Qwen/Qwen3.5-397B-A17B-FP8' )
        error "Geth runs on the free ELM model Qwen/Qwen3.5-397B-A17B-FP8 only (got '${params.model}')"
    if( !params.run_dir || !params.run_dir.startsWith("${params.data_root}/geth/runs/") )
        error "run_dir must be under ${params.data_root}/geth/runs/"

    if( params.mode == 'plan' ) {
        if( !params.question || !params.data_dir )
            error "--mode plan needs --question and --data_dir"
        file(params.run_dir).resolve('question.txt').text = params.question + '\n'
        SAVE_PLAN(planner(params.question, params.data_dir))
    }
    else if( params.mode == 'run' ) {
        def d = file(params.run_dir)
        if( !d.resolve('APPROVED').exists() )
            error "The plan in ${params.run_dir} has not been approved: run `geth approve` first"
        def question = d.resolve('question.txt').text.trim()
        def plan = channel.of(record(
            pipeline: d.resolve('plan_pipeline.txt').text.trim(),
            samplesheet_csv: d.resolve('plan_samplesheet.csv').text,
            params_json: d.resolve('plan_params.json').text,
            rationale: d.resolve('plan_rationale.txt').text))
        def outcome = operator(plan)
        SAVE_OUTCOME(outcome)
        def report = reporter(question, plan.combine(outcome))
        FINALIZE_REPORT(report.combine(outcome)).view()
    }
    else {
        error "--mode must be 'plan' or 'run'"
    }
}
