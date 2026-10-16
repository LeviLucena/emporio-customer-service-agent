"""Function-calling agent loop with persisted conversation history."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .llm import OllamaClient
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, Toolbox

MAX_TOOL_ROUNDS = 6
FALLBACK_REPLY = ("Desculpe, tive um problema para concluir essa consulta agora. "
                  "Pode repetir ou, se preferir, falar com a equipe pelo WhatsApp (67) 3321-4500?")


@dataclass
class Agent:
    llm: OllamaClient = field(default_factory=OllamaClient)
    toolbox: Toolbox = field(default_factory=Toolbox)
    session_file: Path | None = None
    verbose: bool = False
    messages: list[dict] = field(default_factory=list)
    last_tools_used: list[dict] = field(default_factory=list)  # tool calls of the latest turn (for UIs)

    def __post_init__(self) -> None:
        if self.session_file and Path(self.session_file).exists():
            self.messages = json.loads(Path(self.session_file).read_text(encoding="utf-8"))
        if not self.messages:
            self.reset()

    # The system prompt is rebuilt on every turn so 'today' is always current.
    def _system(self) -> dict:
        return {"role": "system", "content": build_system_prompt(self.toolbox.clock.today().isoformat())}

    def reset(self) -> None:
        self.messages = [self._system()]
        self._save()

    def _save(self) -> None:
        if self.session_file:
            p = Path(self.session_file)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.messages, ensure_ascii=False, indent=1), encoding="utf-8")

    def send(self, user_text: str) -> str:
        self.messages[0] = self._system()
        self.last_tools_used = []
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(MAX_TOOL_ROUNDS):
            msg = self.llm.chat(self.messages, TOOL_SCHEMAS)
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content", "")}
            if calls:
                entry["tool_calls"] = calls
            self.messages.append(entry)
            if not calls:
                self._save()
                return (msg.get("content") or "").strip() or FALLBACK_REPLY
            for call in calls:  # parallel calls are answered in order
                fn = call["function"]
                result = self.toolbox.call(fn["name"], fn.get("arguments"))
                args = fn.get("arguments")
                self.last_tools_used.append({"ferramenta": fn["name"], "argumentos": args if isinstance(args, dict) else {}})
                if self.verbose:
                    print(f"  [tool] {fn['name']}({json.dumps(fn.get('arguments'), ensure_ascii=False)})")
                self.messages.append({"role": "tool", "tool_name": fn["name"], "content": result})
        self._save()
        return FALLBACK_REPLY
