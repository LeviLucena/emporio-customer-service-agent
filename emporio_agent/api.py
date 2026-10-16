"""HTTP API used by the web chat UI (stdlib only).

    python -m emporio_agent.api --port 8000 [--today 2026-02-20] [--model NAME]

Endpoints
    GET    /health            -> {"status": "ok", "sessoes": N}
    POST   /chat              {"message", "session_id"?} -> {"session_id", "reply", "tools_used": [...]}
    DELETE /chat/{session_id} -> {"ok": true}

Sessions live in memory (one Agent per session_id); production would use Redis/Postgres with a TTL.
The JSON field names (`sessoes`, `ferramenta`, `argumentos`) are kept for UI compatibility.
"""
from __future__ import annotations

import argparse
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent import Agent
from .cli import parse_today
from .llm import LLMError, OllamaClient
from .tools import Clock, Toolbox

SESSIONS: dict[str, Agent] = {}
_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_LOCK = threading.Lock()
CONFIG: dict = {"model": None, "today": None}


def _get_session(session_id: str | None) -> tuple[str, Agent, threading.Lock]:
    with _REGISTRY_LOCK:
        sid = session_id or str(uuid.uuid4())
        if sid not in SESSIONS:
            SESSIONS[sid] = Agent(llm=OllamaClient(model=CONFIG["model"]),
                                  toolbox=Toolbox(clock=Clock(CONFIG["today"])))
            _LOCKS[sid] = threading.Lock()
        return sid, SESSIONS[sid], _LOCKS[sid]


class Handler(BaseHTTPRequestHandler):
    server_version = "EmporioAgent/1.0"

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")  # demo UI runs on another port
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # CORS preflight
        self._send(204, {})

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"status": "ok", "sessoes": len(SESSIONS)})
        else:
            self._send(404, {"detail": "not found"})

    def do_DELETE(self) -> None:
        if self.path.startswith("/chat/"):
            with _REGISTRY_LOCK:
                SESSIONS.pop(self.path.split("/", 2)[2], None)
            self._send(200, {"ok": True})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self) -> None:
        if self.path != "/chat":
            return self._send(404, {"detail": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(length) or b"{}")
            message = str(req.get("message", "")).strip()
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"detail": "invalid JSON body"})
        if not message:
            return self._send(400, {"detail": "empty message"})
        sid, agent, lock = _get_session(req.get("session_id"))
        try:
            with lock:  # one in-flight turn per conversation
                reply = agent.send(message)
                tools = list(agent.last_tools_used)
        except LLMError as exc:
            return self._send(502, {"detail": f"model unavailable: {exc}"})
        self._send(200, {"session_id": sid, "reply": reply, "tools_used": tools})

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        print(f"[api] {self.address_string()} {fmt % args}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Empório da Música agent HTTP API")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--model", help="Ollama model (default: $OLLAMA_MODEL or gpt-oss:120b-cloud)")
    ap.add_argument("--today", help="pin 'today' (YYYY-MM-DD[THH:MM]); the dataset ends in March 2026")
    args = ap.parse_args(argv)
    CONFIG.update(model=args.model, today=parse_today(args.today))
    print(f"Agent API on http://{args.host}:{args.port}  (GET /health, POST /chat)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
