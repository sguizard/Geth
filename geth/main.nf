/*
 * Geth: language-model agents plan, run, fix and report bioinformatics analyses with nf-core pipelines.
 *
 *   --mode plan : planner inspects the data folder (and, for a follow-up analysis such as
 *                 differential expression, the upstream run given by --upstream_run) and
 *                 writes plan_* files into run_dir
 *   (a person reviews and approves the plan: `geth approve`)
 *   --mode run  : operator launches the approved plan (gated retries), reporter writes report.md,
 *                 every number in the report is checked against the results
 *   --mode report : reporter writes report.md again from a finished run's results (no pipeline launch)
 *
 * Most tools run as local processes next to the driver (which must be able to submit jobs); the nf-core
 * runs submit their own jobs through the site profile; the single-cell toolbox runs as cluster jobs.
 * Site settings (model, folders, profiles) come from env.sh / site/site.env through nextflow.config.
 */
nextflow.enable.types = true

// What the planner returns: lists instead of JSON-in-text, which the structured-output step mangles.
record PlanProposal {
    pipeline: String
    samplesheet_lines: List<String>
    params: List<String>
    contrasts_lines: List<String>
    profile: String
    rationale: String
}

// The approved plan, read back from the plan_* files.
record AnalysisPlan {
    pipeline: String
    samplesheet_csv: String
    params_json: String
    contrasts_csv: String
    profile: String
    rationale: String
}

record RunOutcome {
    succeeded: Boolean
    attempts: Integer
    outdir: String
    fixes_applied: List<String>
    annotations: List<String>
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
        ${params.data_root}/*.gz) echo "(file type: \$(file -b "${path}"); first 8 lines, decompressed)"; zcat "${path}" 2>&1 | head -n 8 ;;
        ${params.data_root}/*) head -c 8000 "${path}" ;;
        *) echo "REFUSED: only files under ${params.data_root} can be read" ;;
    esac
    """
}

process LIST_REFERENCES {
    executor 'local'
    scratch false

    input:
    species: String

    output:
    listing: String = stdout()

    script:
    """
    found=0
    for readme in ${params.references}/*/README.txt; do
        [ -f "\$readme" ] || continue
        found=1; echo "== \$(dirname "\$readme")"; cat "\$readme"; echo
    done
    [ \$found = 1 ] || echo "The reference catalogue is empty."
    """
}

process CHECK_PLAN {
    executor 'local'
    scratch false

    input:
    pipeline: String
    samplesheet_csv: String
    params_json: String
    contrasts_csv: String
    profile: String

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
cat > contrasts.csv <<'GETH_EOF'
${contrasts_csv.trim()}
GETH_EOF
geth_checks.py check-plan "${pipeline}" samplesheet.csv params.json --save-checked "${params.run_dir}" \
    --contrasts contrasts.csv --profile "${profile.trim()}" ${params.upstream_run ? "--upstream ${params.upstream_run}" : ''} || true
    """
}

process RUN_NFCORE {
    executor 'local'
    scratch false
    time 72.h

    input:
    pipeline: String
    samplesheet_csv: String
    params_json: String
    contrasts_csv: String
    profile: String

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
cat > contrasts.csv <<'GETH_EOF'
${contrasts_csv.trim()}
GETH_EOF
run_nfcore.sh "${params.run_dir}" "${pipeline}" samplesheet.csv params.json contrasts.csv "${profile.trim()}"
    """
}

// Single-cell toolbox (Geth's own, bin/sc_downstream.py), run as scheduler jobs in the pinned CellTypist container.
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

process SAVE_ANNOTATIONS {
    executor 'local'
    scratch false

    input:
    annotations: String

    output:
    saved: String = stdout()

    script:
    """
cat > "${params.run_dir}/annotations.txt" <<'GETH_EOF'
${annotations.trim()}
GETH_EOF
echo "Saved \$(grep -c . "${params.run_dir}/annotations.txt") annotation line(s)."
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
        sequencing data folder into a run plan for exactly one nf-core pipeline. For new sequencing data:
        "rnaseq" (bulk RNA-seq), "scrnaseq" (droplet single-cell RNA-seq), "sarek" (DNA-seq variant calling:
        germline or tumour/normal, WGS/WES/panels), "isoseq" (PacBio Iso-Seq full-length transcripts),
        "taxprofiler" (taxonomic profiling of shotgun metagenomes), "mag" (metagenome assembly and binning),
        "ampliseq" (amplicon/metabarcoding: 16S, 18S, ITS, COI), "chipseq" (ChIP-seq peaks), "atacseq"
        (ATAC-seq accessibility), "nanoseq" (Oxford Nanopore DNA/cDNA/direct RNA), "eager" (ancient DNA) or
        "methylseq" (DNA methylation: WGBS, RRBS, EM-seq, TAPS).
        For a follow-up analysis: "differentialabundance" for differential expression on the results of a
        finished nf-core/rnaseq run (an upstream run). If none of these fits the data or the request, say so
        in the rationale instead of forcing a pipeline.
        Always inspect the folders first: list them, then read every README/metadata text file in them;
        for a follow-up analysis also read the upstream run's question.txt, plan_samplesheet.csv,
        plan_params.json and plan_rationale.txt, and list its results folder.
        Load the skill of the pipeline you choose and follow its rules exactly.
        Use absolute paths. Only use files that appear in the listing; never invent files.
        If the folder holds no reference genome and annotation, call LIST_REFERENCES and use the entry for the
        right species; if none matches, say so in the rationale instead of guessing.
        For a follow-up of a finished nf-core/scrnaseq run, design a downstream analysis for Geth's single-cell
        toolbox instead (pipeline "sc_downstream"): load the sc-downstream skill, find the sample's filtered
        count matrix in the upstream results, call SC_INSPECT on it, and choose every design value from the
        observed data; the samplesheet is "sample,h5ad" and the parameters are the design key=value lines.
        Multiplexed 10x single-cell data (on-chip multiplexing OCM, CellPlex/CMO, Flex/probe barcodes: several
        samples share one library) needs nf-core/scrnaseq with aligner cellrangermulti and a second sheet that
        maps each library's barcodes to its samples: read the nfcore-scrnaseq skill's multiplexed section.
        Before answering, call CHECK_PLAN with your pipeline, samplesheet and parameters (as key=value lines),
        plus the second sheet in contrasts_csv (differentialabundance: the contrasts; multiplexed scrnaseq: the
        barcodes sheet) and the analysis profile for differentialabundance (empty strings otherwise),
        fix every problem it reports, and repeat until it prints "PLAN CHECK: OK". Read every WARNING it
        prints too: fix the plan, or explain in the rationale why the warning does not apply.'''
    tools 'nf:module_run:LIST_FILES', 'nf:module_run:READ_TEXT', 'nf:module_run:LIST_REFERENCES', 'nf:module_run:CHECK_PLAN',
        'nf:module_run:SC_INSPECT'
    skills 'nfcore-rnaseq', 'nfcore-scrnaseq', 'nfcore-differentialabundance', 'sc-downstream', 'nfcore-sarek',
        'nfcore-isoseq', 'nfcore-taxprofiler', 'nfcore-mag', 'nfcore-ampliseq', 'nfcore-chipseq', 'nfcore-atacseq',
        'nfcore-nanoseq', 'nfcore-eager', 'nfcore-methylseq'
    maxIterations 25

    input:
    question: String
    data_dir: String
    upstream: String

    output:
    plan: PlanProposal

    prompt:
    """
    Request: ${question}
    Data folder: ${data_dir}
    Upstream run: ${upstream}

    In your final answer give exactly the plan that passed CHECK_PLAN: the pipeline name (e.g. "rnaseq",
    "sarek", "differentialabundance"); the samplesheet (for differentialabundance: the observations sheet) as a
    list of CSV lines, header line first; the pipeline parameters as a list of key=value entries, one per
    parameter (do not include "input", "outdir", "contrasts" or "cellranger_multi_barcodes"); in
    contrasts_lines the second sheet as a list of CSV lines, header line first (differentialabundance: the
    contrasts; multiplexed 10x scrnaseq: the barcodes sheet; otherwise an empty list); the analysis profile
    for differentialabundance (otherwise an empty string); and a short rationale that explains how files or
    samples were grouped, which were left out and why, the contrasts and their direction (or which samples
    each multiplexed library holds), and why each parameter is set.
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
    Execute the approved plan now: call RUN_NFCORE with its pipeline, samplesheet_csv, params_json,
    contrasts_csv and profile (pass empty strings where the plan has none).
    In your final answer state: whether the run succeeded, how many RUN_NFCORE calls you made,
    the OUTDIR printed by the tool (or "none"), every change you made to the plan (or none),
    no annotations (an empty list), and the last error (or "none").
    """
}

agent analyst {
    model "openai/${params.model}"
    instruction '''You are Geth's single-cell analyst. You run a downstream analysis design that a person has
        approved, with the SC_ANALYSE tool, then interpret the diagnostics.
        First call SC_ANALYSE with the approved design lines exactly as given. Read the diagnostics: cells kept
        per QC step, doublet rate, clusters per resolution, and for each cluster its size, top markers, the
        canonical marker panel and the CellTypist label with its agreement.
        You may call SC_ANALYSE once more, only if a diagnostic shows a real problem, changing only tunable keys
        (QC thresholds, doublet rate/threshold, HVG number, neighbours, Leiden resolutions/chosen) and adding a
        line justification=... that cites the diagnostic. If STATUS: REFUSED, do not insist: report.
        The diagnostics end with FLAGS computed by Geth: for each flag, either revise the design to address it
        or state in your final answer why it needs no change. Do not describe the results as better than the
        diagnostics show.
        Then annotate every cluster of the final analysis from its markers, supported by CellTypist; write
        "uncertain" when markers and CellTypist disagree, and save the annotations with SAVE_ANNOTATIONS
        (one line per cluster: "cluster <id>: <cell type> (<key markers>)"). Never claim success unless the
        tool printed STATUS: SUCCESS.'''
    tools 'nf:module_run:SC_ANALYSE', 'nf:module_run:SAVE_ANNOTATIONS'
    skills 'sc-downstream'
    maxIterations 8

    input:
    plan: AnalysisPlan

    output:
    outcome: RunOutcome

    prompt:
    """
    Run the approved design now: call SC_ANALYSE with this design exactly as given (a JSON object; for a
    revision you may send the changed keys and the justification as key=value lines instead):
    ${plan.params_json}
    In your final answer state: whether the analysis succeeded, how many SC_ANALYSE calls you made, the OUTDIR
    of the final analysis, every change you made to the design with its justification (or none), how you
    handled each FLAG, one annotation per cluster as "cluster <id>: <cell type> (<key markers>)" (also saved
    with SAVE_ANNOTATIONS), and the last error (or "none").
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
    scratch false

    input:
    plan: PlanProposal

    output:
    check: String = stdout()

    script:
    """
cat > samplesheet.csv <<'GETH_EOF'
${plan.samplesheet_lines.join('\n')}
GETH_EOF
cat > params.txt <<'GETH_EOF'
${plan.params.join('\n')}
GETH_EOF
cat > rationale.txt <<'GETH_EOF'
${plan.rationale}
GETH_EOF
cat > contrasts.csv <<'GETH_EOF'
${plan.contrasts_lines.join('\n')}
GETH_EOF
geth_checks.py save-plan "${params.run_dir}" "${plan.pipeline}" samplesheet.csv params.txt rationale.txt \
    --contrasts contrasts.csv --profile "${plan.profile.trim()}" ${params.upstream_run ? "--upstream ${params.upstream_run}" : ''}
    """
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
        annotations: ${outcome.annotations}
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

// A list as SAVE_OUTCOME printed it ("[a, b]"), back as one entry for the reporter ([] when empty).
def savedList(text: String) -> List<String> {
    return text && text != '[]' ? [text.replaceAll(/^\[|\]$/, '')] : []
}

workflow {
    if( !params.model || !params.runs_dir || !params.data_root || !params.references )
        error "Geth's site settings are missing: source env.sh (it loads site/site.env) before running Geth"
    def allowed = params.allowed_models.tokenize(', ')
    if( !(params.model in allowed) )
        error "Model '${params.model}' is not in GETH_LLM_ALLOWED_MODELS (${allowed.join(', ')})"
    if( !params.run_dir || !params.run_dir.startsWith("${params.runs_dir}/") )
        error "run_dir must be under ${params.runs_dir}/"

    if( params.mode == 'plan' ) {
        if( !params.question || !params.data_dir )
            error "--mode plan needs --question and --data_dir"
        if( params.upstream_run && !file(params.upstream_run).resolve('APPROVED').exists() )
            error "Upstream run ${params.upstream_run} has no approved plan"
        file(params.run_dir).resolve('question.txt').text = params.question + '\n'
        file(params.run_dir).resolve('data_dir.txt').text = params.data_dir + '\n'
        def upstream = params.upstream_run
            ? "${params.upstream_run} (nf-core/${file(params.upstream_run).resolve('plan_pipeline.txt').text.trim()} results in ${params.upstream_run}/results)"
            : 'none (this is a new analysis of sequencing data)'
        SAVE_PLAN(planner(params.question, params.data_dir, upstream)).view()
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
            contrasts_csv: ['plan_contrasts.csv', 'plan_barcodes.csv'].collect { f -> d.resolve(f) }.findAll { f -> f.exists() }.collect { f -> f.text }.join(''),
            profile: d.resolve('plan_profile.txt').exists() ? d.resolve('plan_profile.txt').text.trim() : '',
            rationale: d.resolve('plan_rationale.txt').text))
        def outcome = d.resolve('plan_pipeline.txt').text.trim() == 'sc_downstream' ? analyst(plan) : operator(plan)
        SAVE_OUTCOME(outcome)
        def report = reporter(question, plan.combine(outcome))
        FINALIZE_REPORT(report.combine(outcome)).view()
    }
    else if( params.mode == 'report' ) {
        // The report of a finished run, written again from its results (e.g. after a better results summary)
        def d = file(params.run_dir)
        if( !d.resolve('APPROVED').exists() || !d.resolve('outcome.txt').exists() )
            error "No finished run in ${params.run_dir}: nothing to report"
        def question = d.resolve('question.txt').text.trim()
        def plan = channel.of(record(
            pipeline: d.resolve('plan_pipeline.txt').text.trim(),
            samplesheet_csv: d.resolve('plan_samplesheet.csv').text,
            params_json: d.resolve('plan_params.json').text,
            contrasts_csv: ['plan_contrasts.csv', 'plan_barcodes.csv'].collect { f -> d.resolve(f) }.findAll { f -> f.exists() }.collect { f -> f.text }.join(''),
            profile: d.resolve('plan_profile.txt').exists() ? d.resolve('plan_profile.txt').text.trim() : '',
            rationale: d.resolve('plan_rationale.txt').text))
        def saved: Map<String,String> = [:]  // outcome.txt: "key: value" lines written by SAVE_OUTCOME
        d.resolve('outcome.txt').readLines().each { line ->
            def i = line.indexOf(': ')
            if( i > 0 ) saved[line.substring(0, i)] = line.substring(i + 2)
        }
        def outcome = channel.of(record(
            succeeded: saved['succeeded'] == 'true',
            attempts: (saved['attempts'] ?: '0').toInteger(),
            outdir: saved['outdir'] ?: 'none',
            fixes_applied: savedList(saved['changes_to_plan'] ?: ''),
            annotations: savedList(saved['annotations'] ?: ''),
            last_error: saved['last_error'] ?: 'none'))
        def report = reporter(question, plan.combine(outcome))
        FINALIZE_REPORT(report.combine(outcome)).view()
    }
    else {
        error "--mode must be 'plan', 'run' or 'report'"
    }
}
