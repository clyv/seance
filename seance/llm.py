"""A small client for a local Ollama server (standard library only).

Adapted from my earlier project TalkDown, with embeddings added. Ollama's
structured outputs constrain Gemma's reply to a JSON schema, so parsing doesn't
depend on the model behaving.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    pass


def parse_json_loose(text: str) -> Any:
    """Parse JSON even if the model wrapped it in ``` fences or added chatter."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _same_model(name: str, want: str) -> bool:
    if ":" not in want:
        want_full = want + ":latest"
        return name in (want, want_full)
    return name == want


class OllamaClient:
    def __init__(self, base_url: str, model: str, *, embed_model: str = "embeddinggemma",
                 timeout: float = 600.0, num_ctx: int = 8192):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.embed_model = embed_model
        self.timeout = timeout
        self.num_ctx = num_ctx

    # Low-level ---------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None, *,
                 timeout: float | None = None, model: str | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            name = model or self.model
            if exc.code == 404 and "not found" in detail.lower():
                raise OllamaError(
                    f"Model '{name}' is not available in Ollama. Pull it with:\n"
                    f"    ollama pull {name}"
                ) from exc
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"Can't reach Ollama at {self.base_url} ({exc.reason}).\n"
                "Make sure Ollama is running (open the Ollama app, or run `ollama serve`)."
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Ollama took longer than {timeout or self.timeout:.0f}s to answer. "
                "The first call loads the model into memory and can be slow; try again, "
                "or use a smaller Gemma tag such as gemma4:e2b."
            ) from exc

    # Chat ------------------------------------------------------------------
    def chat(self, prompt: str, *, schema: dict | None = None, temperature: float = 0.0) -> str:
        # Gemma's chat template has no separate system role, so instructions go in the user turn.
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "keep_alive": "15m",
            "options": {"temperature": temperature, "num_ctx": self.num_ctx},
        }
        if schema is not None:
            body["format"] = schema
        data = self._request("POST", "/api/chat", body)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaError(f"Unexpected response from Ollama: {str(data)[:300]}") from exc

    def chat_json(self, prompt: str, schema: dict) -> Any:
        content = self.chat(prompt, schema=schema)
        try:
            return parse_json_loose(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Gemma did not return valid JSON: {content[:300]}") from exc

    # Embeddings --------------------------------------------------------------
    def embed(self, texts: list[str], *, batch: int = 32) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), batch):
            body = {"model": self.embed_model, "input": texts[i:i + batch], "keep_alive": "15m"}
            data = self._request("POST", "/api/embed", body, model=self.embed_model)
            got = data.get("embeddings")
            if not isinstance(got, list) or len(got) != len(texts[i:i + batch]):
                raise OllamaError(f"Unexpected embedding response from Ollama: {str(data)[:200]}")
            vectors.extend([[float(x) for x in v] for v in got])
        return vectors

    # Model discovery -----------------------------------------------------------
    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/tags", timeout=10)
        return [m.get("name", "") for m in data.get("models", [])]

    def has_model(self, name: str | None = None) -> bool:
        want = name or self.model
        return any(_same_model(n, want) for n in self.list_models())
