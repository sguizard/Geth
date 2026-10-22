"""A minimal client for an OpenAI-compatible chat-completions endpoint.

Client() is the site's model service, from the site configuration (env.sh): GETH_LLM_BASE_URL, GETH_LLM_MODEL,
GETH_LLM_ALLOWED_MODELS and GETH_LLM_API_KEY_VAR (the name of the variable that holds the key).
Client("GETH_PLANNER") is another model for the planner only (a comparison chosen by a person), and only with a
hard budget: GETH_PLANNER_MODEL, GETH_PLANNER_BASE_URL, GETH_PLANNER_API_KEY_VAR, GETH_PLANNER_PRICES ("input,
cached input, output" in USD per million tokens) and GETH_PLANNER_BUDGET_USD (per plan). It stops before a request
once the plan has spent its budget.
The key is only ever put in the request header: never in a message, an error, a log or the trace.
"""
import json
import os
import time
import urllib.error
import urllib.request


class ModelError(Exception):
    pass


class Client:
    def __init__(self, prefix="GETH_LLM", timeout=600, retries=4):
        env = lambda k, default="": os.environ.get(f"{prefix}_{k}", default)
        self.base_url, self.model = env("BASE_URL").rstrip("/"), env("MODEL")
        if not self.base_url or not self.model:
            raise ModelError(f"{prefix}_BASE_URL and {prefix}_MODEL must be set" + (": source env.sh" if prefix == "GETH_LLM" else ""))
        self.prices, self.budget = None, None
        if prefix == "GETH_LLM":
            allowed = env("ALLOWED_MODELS", self.model).replace(",", " ").split()
            if self.model not in allowed:
                raise ModelError(f"model '{self.model}' is not in GETH_LLM_ALLOWED_MODELS ({', '.join(allowed)})")
        else:  # a model chosen by a person for one comparison: only with prices and a hard budget
            try:
                self.prices = [float(x) for x in env("PRICES").split(",")]
                self.budget = float(env("BUDGET_USD"))
                assert len(self.prices) == 3 and self.budget > 0
            except (ValueError, AssertionError):
                raise ModelError(f"{prefix}_MODEL needs {prefix}_PRICES (input,cached input,output USD per million "
                                 f"tokens) and {prefix}_BUDGET_USD (the most one plan may spend)") from None
        key_var = env("API_KEY_VAR", f"{prefix}_API_KEY")
        self._key = os.environ.get(key_var, "")
        if not self._key:
            raise ModelError(f"the API key variable {key_var} is empty")
        self.timeout, self.retries = timeout, retries
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
                      "reasoning_tokens": 0, "seconds": 0.0, "usd": 0.0}

    def chat(self, messages, tools=None):
        """One chat completion: returns the assistant message (content, tool_calls)."""
        if self.budget is not None and self.usage["usd"] >= self.budget:
            raise ModelError(f"budget reached: this plan has spent ${self.usage['usd']:.4f} of its "
                             f"${self.budget:.4f} on {self.model}")
        body = {"model": self.model, "messages": messages}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        if self.budget is not None:
            body["max_completion_tokens"] = 32000  # one answer, reasoning included, cannot run away
        data = json.dumps(body).encode()
        t0 = time.time()
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(f"{self.base_url}/chat/completions", data=data, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {self._key}"})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    reply = json.load(response)
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:400]
                if e.code in (408, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                raise ModelError(f"model service: HTTP {e.code} {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if attempt < self.retries:
                    time.sleep(min(60, 5 * 2 ** attempt))
                    continue
                raise ModelError(f"model service unreachable: {e}") from None
        usage = reply.get("usage") or {}
        prompt, completion = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += prompt
        self.usage["completion_tokens"] += completion  # reasoning tokens included, as they are billed
        self.usage["cached_tokens"] += cached
        self.usage["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        self.usage["seconds"] += time.time() - t0
        if self.prices:
            p_in, p_cached, p_out = self.prices
            self.usage["usd"] += ((prompt - cached) * p_in + cached * p_cached + completion * p_out) / 1e6
        try:
            return reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError(f"unexpected reply from the model service: {str(reply)[:300]}") from None
