/*
 * Geth lab — EXPERIMENTAL. Not for real analyses.
 *
 * Phase 11: can language-model agents design (and later build) a coherent single-cell downstream analysis?
 *   --mode design : arm A, a designer agent writes a structured design for the question; nothing runs on the data.
 *                   --lab_skill false gives the designer no best-practice skill (arm A0), true gives it one (arm A1).
 *   --mode engineer: arm B, an engineer agent implements a checked design as Python step scripts, testing each
 *                   one on a subset in the sandbox, then saves the pipeline spec (--build_round 1 or 2).
 *                   --lab_skill false: the engineer has no coding skill (arm B0).
 *   --mode review  : arm B, a reviewer agent reads the scripts and their test outputs: approve or revise.
 *                   geth lab build runs these rounds, then the pipeline Geth renders from the spec.
 *
 * The lab is separate from Geth's workflow: its file tools only reach the benchmark folders (GETH_LAB_DATA), so
 * the truth used to score designs stays out of the agents' reach.
 */
nextflow.enable.types = true

// The design, as lists of lines (a nested structure would be mangled by the structured-output step).
record LabDesign {
    steps: List<String>
    statistics: List<String>
    expected: List<String>
    rationale: String
}

record LabNotes {
    notes: List<String>
}

record LabReview {
    verdict: String
    issues: List<String>
}

// ---------------------------------------------------------------- tools

process LAB_LIST_FILES {
    executor 'local'
    scratch false

    input:
    dir: String

    output:
    listing: String = stdout()

    script:
    """
    ok=0
    for root in ${params.lab_data.tokenize(':').join(' ')}; do
        case "${dir}" in "\$root"|"\$root"/*) ok=1 ;; esac
    done
    if [ \$ok = 1 ] && [ ! -d "${dir}" ]; then
        echo "NOT FOUND: no folder ${dir}; list its parent folder to see what exists"
    elif [ \$ok = 1 ]; then
        find "${dir}" -maxdepth 3 \\( -type f -o -type l \\) -printf '%p\\t%s bytes\\n' | sort | head -n 300
    else
        echo "REFUSED: the lab only lists benchmark folders: ${params.lab_data}"
    fi
    """
}

process LAB_READ_TEXT {
    executor 'local'
    scratch false

    input:
    path: String

    output:
    text: String = stdout()

    script:
    """
    ok=0
    for root in ${params.lab_data.tokenize(':').join(' ')}; do
        case "${path}" in "\$root"/*) ok=1 ;; esac
    done
    case "${path}" in *.h5ad|*.gz) ok=binary ;; esac
    if [ \$ok = 1 ] && [ ! -f "${path}" ]; then echo "NOT FOUND: no file ${path}; use LAB_LIST_FILES to see what exists"
    elif [ \$ok = 1 ]; then head -c 8000 "${path}"
    elif [ \$ok = binary ]; then echo "REFUSED: binary file; use LAB_INSPECT for count matrices"
    else echo "REFUSED: the lab only reads benchmark folders: ${params.lab_data}"
    fi
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
    for readme in ${params.references}/*/README.txt; do
        [ -f "\$readme" ] || continue
        echo "== \$(dirname "\$readme")"; cat "\$readme"; echo
    done
    """
}

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

process CHECK_DESIGN {
    executor 'local'
    scratch false

    input:
    steps: String
    statistics: String
    expected: String

    output:
    report: String = stdout()

    script:
    """
cat > steps.txt <<'GETH_EOF'
${steps.trim()}
GETH_EOF
cat > statistics.txt <<'GETH_EOF'
${statistics.trim()}
GETH_EOF
cat > expected.txt <<'GETH_EOF'
${expected.trim()}
GETH_EOF
lab_checks.py check-design steps.txt statistics.txt expected.txt --save-checked "${params.run_dir}"
    """
}

// ---------------------------------------------------------------- arm B tools
// Agent text reaches the shell only inside single quotes, with each ' written as '\'' so it can never end the
// quoted string; lab_build.py then checks names and paths.

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

process WRITE_STEP {
    executor 'local'
    scratch false

    input:
    name: String
    code: String

    output:
    report: String = stdout()

    script:
    def quoted = code.replace("'", "'\\''")
    def safe = name.replace("'", "'\\''")
    """
    printf '%s' '${quoted}' | lab_build.py write-step "${params.run_dir}" '${safe}'

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

process READ_BUILD {
    executor 'local'
    scratch false

    input:
    what: String

    output:
    text: String = stdout()

    script:
    def safe = what.replace("'", "'\\''")
    """
    lab_build.py read "${params.run_dir}" '${safe}'
    """
}

process SAVE_SPEC {
    executor 'local'
    scratch false

    input:
    spec: String

    output:
    report: String = stdout()

    script:
    def quoted = spec.replace("'", "'\\''")
    """
    printf '%s' '${quoted}' | lab_build.py check-spec "${params.run_dir}"
    """
}

// ---------------------------------------------------------------- agents
// The two designers differ only by the skill (arm A1 has it, A0 does not).


agent designer_skill {
    model "openai/${params.model}"
    instruction '''You are an EXPERIMENTAL single-cell analysis designer in Geth's lab. You design, but do not
    run, a complete downstream analysis of single-cell RNA-seq count data that answers a scientist's question.
    Inspect before you design: list the data folder, read its README and other text files, call LAB_INSPECT on
    the count matrix, and call LIST_REFERENCES for annotation models. Choose every value from what you saw.
    Write the design as three lists of lines.
    steps: one line per step, "<step> | <method> | <tool> | <key parameters> | <why>", where <step> is one of
      qc, doublets, normalisation, feature_selection, dimensionality_reduction, integration, clustering,
      annotation, differential_expression (all nine; write the method "none" and why if a step is not needed).
    statistics: one line per comparison the question needs, "<comparison> | <unit of replication> |
      <test or model> | <design formula> | <multiple testing>".
    expected: what the results should show if the analysis works, one expectation per line.
    Call CHECK_DESIGN with the steps, statistics and expected lines until it prints "DESIGN CHECK: OK".'''
    tools 'nf:module_run:LAB_LIST_FILES', 'nf:module_run:LAB_READ_TEXT', 'nf:module_run:LAB_INSPECT',
        'nf:module_run:LIST_REFERENCES', 'nf:module_run:CHECK_DESIGN'
    skills 'sc-design-lab'
    maxIterations 25

    input:
    question: String
    data_dir: String

    output:
    design: LabDesign

    prompt:
    """
    Request: ${question}
    Data folder: ${data_dir}

    In your final answer give the steps, the statistics and the expected results exactly as checked, each as a
    list of lines, and a short rationale for the main choices.
    """
}

agent designer_plain {
    model "openai/${params.model}"
    instruction '''You are an EXPERIMENTAL single-cell analysis designer in Geth's lab. You design, but do not
    run, a complete downstream analysis of single-cell RNA-seq count data that answers a scientist's question.
    Inspect before you design: list the data folder, read its README and other text files, call LAB_INSPECT on
    the count matrix, and call LIST_REFERENCES for annotation models. Choose every value from what you saw.
    Write the design as three lists of lines.
    steps: one line per step, "<step> | <method> | <tool> | <key parameters> | <why>", where <step> is one of
      qc, doublets, normalisation, feature_selection, dimensionality_reduction, integration, clustering,
      annotation, differential_expression (all nine; write the method "none" and why if a step is not needed).
    statistics: one line per comparison the question needs, "<comparison> | <unit of replication> |
      <test or model> | <design formula> | <multiple testing>".
    expected: what the results should show if the analysis works, one expectation per line.
    Call CHECK_DESIGN with the steps, statistics and expected lines until it prints "DESIGN CHECK: OK".'''
    tools 'nf:module_run:LAB_LIST_FILES', 'nf:module_run:LAB_READ_TEXT', 'nf:module_run:LAB_INSPECT',
        'nf:module_run:LIST_REFERENCES', 'nf:module_run:CHECK_DESIGN'
    maxIterations 25

    input:
    question: String
    data_dir: String

    output:
    design: LabDesign

    prompt:
    """
    Request: ${question}
    Data folder: ${data_dir}

    In your final answer give the steps, the statistics and the expected results exactly as checked, each as a
    list of lines, and a short rationale for the main choices.
    """
}

// Arm B: the engineer implements a checked design; the reviewer reads the result with fresh eyes.

agent engineer {
    model "openai/${params.model}"
    instruction '''You are an EXPERIMENTAL single-cell analysis engineer in Geth's lab. You implement an analysis
    design that a person has already checked, as Python step scripts that Geth chains into a pipeline.
    Each step is one script, run as "python3 step.py <input.h5ad> <output.h5ad>" in a sandbox: no network, no
    files but its input, its own working folder, and ./models (CellTypist models Immune_All_Low.pkl and
    Immune_All_High.pkl). Libraries: scanpy, anndata, celltypist, pydeseq2, harmonypy, numpy, pandas, scipy,
    scikit-learn, statsmodels, matplotlib, seaborn. Read the input from sys.argv[1] and write the AnnData for the
    next step to sys.argv[2]; keep the raw counts (layers["counts"]) through every step; write tables (.tsv, tab
    separated) and figures (.png) in the working folder.
    Results contract: the last step's AnnData has obs["cell_type"] (the annotation). The step that compares
    conditions writes de_results.tsv, and the step that finds markers of clusters or cell types writes
    markers.tsv; both have at least the columns cell_type, gene, log2fc, padj (one row per gene and cell type).
    Implement the design's steps in its order; one script may hold several small steps; leave out steps whose
    method is none. Work one step at a time: WRITE_STEP saves a script and checks it; TEST_STEP runs it on a
    3000-cell subset, the first step from "input", every other step from the previous step's name, and shows
    its log and outputs. Fix and test again until the step works and its outputs look right (cells kept,
    columns, plausible values), then go on to the next step. READ_BUILD shows the design, the subset, your
    steps and their test outputs. When every step has passed its test in order, call SAVE_SPEC with one line
    per step in order, "<step> | <cpus> | <memory GB> | <minutes>" for the full data (at most 8 cpus, 64 GB,
    240 minutes), until it prints "SPEC CHECK: OK".'''
    tools 'nf:module_run:WRITE_STEP', 'nf:module_run:TEST_STEP', 'nf:module_run:READ_BUILD', 'nf:module_run:SAVE_SPEC'
    skills 'sc-build-lab'
    maxIterations 90

    input:
    question: String
    design: String
    review: String
    subset: String

    output:
    notes: LabNotes

    prompt:
    """
    Request: ${question}

    The checked design:
    ${design}

    Review of the previous round: ${review}

    The subset for tests: ${subset}

    When SAVE_SPEC has printed "SPEC CHECK: OK", answer with short notes: one line per step on what it does
    and anything a reviewer should know.
    """
}

// The same engineer without the coding skill (arm B0).
agent engineer_plain {
    model "openai/${params.model}"
    instruction '''You are an EXPERIMENTAL single-cell analysis engineer in Geth's lab. You implement an analysis
    design that a person has already checked, as Python step scripts that Geth chains into a pipeline.
    Each step is one script, run as "python3 step.py <input.h5ad> <output.h5ad>" in a sandbox: no network, no
    files but its input, its own working folder, and ./models (CellTypist models Immune_All_Low.pkl and
    Immune_All_High.pkl). Libraries: scanpy, anndata, celltypist, pydeseq2, harmonypy, numpy, pandas, scipy,
    scikit-learn, statsmodels, matplotlib, seaborn. Read the input from sys.argv[1] and write the AnnData for the
    next step to sys.argv[2]; keep the raw counts (layers["counts"]) through every step; write tables (.tsv, tab
    separated) and figures (.png) in the working folder.
    Results contract: the last step's AnnData has obs["cell_type"] (the annotation). The step that compares
    conditions writes de_results.tsv, and the step that finds markers of clusters or cell types writes
    markers.tsv; both have at least the columns cell_type, gene, log2fc, padj (one row per gene and cell type).
    Implement the design's steps in its order; one script may hold several small steps; leave out steps whose
    method is none. Work one step at a time: WRITE_STEP saves a script and checks it; TEST_STEP runs it on a
    3000-cell subset, the first step from "input", every other step from the previous step's name, and shows
    its log and outputs. Fix and test again until the step works and its outputs look right (cells kept,
    columns, plausible values), then go on to the next step. READ_BUILD shows the design, the subset, your
    steps and their test outputs. When every step has passed its test in order, call SAVE_SPEC with one line
    per step in order, "<step> | <cpus> | <memory GB> | <minutes>" for the full data (at most 8 cpus, 64 GB,
    240 minutes), until it prints "SPEC CHECK: OK".'''
    tools 'nf:module_run:WRITE_STEP', 'nf:module_run:TEST_STEP', 'nf:module_run:READ_BUILD', 'nf:module_run:SAVE_SPEC'
    maxIterations 90

    input:
    question: String
    design: String
    review: String
    subset: String

    output:
    notes: LabNotes

    prompt:
    """
    Request: ${question}

    The checked design:
    ${design}

    Review of the previous round: ${review}

    The subset for tests: ${subset}

    When SAVE_SPEC has printed "SPEC CHECK: OK", answer with short notes: one line per step on what it does
    and anything a reviewer should know.
    """
}

agent reviewer {
    model "openai/${params.model}"
    instruction '''You are an EXPERIMENTAL code reviewer in Geth's lab. A person checked an analysis design; an
    engineer implemented it as Python step scripts, tested each on a 3000-cell subset, and saved the pipeline
    spec. Review the implementation with fresh eyes. READ_BUILD shows the design ("design"), the spec ("spec"),
    the steps and their test status ("steps"), each script ("step:<name>"), its test log and outputs
    ("test:<name>") and the tables it wrote ("file:<name>/<table>"). Read every script. Check that each design
    step is implemented as designed (method, thresholds, what is compared with what, the unit of replication,
    the design formula); that raw counts are used where the design needs them (pseudobulk sums, DESeq2) and
    normalised values elsewhere; that no step silently drops cells, genes or samples, mixes up conditions or
    reverses a contrast; that the outputs follow the contract (obs cell_type; de_results.tsv or markers.tsv with
    cell_type, gene, log2fc, padj); and that the subset results look plausible. Answer with verdict "approve" or
    "revise", and issues: one line per required change, naming the step and what to change (no issues when you
    approve). Ask only for changes that affect correctness, not for style.'''
    tools 'nf:module_run:READ_BUILD'
    maxIterations 40

    input:
    question: String
    design: String

    output:
    review: LabReview

    prompt:
    """
    Request: ${question}

    The checked design:
    ${design}
    """
}

// ---------------------------------------------------------------- bookkeeping

process SAVE_DESIGN {
    executor 'local'
    scratch false

    input:
    design: LabDesign

    output:
    check: String = stdout()

    script:
    """
cat > steps.txt <<'GETH_EOF'
${design.steps.join('\n')}
GETH_EOF
cat > statistics.txt <<'GETH_EOF'
${design.statistics.join('\n')}
GETH_EOF
cat > expected.txt <<'GETH_EOF'
${design.expected.join('\n')}
GETH_EOF
cat > rationale.txt <<'GETH_EOF'
${design.rationale}
GETH_EOF
lab_checks.py save-design "${params.run_dir}" steps.txt statistics.txt expected.txt rationale.txt
    """
}

process SAVE_NOTES {
    executor 'local'
    scratch false

    input:
    notes: LabNotes

    output:
    report: String = stdout()

    script:
    def quoted = notes.notes.join('\n').replace("'", "'\\''")
    """
    printf '%s\n' '${quoted}' > "${params.run_dir}/engineer_notes_${params.build_round}.txt"
    lab_build.py read "${params.run_dir}" spec
    """
}

process SAVE_REVIEW {
    executor 'local'
    scratch false

    input:
    review: LabReview

    output:
    report: String = stdout()

    script:
    def verdict = review.verdict.toLowerCase().contains('approve') && !review.verdict.toLowerCase().contains('revise') ? 'approve' : 'revise'
    def quoted = review.issues.join('\n').replace("'", "'\\''")
    """
    printf '%s' '${quoted}' | lab_build.py save-review "${params.run_dir}" "${params.build_round}" "${verdict}"
    """
}

workflow {
    if( !params.model || !params.runs_dir || !params.lab_data )
        error "Geth's site settings are missing: source env.sh before running the lab"
    def allowed = params.allowed_models.tokenize(', ')
    if( !(params.model in allowed) )
        error "Model '${params.model}' is not in GETH_LLM_ALLOWED_MODELS (${allowed.join(', ')})"
    if( !params.run_dir || !params.run_dir.startsWith("${params.runs_dir}/lab/") )
        error "run_dir must be under ${params.runs_dir}/lab/"
    if( !params.lab_data.tokenize(':').any { root -> params.data_dir == root || params.data_dir.startsWith("${root}/") } )
        error "The lab only works on benchmark data (GETH_LAB_DATA: ${params.lab_data})"

    if( params.mode == 'design' ) {
        file(params.run_dir).resolve('question.txt').text = params.question + '\n'
        file(params.run_dir).resolve('data_dir.txt').text = params.data_dir + '\n'
        // a command-line value arrives as text, and the text 'false' is true in Groovy
        def with_skill = params.lab_skill.toString() == 'true'
        file(params.run_dir).resolve('lab_arm.txt').text = (with_skill ? 'A1 design, with skill' : 'A0 design, no skill') + '\n'
        def design = with_skill ? designer_skill(params.question, params.data_dir) : designer_plain(params.question, params.data_dir)
        SAVE_DESIGN(design).view()
    }
    else if( params.mode == 'engineer' || params.mode == 'review' ) {
        def question = file(params.run_dir).resolve('question.txt').text.trim()
        def design = ['steps', 'statistics', 'expected'].collect { part ->
            "${part}:\n" + file(params.run_dir).resolve("lab_design_${part}.txt").text.readLines().findAll { line -> !line.startsWith('#') }.join('\n')
        }.join('\n\n')
        if( params.mode == 'engineer' ) {
            if( !params.data_file || !params.data_file.startsWith("${params.data_dir}/") )
                error "--data_file must be in the design's data folder (${params.data_dir})"
            // a command-line value arrives as text
            def previous = file(params.run_dir).resolve("review_${(params.build_round.toString() as int) - 1}.txt")
            def review = previous.exists() ? previous.text : 'none (first round)'
            def subset = MAKE_SUBSET(params.data_file)
            def with_skill = params.lab_skill.toString() == 'true'
            def notes = with_skill ? engineer(question, design, review, subset) : engineer_plain(question, design, review, subset)
            SAVE_NOTES(notes).view()
        }
        else {
            SAVE_REVIEW(reviewer(question, design)).view()
        }
    }
    else {
        error "--mode must be 'design', 'engineer' or 'review' (arm C comes later)"
    }
}
