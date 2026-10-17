/*
 * Geth lab — EXPERIMENTAL. Not for real analyses.
 *
 * Phase 11: can language-model agents design (and later build) a coherent single-cell downstream analysis?
 *   --mode design : arm A, a designer agent writes a structured design for the question; nothing runs on the data.
 *                   --lab_skill false gives the designer no best-practice skill (arm A0), true gives it one (arm A1).
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
    if [ \$ok = 1 ]; then
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
    if [ \$ok = 1 ]; then head -c 8000 "${path}"
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
        file(params.run_dir).resolve('lab_arm.txt').text = (params.lab_skill ? 'A1 design, with skill' : 'A0 design, no skill') + '\n'
        def design = params.lab_skill ? designer_skill(params.question, params.data_dir) : designer_plain(params.question, params.data_dir)
        SAVE_DESIGN(design).view()
    }
    else {
        error "--mode must be 'design' (arms B and C come later)"
    }
}
