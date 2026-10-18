// Geth lab sandbox test (not an agent's code): Groovy in a Nextflow driver tries to get out of the arm C sandbox.
// Run by bench/lab/sandbox_test.sh --nextflow. Every value printed must be false or empty for the sandbox to pass.
params.input  = null
params.outdir = 'results'
params.models = null
params.probe  = ''

workflow {
    def result = [:]
    try {
        new URL('https://www.ebi.ac.uk').openConnection().with { conn -> conn.connectTimeout = 5000; conn.inputStream.close() }
        result.https_reachable = true
    } catch( Exception e ) {
        result.https_reachable = false
    }
    try {
        new Socket().withCloseable { s -> s.connect(new InetSocketAddress('129.215.0.1', 53), 5000) }
        result.tcp_to_ip = true
    } catch( Exception e ) {
        result.tcp_to_ip = false
    }
    result.host_folders_visible = (['/exports', '/home/sguizard'] + params.probe.tokenize(',')).findAll { d -> new File(d).exists() }
    result.secret_like_env = System.getenv().keySet().findAll { k -> ['KEY', 'TOKEN', 'SECRET', 'PASS', 'GETH', 'ELM', 'SGE'].any { w -> k.toUpperCase().contains(w) } && !k.startsWith('NXF_') }.sort()
    result.writable_outside_work = ['/in/probe', '/probe', '/opt/java/probe'].findAll { p ->
        try { new File(p).text = 'x'; true } catch( Exception e ) { false }
    }
    def proc = ['sh', '-c', 'qsub -help >/dev/null 2>&1 && echo yes || echo no'].execute()
    result.qsub_available = proc.text.trim() == 'yes'
    new File('/work/results').mkdirs()
    java.nio.file.Files.createSymbolicLink(java.nio.file.Paths.get('/work/results/link_outside'), java.nio.file.Paths.get('/etc/hostname'))
    println 'PROBE ' + groovy.json.JsonOutput.toJson(result)
}
