"""Local-only Ollama chat for AthenZ; no daemon, tool execution or data upload."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from .prompting import build_messages
from .experience import ExperienceStore
from .store import IdentityStore


class LocalModelError(RuntimeError):
    pass


# Bound all untrusted loopback HTTP responses before parsing or retaining them.
# This is a generous limit for ordinary text JSON, not a token-generation cap.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REPLY_CHARS = 128 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalModelError('Local Ollama endpoint redirected; refusing external request')


def safe_local_open(req, timeout: int):
    # urllib otherwise inherits HTTP(S)_PROXY and follows redirects. Never send
    # private prompts through a proxy or to an endpoint other than loopback.
    return build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=timeout)


class OllamaClient:
    def __init__(self, endpoint: str | None = None, model: str | None = None):
        self.endpoint = (endpoint or os.environ.get("ATHENZ_OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("ATHENZ_MODEL", "qwen3.5:2b")
        try:
            parts = urlsplit(self.endpoint)
            valid = (parts.scheme == "http" and
                     parts.hostname in {"127.0.0.1", "::1", "localhost"} and
                     parts.username is None and parts.password is None and
                     not parts.path and not parts.query and not parts.fragment and
                     parts.port is not None and 1 <= parts.port <= 65535)
        except ValueError as exc:
            raise LocalModelError("Invalid local Ollama endpoint") from exc
        if not valid:
            raise LocalModelError("Only an explicit HTTP loopback Ollama host:port is allowed")
        if not self.model.strip():
            raise LocalModelError("Model name is required")

    def generate(self, messages: list[dict], timeout: int = 180, json_mode: bool = False,
                 temperature: float = 0.35, seed: int | None = None) -> str:
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "options": {"num_ctx": 8192, "temperature": temperature}}
        if seed is not None:
            payload["options"]["seed"] = int(seed)
        if json_mode:
            payload["format"] = "json"
        req = Request(self.endpoint + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            with safe_local_open(req, timeout=timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("oversized local JSON response")
            data = json.loads(raw)
            content = data["message"]["content"]
            if (not isinstance(content, str) or not content.strip() or
                    len(content) > MAX_REPLY_CHARS):
                raise ValueError("invalid local text reply")
            return content
        except (HTTPError, URLError, OSError, TimeoutError, KeyError, TypeError,
                ValueError, UnicodeError, json.JSONDecodeError) as exc:
            # Neither HTTP error bodies nor exception messages are safe to
            # expose: a loopback service may reflect private prompt content.
            raise LocalModelError("Local Ollama inference failed or returned an invalid reply") from None


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
    store = ExperienceStore(args.home)
    try:
        from .runtime import checked_active_tag, RoutingError
        selected = checked_active_tag(store) if args.model is None else None
        model = OllamaClient(model=args.model or selected)
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
                if args.model is None and checked_active_tag(store) != selected:
                    raise RoutingError('Active model routing changed; restart the session')
                reply = answer(store, model, q, args.mode, history)
                # A tag, approval or runtime preference can change while a
                # slow local generation is in flight. Never save its reply
                # after revocation or re-routing, including None -> candidate.
                if args.model is None and checked_active_tag(store) != selected:
                    raise RoutingError('Active model routing changed during inference; reply discarded')
            except (LocalModelError, RoutingError) as error:
                print(f"Error: {error}")
                continue
            # Save an entire turn in ONE transaction. A failed assistant
            # insert must not leave a user message without a corresponding
            # reply (the desktop already uses this atomic-write contract).
            from .store import utc_now
            try:
                with store.db:
                    store.db.execute('''INSERT INTO messages(session,mode,role,content,created_at)
                        VALUES (?,?,?,?,?)''', (args.session, args.mode, 'user', q, utc_now()))
                    saved = store.db.execute('''INSERT INTO messages(session,mode,role,content,created_at)
                        VALUES (?,?,?,?,?)''', (args.session, args.mode, 'assistant', reply, utc_now()))
            except sqlite3.DatabaseError:
                # Roll back the complete turn and never expose raw SQL errors
                # or confidential rows to the terminal or log.
                print('Error: Could not save complete conversation turn')
                continue
            reply_id = int(saved.lastrowid)
            print(f"\nAthenZ> {reply}\n")
            print(f"(reply ID {reply_id} — use 'athenz feedback {reply_id} up|down' to rate)")
            history = store.conversation(args.session, args.mode, limit=10)
    finally:
        store.close()


if __name__ == "__main__":
    main()
