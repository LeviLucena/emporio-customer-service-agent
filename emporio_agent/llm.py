"""Minimal Ollama chat client (stdlib only, no third-party dependencies)."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_MODEL = "gpt-oss:120b-cloud"


class LLMError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, model: str | None = None, host: str | None = None, timeout: int = 180,
                 retries: int = 2, temperature: float = 0.2) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
        host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.host = host if host.startswith("http") else f"http://{host}"
        self.timeout, self.retries, self.temperature = timeout, retries, temperature

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """POST /api/chat (non-streaming) and return the assistant message dict."""
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"temperature": self.temperature}}
        if tools:
            payload["tools"] = tools
        body = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(f"{self.host}/api/chat", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))["message"]
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"Ollama request failed after {self.retries + 1} attempts: {last}")
