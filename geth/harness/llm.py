"""A minimal client for an OpenAI-compatible chat-completions endpoint.

Client() is the site's model service, from the site configuration (env.sh): GETH_LLM_BASE_URL, GETH_LLM_MODEL,
GETH_LLM_ALLOWED_MODELS and GETH_LLM_API_KEY_VAR (the name of the variable that holds the key).
Client("GETH_MODEL") is another model chosen by a person for one command (geth plan / project / lab ... --model
<name>, from the site's GETH_MODEL_<NAME>_* settings), and only with a hard budget: GETH_MODEL_MODEL,
GETH_MODEL_BASE_URL, GETH_MODEL_API_KEY_VAR, GETH_MODEL_PRICES ("input,cached input,output" in USD per million
tokens) and GETH_MODEL_BUDGET_USD (per agent stage). It stops before a request once the stage has spent its budget.
(GETH_PLANNER_* is the same, under its Geth 2.0.0 name.) model_client() picks the right one.
<prefix>_API=responses speaks OpenAI's Responses API instead of chat completions: the GPT-6 models refuse tools with
reasoning in chat completions. Reasoning effort: <prefix>_REASONING (default medium); the model's own reasoning
items are handed back to it at each turn (store=false, encrypted).
The key is only ever put in the request header: never in a message, an error, a log or the trace.
"""
import json
import os
import time
import urllib.error
import urllib.request


def model_client(site=False):
    """The model of an agent stage: the one a person chose for this command, if any, else the site's.
    site=True: always the site's (the stand-in scientist answers with the site's model)."""
    if not site:
        for prefix in ("GETH_MODEL", "GETH_PLANNER"):
            if os.environ.get(f"{prefix}_MODEL"):
                return Client(prefix)
    return Client()


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
        self.api = env("API", "chat")
        if self.api not in ("chat", "responses"):
            raise ModelError(f"{prefix}_API must be chat or responses (got {self.api})")
        self.reasoning = env("REASONING", "medium")
        self.encrypted = env("ENCRYPTED_REASONING", "yes") == "yes"
        self._turns = []  # Responses API: the raw output items of each answer, handed back in order
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
                      "reasoning_tokens": 0, "seconds": 0.0, "usd": 0.0}

    def chat(self, messages, tools=None, extra=None):
        """One answer of the model: returns an assistant message (content, tool_calls), whatever the API.
        extra: more request fields (chat completions only), e.g. turning a model's thinking off."""
        if self.budget is not None and self.usage["usd"] >= self.budget:
            raise ModelError(f"budget reached: this stage has spent ${self.usage['usd']:.4f} of its "
                             f"${self.budget:.4f} on {self.model}")
        if self.api == "responses":
            return self._responses(messages, tools)
        body = {"model": self.model, "messages": messages}
        if tools:
            body.update(tools=tools, tool_choice="auto")
        if self.budget is not None:
            body["max_completion_tokens"] = 32000  # one answer, reasoning included, cannot run away
        body.update(extra or {})
        reply, seconds = self._post("chat/completions", body)
        usage = reply.get("usage") or {}
        self._count(usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0,
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0, seconds)
        try:
            return reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError(f"unexpected reply from the model service: {str(reply)[:300]}") from None

    def _responses(self, messages, tools):
        body = {"model": self.model, "input": to_input(messages, self._turns), "store": False}
        if tools:
            body["tools"] = [{"type": "function", **t["function"]} for t in tools]
            body["tool_choice"] = "auto"
        if self.reasoning != "none":
            body["reasoning"] = {"effort": self.reasoning}
            if self.encrypted:
                body["include"] = ["reasoning.encrypted_content"]
        if self.budget is not None:
            body["max_output_tokens"] = 32000
        reply, seconds = self._post("responses", body)
        usage = reply.get("usage") or {}
        self._count(usage.get("input_tokens") or 0, usage.get("output_tokens") or 0,
                    (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0,
                    (usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0, seconds)
        if not isinstance(reply.get("output"), list):
            raise ModelError(f"unexpected reply from the model service: {str(reply)[:300]}")
        message, items = from_output(reply["output"])
        self._turns.append(items)
        return message

    def _count(self, prompt, completion, cached, reasoning, seconds):
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += prompt
        self.usage["completion_tokens"] += completion  # reasoning tokens included, as they are billed
        self.usage["cached_tokens"] += cached
        self.usage["reasoning_tokens"] += reasoning
        self.usage["seconds"] += seconds
        if self.prices:
            p_in, p_cached, p_out = self.prices
            self.usage["usd"] += ((prompt - cached) * p_in + cached * p_cached + completion * p_out) / 1e6

    def _post(self, path, body):
        data = json.dumps(body).encode()
        t0 = time.time()
        for attempt in range(self.retries + 1):
            request = urllib.request.Request(f"{self.base_url}/{path}", data=data, method="POST",
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
        return reply, time.time() - t0


def to_input(messages, turns):
    """Chat messages as Responses API input items. The k-th assistant message is replaced by the raw output items
    of the k-th answer (its reasoning and tool calls), when the client kept them."""
    items, k = [], 0
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            if k < len(turns):
                items += turns[k]
            else:
                if m.get("content"):
                    items.append({"role": "assistant", "content": m["content"]})
                for c in m.get("tool_calls") or []:
                    items.append({"type": "function_call", "call_id": c.get("id", ""),
                                  "name": c["function"]["name"], "arguments": c["function"].get("arguments") or "{}"})
            k += 1
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""), "output": m.get("content", "")})
        else:
            items.append({"role": role, "content": m.get("content", "")})
    return items


def from_output(output):
    """A Responses API answer as a chat message, plus the items to hand back next turn."""
    text, calls, keep = [], [], []
    for o in output:
        kind = o.get("type")
        if kind == "message":
            t = "".join(c.get("text", "") for c in o.get("content") or [] if c.get("type") in ("output_text", "text"))
            text.append(t)
            keep.append({"role": "assistant", "content": t})
        elif kind == "function_call":
            calls.append({"id": o.get("call_id", ""), "type": "function",
                          "function": {"name": o.get("name", ""), "arguments": o.get("arguments") or "{}"}})
            keep.append({"type": "function_call", "call_id": o.get("call_id", ""), "name": o.get("name", ""),
                         "arguments": o.get("arguments") or "{}"})
        elif kind == "reasoning" and o.get("encrypted_content"):  # only what can be handed back with store=false
            keep.append({k: o[k] for k in ("type", "id", "summary", "encrypted_content") if k in o})
    message = {"content": "\n".join(t for t in text if t)}
    if calls:
        message["tool_calls"] = calls
    return message, keep
