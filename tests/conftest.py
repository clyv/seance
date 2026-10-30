import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from seance.config import Config

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

FAKE_QUOTE = "my grandmother once sailed to the moon on a banana leaf"


def _transcript_from_prompt(prompt: str) -> str:
    m = re.search(r'"""\n(.*)\n"""', prompt, re.DOTALL)
    return m.group(1) if m else ""


def fake_card(prompt: str) -> dict:
    text = _transcript_from_prompt(prompt)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 6]
    quotes = sentences[:2]
    moments = [{"heading": f"Moment {i + 1}", "quote": q} for i, q in enumerate(quotes)]
    moments.append({"heading": "Invented", "quote": FAKE_QUOTE})
    years = [{"when": y, "what": "something happened"} for y in sorted(set(re.findall(r"\b(19\d\d)\b", text)))]
    return {
        "title": "The house with the mango tree" if "Kottayam" in text else "A long journey",
        "summary": "A short summary. It has two sentences.",
        "people": [{"name": "Joseph", "relation": "brother"}] if "Joseph" in text else [],
        "places": ["Kottayam"] if "Kottayam" in text else ["Deira"] if "Deira" in text else [],
        "years": years,
        "moments": moments,
        "themes": ["family", "home"],
        "follow_up_questions": ["What happened to the house?"],
    }


def fake_answer(prompt: str) -> dict:
    m = re.search(r"\[P1\][^\n]*:\n([^\n]+)", prompt)
    if not m:
        return {"found": False, "answer": "Nothing about that.", "citations": []}
    words = m.group(1).split()
    quote = " ".join(words[:12])
    return {
        "found": True,
        "answer": "She talked about it.",
        "citations": [{"passage": "P1", "quote": quote}, {"passage": "P2", "quote": FAKE_QUOTE}],
    }


def fake_vector(text: str, dims: int = 32) -> list[float]:
    vec = [0.0] * dims
    for w in re.findall(r"[a-z]+", text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        vec[h % dims] += 1.0
    return vec


def respond(prompt: str, schema: dict) -> dict:
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if "moments" in props:
        return fake_card(prompt)
    if "citations" in props:
        return fake_answer(prompt)
    return {"title": "Merged title", "summary": "Merged summary of all the parts."}


class FakeLLM:
    def __init__(self, embed_ok: bool = True):
        self.prompts: list[str] = []
        self.embed_model = "embeddinggemma"
        self.embed_ok = embed_ok
        self.embed_calls = 0

    def chat_json(self, prompt, schema):
        self.prompts.append(prompt)
        return respond(prompt, schema)

    def embed(self, texts):
        self.embed_calls += 1
        return [fake_vector(t) for t in texts]

    def has_model(self, name=None):
        if name == "embeddinggemma":
            return self.embed_ok
        return True


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def cfg(tmp_path):
    c = Config(home=tmp_path / "Seance")
    c.ensure_dirs()
    return c


@pytest.fixture
def samples():
    return SAMPLES


def start_fake_ollama():
    """A tiny stand-in for the Ollama HTTP API. Returns (url, calls, server)."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            calls.append(("GET", self.path, None))
            if self.path == "/api/tags":
                self._send({"models": [{"name": "gemma4:e4b"}, {"name": "embeddinggemma:latest"}]})
            else:
                self._send({"error": "not found"}, 404)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(("POST", self.path, body))
            if self.path == "/api/chat":
                prompt = body["messages"][0]["content"]
                reply = respond(prompt, body.get("format") or {})
                self._send({"message": {"role": "assistant", "content": json.dumps(reply)}})
            elif self.path == "/api/embed":
                self._send({"embeddings": [fake_vector(t) for t in body["input"]]})
            else:
                self._send({"error": "not found"}, 404)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", calls, srv


@pytest.fixture
def fake_ollama():
    url, calls, srv = start_fake_ollama()
    yield url, calls
    srv.shutdown()
