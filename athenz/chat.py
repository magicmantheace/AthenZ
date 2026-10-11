"""Local-only Ollama chat for AthenZ; no daemon, tool execution or data upload."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from .prompting import build_messages
from .learning import LearningStore
from .store import IdentityStore


class LocalModelError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, endpoint: str | None = None, model: str | None = None):
        self.endpoint = (endpoint or os.environ.get("ATHENZ_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("ATHENZ_MODEL", "qwen3.5:2b")
        parts = urlsplit(self.endpoint)
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "::1", "localhost"}
                or parts.username is not None or parts.password is not None or parts.path
                or parts.query or parts.fragment or parts.port is None):
            raise LocalModelError("Only an explicit HTTP loopback Ollama host:port is allowed")
        if not self.model.strip():
            raise LocalModelError("Model name is required")

    def generate(self, messages: list[dict], timeout: int = 180, json_mode: bool = False) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"num_ctx": 8192, "temperature": 0.35}}
        if json_mode:
            payload["format"] = "json"
        req = Request(self.endpoint + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(req, timeout=timeout) as response:
                data = json.load(response)
            content = data["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("non-text model reply")
            return content
        except (HTTPError, URLError, OSError, TimeoutError, KeyError, TypeError, ValueError) as exc:
            raise LocalModelError(f"Local Ollama request failed: {exc}") from exc


def answer(store: IdentityStore, model: OllamaClient, prompt: str,
           mode: str = "agent", recent: list[dict] | None = None) -> str:
    messages = build_messages(store, prompt, mode=mode)
    if recent:
        # Caller-supplied context remains untrusted and bounded to one session.
        valid = [{"role": r["role"], "content": r["content"][:4000]}
                 for r in recent[-10:] if r.get("role") in {"user", "assistant"}
                 and isinstance(r.get("content"), str)]
        messages[2:2] = valid
    return model.generate(messages)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Chat privately with local Ollama using approved AthenZ context")
    p.add_argument("--home", type=Path)
    p.add_argument("--mode", choices=["twin", "agent"], default="agent")
    p.add_argument("--model", default=None)
    p.add_argument("--session", default="default", help="Persistent session ID; stored locally")
    args = p.parse_args(argv)
    store = LearningStore(args.home)
    try:
        model = OllamaClient(model=args.model)
        print(f"AthenZ local {args.mode} chat (model: {model.model}). /exit to quit")
        history = store.conversation(args.session, args.mode, limit=10)
        while True:
            try:
                q = input("You> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if q in {"/exit", "/quit"}:
                break
            if not q:
                continue
            try:
                reply = answer(store, model, q, args.mode, history)
            except LocalModelError as error:
                print(f"Error: {error}")
                continue
            print(f"\nAthenZ> {reply}\n")
            # Only persist complete turns after successful inference.
            store.add_message(args.session, args.mode, "user", q)
            reply_id = store.add_message(args.session, args.mode, "assistant", reply)
            print(f"(reply ID {reply_id} — use 'athenz feedback {reply_id} up|down' to rate)")
            history = store.conversation(args.session, args.mode, limit=10)
    finally:
        store.close()


if __name__ == "__main__":
    main()
