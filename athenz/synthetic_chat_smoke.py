"""Explicit disposable-profile Twin/Agent end-to-end Ollama smoke.

This uses PUBLIC SYNTHETIC reference data in a disposable OS temp folder and
the exact desktop chat/service persistence path. No default owner home is read,
no user chat is sent to Ollama, and no weights are downloaded or trained.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_SESSION = "synthetic-readiness"
_OWNER_PROMPT = "In a fictional software review, why check changes before release?"
_REFERENCE = "In fictional software projects, I prefer a review before release."
_AGENT_PROMPT = "Give one brief suggestion for reviewing a fictional code change."


class SyntheticChatSmokeError(ValueError):
    """The owner has not authorized a bounded synthetic model check."""


def check_synthetic_chat(*, model: str, confirmed: bool = False) -> dict:
    """Exercise Twin and Agent via DesktopService with two local replies.

    A success is evidence of local request/response and mode-separated
    persistence, NOT a user-Twin fidelity, GPU, performance or training score.
    Sanitized output never contains model text, tag, paths or prompt content.
    """
    if confirmed is not True:
        raise SyntheticChatSmokeError(
            "Explicit --confirm is required for two local model inferences")
    if (type(model) is not str or _MODEL.fullmatch(model) is None
            or "://" in model or "//" in model):
        raise SyntheticChatSmokeError("Choose one short installed Ollama model tag")
    report = {
        "schema": 1,
        "kind": "disposable-synthetic-twin-agent-smoke",
        "status": "local-smoke-unavailable",
        "twin_reply_saved": False,
        "agent_reply_saved": False,
        "mode_isolation_verified": False,
        "synthetic_approved_context_verified": False,
        "owner_profile_opened": False,
        "owner_data_sent": False,
        "prompts_synthetic": True,
        "temporary_profile_removed": False,
        "local_model_downloaded": False,
        "training_performed": False,
        "gpu_validated": False,
        "real_twin_fidelity_validated": False,
        "inference_calls_attempted": 0,
    }
    # Import after consent; no default-profile resolution is performed.
    from .desktop import DesktopService
    from .experience import ExperienceStore
    from .prompting import build_messages

    try:
        with tempfile.TemporaryDirectory(prefix="athenz-synthetic-chat-") as folder:
            home = Path(folder) / "private"
            store = ExperienceStore(home)
            try:
                store.propose(
                    "preference", _REFERENCE, source="synthetic:local-smoke",
                    approved=True)
                # Ensure the real runtime prompt builder retrieves synthetic
                # reviewed evidence and does not invent owner source material.
                twin = build_messages(store, _OWNER_PROMPT, mode="twin")
                agent = build_messages(store, _AGENT_PROMPT, mode="agent")
                if (_REFERENCE not in twin[1]["content"]
                        or _REFERENCE not in agent[1]["content"]):
                    return {**report, "status": "synthetic-prompt-check-failed"}
            finally:
                store.close()

            report["synthetic_approved_context_verified"] = True
            service = DesktopService(home)
            for mode, prompt in (("twin", _OWNER_PROMPT),
                                 ("agent", _AGENT_PROMPT)):
                report["inference_calls_attempted"] += 1
                result = service.send(_SESSION, mode, prompt, model=model)
                history = service.history(_SESSION, mode)
                if (not isinstance(result.get("reply"), str)
                        or not result["reply"].strip() or len(history) != 2
                        or [row["role"] for row in history] != ["user", "assistant"]
                        or history[0]["content"] != prompt
                        or history[1]["content"] != result["reply"]
                        or history[1]["id"] != result["reply_id"]):
                    return {**report, "status": "synthetic-session-check-failed"}
                report[mode + "_reply_saved"] = True

            twin_history = service.history(_SESSION, "twin")
            agent_history = service.history(_SESSION, "agent")
            report["mode_isolation_verified"] = (
                len(twin_history) == 2 and len(agent_history) == 2
                and twin_history[0]["content"] == _OWNER_PROMPT
                and agent_history[0]["content"] == _AGENT_PROMPT
                and twin_history[0]["id"] != agent_history[0]["id"]
                and twin_history[1]["id"] != agent_history[1]["id"]
            )
            if report["mode_isolation_verified"]:
                report["status"] = "synthetic-chat-roundtrip-observed"
            else:
                report["status"] = "synthetic-session-check-failed"
        # The context manager has completed without reporting a failed
        # teardown. Do not claim cleanup happened on exception paths.
        report["temporary_profile_removed"] = True
    except Exception:
        # Model/library errors and OS paths could include private identifiers;
        # deliberately never return raw exception details.
        return {**report, "status": "local-smoke-unavailable"}
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Explicit local Twin/Agent smoke on synthetic disposable data")
    parser.add_argument("--model", required=True, help="Installed local Ollama tag")
    parser.add_argument("--confirm", action="store_true",
                        help="Authorize exactly two local inference requests")
    args = parser.parse_args(argv)
    result = check_synthetic_chat(model=args.model, confirmed=args.confirm)
    print(json.dumps(result, sort_keys=True, indent=2))
    if result["status"] != "synthetic-chat-roundtrip-observed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
