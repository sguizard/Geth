// Reference Nextflow project for arm C (written by hand, not by an agent): the arm B reference steps, chained.
params.input  = null
params.outdir = 'results'
params.models = null

process PREPROCESS {
    cpus 2

    input:
    path h5ad

    output:
    path 'preprocessed.h5ad'

    script:
    """
    preprocess.py ${h5ad} preprocessed.h5ad
    """
}

process ANNOTATE {
    cpus 2

    input:
    path h5ad
    path models

    output:
    path 'annotated.h5ad'

    script:
    """
    annotate.py ${h5ad} annotated.h5ad
    """
}

process PSEUDOBULK_DE {
    cpus 2
    publishDir params.outdir, mode: 'copy'

    input:
    path h5ad

    output:
    path 'final.h5ad'
    path 'de_results.tsv'

    script:
    """
    de.py ${h5ad} final.h5ad
    """
}

workflow {
    PSEUDOBULK_DE(ANNOTATE(PREPROCESS(file(params.input)), file(params.models)))
}
