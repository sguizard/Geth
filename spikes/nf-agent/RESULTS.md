# Spike 2 — Nextflow `agent` + ELM (2026-10-16)

Nextflow 26.10.2, plugin `nf-agent@0.2.0` (runner `langchain4j`, in the driver JVM on node1q01).
Config: `agent { apiProvider='openai'; baseUrl='https://elm.edina.ac.uk/api/v1'; apiKey=System.getenv('ELM_API_KEY') }`,
`model "openai/${params.model}"` — the slash in `Qwen/Qwen3.5-...` is parsed correctly.

## hello/ — plain agent
2 questions answered by Qwen through ELM, no extra setup.

## qc-tool/ — agent calling a process as a tool on SGE
`qc_triage` agent → tool `FASTQC` (typed process, apptainer, roslin profile, SGE) → structured `QcVerdict` record.
4 FASTQ files (50 000 reads each) × 2 models:

| | Qwen3.5-397B | Mistral-Small-4 |
|---|---|---|
| tool called, SGE job OK (project roslin_alaw3_grp, checked with `qacct`) | 4/4 | 4/4 |
| `total_reads`, `sample`, `failed_modules` correct | 4/4 | 4/4 |
| trimming verdict correct (Adapter Content = PASS → no trimming) | 4/4 | 3/4 |
| agent wall time (incl. tool job) | 38–81 s | 8–14 s |

FASTQC SGE jobs took ~10 s each, queue wait included.

## Limitations / lessons
- **Tool inputs cannot be `Path` yet** (`nf-agent` 0.2.0: "not yet supported as an agent tool (Phase 3)").
  Workaround: pass absolute paths as `String` + `containerOptions "-B <data root>"` (shared filesystem).
- If a tool task fails the whole agent fails → tool wrappers must always exit 0 and report errors as text.
- Record outputs: use `List<String>` (bare `List` is rejected).
- **Structured output hallucination**: when the prompt did not ask the model to state a field in its final answer,
  Qwen invented it (`total_reads: 1000000`, `sample: "this file"`). Asking explicitly for every field fixed it (4/4).
  → Every agent prompt must name the facts to report, and Geth must validate agent outputs deterministically.
- Compute nodes are not SGE submit hosts: the Nextflow driver (and thus the agents) must run on node1q01.
- Type checker wants `memory 4.GB` (not `'4 GB'`) and explicit closure params (`map { fq -> ... }`).

**Verdict: GO.** Qwen is the default for decisions; Mistral is a fast option for mechanical steps.
