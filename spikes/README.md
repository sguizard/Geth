# Feasibility spikes

Short experiments from the first days of the project (October 2026), kept as a record. Each `RESULTS.md`
says what was tested and what was learned:

- `elm/`: can the language-model endpoint do tool calls, JSON-schema output and long prompts?
- `nf-agent/`: can Nextflow's `agent` primitive call a process as a tool on a cluster?
- `nfcore/`: the first planner/operator/reporter workflow, on two nf-core test datasets.

They are tied to the cluster they ran on (paths, project codes) and are not maintained: the code that came
out of them lives in `geth/`, and [docs/history](../docs/history/) tells the rest of the story.
