"""A minimal client for the site's model service: an OpenAI-compatible chat-completions endpoint.

Settings come from the site configuration (env.sh): GETH_LLM_BASE_URL, GETH_LLM_MODEL, GETH_LLM_ALLOWED_MODELS and
GETH_LLM_API_KEY_VAR (the name of the variable that holds the key). The key is only ever put in the request
header: never in a message, an error, a log or the trace.
"""
import json
import os
import time
import urllib.error
import urllib.request


class ModelError(Exception):
    pass


class Client:
    def __init__(self, timeout=600, retries=4):
        self.base_url = os.environ.get("GETH_LLM_BASE_URL", "").rstrip("/")
        self.model = os.environ.get("GETH_LLM_MODEL", "")
        if not self.base_url or not self.model:
            raise ModelError("GETH_LLM_BASE_URL and GETH_LLM_MODEL must be set: source env.sh")
        allowed = os.environ.get("GETH_LLM_ALLOWED_MODELS", self.model).replace(",", " ").split()
        if self.model not in allowed:
            raise ModelError(f"model '{self.model}' is not in GETH_LLM_ALLOWED_MODELS ({', '.join(allowed)})")
        key_var = os.environ.get("GETH_LLM_API_KEY_VAR", "GETH_LLM_API_KEY")
        self._key = os.environ.get(key_var, "")
        if not self._key:
            raise ModelError(f"the API key variable {key_var} is empty")
        self.timeout, self.retries = timeout, retries
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0}

    def chat(self, messages, tools=None):
        """One chat completion: returns the assistant message (content, tool_calls)."""
        body = {"model": self.model, "messages": messages}
        if tools:
            body.update(tools=tools, tool_choice="auto")
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
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += usage.get("prompt_tokens") or 0
        self.usage["completion_tokens"] += usage.get("completion_tokens") or 0
        self.usage["seconds"] += time.time() - t0
        try:
            return reply["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError(f"unexpected reply from the model service: {str(reply)[:300]}") from None
