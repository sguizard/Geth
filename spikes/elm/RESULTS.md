# Spike 1 — ELM capability check (2026-10-16)

Run: `source Geth/env.sh; python3 spikes/elm/elm_probe.py --out $PERSEUS_VEIL/spikes/elm/probe_login.json` (node1q01).

| Test | Qwen3.5-397B-A17B-FP8 | Mistral-Small-4-119B-2603 |
|---|---|---|
| basic chat | PASS, 30 s (thinking on: ~1.75k completion tokens) | PASS, 0.7 s |
| tool call, `auto` | PASS, 2.1 s | PASS, 0.6 s |
| tool call, forced | PASS, 1.8 s | PASS, 0.6 s |
| tool round-trip (call → result → answer) | PASS, 3.9 s | PASS, 2.0 s |
| JSON-schema structured output (samplesheet) | PASS, 29 s | PASS, 1.5 s |
| long-context needle, ~10k / ~42k / ~132k prompt tokens | PASS / PASS / PASS | PASS / FAIL* / PASS |

\* Mistral answered `The sample` and stopped early: a one-off truncation, not a context limit (the 135k prompt passed).

## Findings
- API is OpenAI-compatible at `https://elm.edina.ac.uk/api/v1` (vLLM-style `tool_calls`, `response_format: json_schema`).
- No rate-limit headers returned; usage (`prompt_tokens`, `completion_tokens`) is reported.
- Qwen thinks by default. `chat_template_kwargs: {"enable_thinking": false}` drops a simple answer from 32 s to 0.9 s.
  Thinking may be worth keeping for planning/debugging steps; disable it for mechanical steps.
- The key also exposes paid GPT models → the allowlist guard is mandatory (`GETH_ALLOWED_MODELS` in `env.sh`).
- **Compute nodes can reach ELM** (`netcheck.sge`, queues `eddie` and `staging`: `/models` → 401 without key),
  plus GitHub and depot.galaxyproject.org. No proxy needed. The Nextflow driver (and its agents) can therefore run inside a qsub job.

**Verdict: GO.** Both models do reliable tool calling and structured output; Mistral is ~10–30× faster, Qwen is stronger at reasoning.
