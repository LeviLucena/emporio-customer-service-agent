"""Interactive CLI: python -m emporio_agent [--session NAME] [--today YYYY-MM-DD] [-v]"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from .agent import Agent
from .llm import LLMError, OllamaClient
from .tools import STORE_TZ, Clock, Toolbox


def parse_today(value: str | None) -> datetime | None:
    """'2026-02-20' -> that day at 10:00 (business hours); '2026-02-20T15:30' is kept as given."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if "T" not in value and " " not in value:
        dt = dt.replace(hour=10)
    return dt.replace(tzinfo=STORE_TZ)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="emporio_agent", description="Empório da Música - assistente virtual (CLI)")
    ap.add_argument("--session", help="session name; history is persisted in .sessions/<name>.json")
    ap.add_argument("--model", help="Ollama model (default: $OLLAMA_MODEL or gpt-oss:120b-cloud)")
    ap.add_argument("--today", help="pin 'today' (YYYY-MM-DD[THH:MM]); the dataset ends in March 2026")
    ap.add_argument("-v", "--verbose", action="store_true", help="print tool calls")
    args = ap.parse_args(argv)

    session = Path(".sessions") / f"{args.session}.json" if args.session else None
    agent = Agent(llm=OllamaClient(model=args.model), toolbox=Toolbox(clock=Clock(parse_today(args.today))),
                  session_file=session, verbose=args.verbose)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("Empório da Música - atendimento (digite /sair para encerrar, /novo para reiniciar)\n")
    while True:
        try:
            text = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"/sair", "/exit", "/quit"}:
            return 0
        if text.lower() in {"/novo", "/reset"}:
            agent.reset()
            print("(conversa reiniciada)\n")
            continue
        try:
            print(f"\nTom: {agent.send(text)}\n")
        except LLMError as exc:
            print(f"\n[erro] {exc}\n")
