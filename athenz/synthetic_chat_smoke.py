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
_CORRECTION = "In fictional software projects, I prefer staged review before release."
_AGENT_PROMPT = "Give one brief suggestion for reviewing a fictional code change."


class SyntheticChatSmokeError(ValueError):
    """The owner has not authorized a bounded synthetic model check."""


def check_synthetic_chat(*, model: str, confirmed: bool = False,
                         twin_lifecycle: bool = False) -> dict:
    """Exercise Twin and Agent via DesktopService, optionally five inferences.

    A success is evidence of local request/response and mode-separated
    persistence, NOT a user-Twin fidelity, GPU, performance or training score.
    Sanitized output never contains model text, tag, paths or prompt content.
    """
    if confirmed is not True or type(twin_lifecycle) is not bool:
        raise SyntheticChatSmokeError(
            "Explicit --confirm and a valid lifecycle option are required")
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
    if twin_lifecycle:
        report.update({
            "twin_lifecycle_requested": True,
            "session_reopened": False,
            "pending_correction_excluded_from_approved_context": False,
            "approved_correction_in_approved_context": False,
            "revoked_memory_excluded_from_approved_context": False,
            "lifecycle_conversation_persisted": False,
            "model_answer_quality_measured": False,
        })
    # Import after consent; no default-profile resolution is performed.
    from .desktop import DesktopService
    from .experience import ExperienceStore
    from .prompting import build_messages

    try:
        with tempfile.TemporaryDirectory(prefix="athenz-synthetic-chat-") as folder:
            home = Path(folder) / "private"
            store = ExperienceStore(home)
            try:
                memory_id = store.propose(
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
            if twin_lifecycle and report["mode_isolation_verified"]:
                # Opt-in: demonstrate an actual model chat across fresh
                # DesktopService instances and review-gated memory states.
                # Profile checks validate prompt references, not model honesty.
                reopened = DesktopService(home)
                report["session_reopened"] = len(
                    reopened.history(_SESSION, "twin")) == 2

                detail = reopened.approved_memory_detail(memory_id)
                reopened.manage_approved_memory(
                    memory_id, "revise", review_sha256=detail["review_sha256"],
                    confirmed=True, new_text=_CORRECTION,
                    reason="Owner-reviewed synthetic smoke correction")

                def approved_context() -> str:
                    private = ExperienceStore(home)
                    try:
                        return build_messages(
                            private, _OWNER_PROMPT, mode="twin")[1]["content"]
                    finally:
                        private.close()

                pending_profile = approved_context()
                report["pending_correction_excluded_from_approved_context"] = (
                    _REFERENCE not in pending_profile and
                    _CORRECTION not in pending_profile)
                if not report["pending_correction_excluded_from_approved_context"]:
                    return {**report, "status": "synthetic-lifecycle-check-failed"}
                report["inference_calls_attempted"] += 1
                reopened.send(_SESSION, "twin", _OWNER_PROMPT, model=model)

                pending = reopened.review_detail("identity", memory_id)
                if not reopened.review(
                        "identity", memory_id, "approved",
                        review_sha256=pending["review_sha256"]):
                    return {**report, "status": "synthetic-lifecycle-check-failed"}
                approved_profile = approved_context()
                report["approved_correction_in_approved_context"] = (
                    _CORRECTION in approved_profile and
                    _REFERENCE not in approved_profile)
                if not report["approved_correction_in_approved_context"]:
                    return {**report, "status": "synthetic-lifecycle-check-failed"}
                report["inference_calls_attempted"] += 1
                DesktopService(home).send(
                    _SESSION, "twin", _OWNER_PROMPT, model=model)

                approved = reopened.approved_memory_detail(memory_id)
                reopened.manage_approved_memory(
                    memory_id, "revoke",
                    review_sha256=approved["review_sha256"], confirmed=True)
                revoked_profile = approved_context()
                report["revoked_memory_excluded_from_approved_context"] = (
                    _CORRECTION not in revoked_profile and
                    _REFERENCE not in revoked_profile)
                if not report["revoked_memory_excluded_from_approved_context"]:
                    return {**report, "status": "synthetic-lifecycle-check-failed"}
                report["inference_calls_attempted"] += 1
                DesktopService(home).send(
                    _SESSION, "twin", _OWNER_PROMPT, model=model)

                report["lifecycle_conversation_persisted"] = (
                    len(DesktopService(home).history(_SESSION, "twin")) == 8
                    and len(DesktopService(home).history(_SESSION, "agent")) == 2)
                passed = all((
                    report["session_reopened"],
                    report["pending_correction_excluded_from_approved_context"],
                    report["approved_correction_in_approved_context"],
                    report["revoked_memory_excluded_from_approved_context"],
                    report["lifecycle_conversation_persisted"],
                ))
                report["status"] = (
                    "synthetic-twin-lifecycle-observed" if passed
                    else "synthetic-lifecycle-check-failed")
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
                        help="Authorize local inference requests (two, or five with lifecycle)")
    parser.add_argument("--twin-lifecycle", action="store_true",
                        help="Also check Twin correction, approval, revocation and restart")
    args = parser.parse_args(argv)
    result = check_synthetic_chat(
        model=args.model, confirmed=args.confirm,
        twin_lifecycle=args.twin_lifecycle)
    print(json.dumps(result, sort_keys=True, indent=2))
    expected = ("synthetic-twin-lifecycle-observed" if args.twin_lifecycle
                else "synthetic-chat-roundtrip-observed")
    if result["status"] != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
