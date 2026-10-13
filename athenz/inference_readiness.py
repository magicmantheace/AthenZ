"""Owner-confirmed, synthetic Ollama response probe with no AthenZ profile access.

The request uses a fixed public prompt and the existing proxy-disabled,
redirect-refusing loopback transport. This is a functional readiness hint,
not GPU, WSL2, training or model-quality certification.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from urllib.request import Request


_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z')
_PROMPT = 'Reply with exactly the word READY.'


class InferenceProbeError(ValueError):
    """Missing permission or malformed requested local probe."""


def check_inference(*, model: str, confirmed: bool = False, timeout_seconds: int = 20) -> dict:
    """Send one small synthetic inference request only with explicit consent.

    No implicit model pull, no training, no conversation history, no identity
    store, no file writes and no raw reply or error content in the result.
    """
    if not confirmed:
        raise InferenceProbeError('Explicit --confirm required before starting model inference')
    if type(model) is not str or not _MODEL.fullmatch(model):
        raise InferenceProbeError('Choose a short local Ollama model tag')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 60:
        raise InferenceProbeError('Inference timeout must be 1..60 seconds')

    # Import only after confirmation to rule out hidden initialization work.
    from .chat import OllamaClient, safe_local_open
    # OllamaClient's strict loopback parsing forbids redirects/proxies/credentials.
    client = OllamaClient(model=model)
    base = {'schema': 1, 'status': 'local-model-unavailable', 'inference_observed': False,
            'training_validated': False, 'gpu_validated': False,
            'quality_validated': False, 'personal_data_collected': False,
            'conversation_saved': False, 'reply_returned': False,
            'prompts_are_synthetic': True, 'request_scope': 'loopback-only',
            'model_downloaded': False, 'background_work_enabled': False,
            'synthetic_instruction_followed': False}
    payload = {
        'model': client.model,
        'messages': [{'role': 'user', 'content': _PROMPT}],
        'stream': False,
        'options': {'num_ctx': 256, 'num_predict': 12, 'temperature': 0, 'seed': 0},
    }
    req = Request(client.endpoint + '/api/chat', data=json.dumps(payload).encode('utf-8'),
                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        started = time.monotonic()
        with safe_local_open(req, timeout=timeout_seconds) as response:
            # Enforce small response budget; never print or persist the bytes.
            raw = response.read(16385)
        if len(raw) > 16384:
            return {**base, 'status': 'invalid-local-reply'}
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {**base, 'status': 'invalid-local-reply'}
        if not isinstance(data, dict) or data.get('error') or data.get('done') is False:
            return {**base, 'status': 'invalid-local-reply'}
        message = data.get('message')
        content = message.get('content') if isinstance(message, dict) else None
        if (not isinstance(content, str) or not 1 <= len(content.strip()) <= 4000
                or (message.get('role') not in ('assistant', None))):
            return {**base, 'status': 'invalid-local-reply'}
        # Instruction-following is an extra descriptive signal, NOT a quality
        # or identity certification. Never expose the raw local model reply.
        followed = content.strip() == 'READY'
        elapsed = max(0.0, time.monotonic() - started)
    except Exception:
        # Exceptions can contain model names, response bodies, local paths and
        # other diagnostics. No raw error reaches stdout or the caller.
        return base
    return {**base, 'status': 'local-text-generated', 'inference_observed': True,
            'synthetic_instruction_followed': followed,
            'elapsed_bucket': ('under-5s' if elapsed < 5 else '5-20s' if elapsed < 20 else 'over-20s')}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Explicit synthetic loopback Ollama inference readiness check')
    parser.add_argument('--model', required=True, help='Locally installed model tag (no downloads)')
    parser.add_argument('--confirm', action='store_true', help='Authorize one local model inference request')
    parser.add_argument('--timeout', type=int, default=20, help='Response timeout, 1..60 seconds')
    args = parser.parse_args(argv)
    report = check_inference(model=args.model, confirmed=args.confirm, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2))
    if not report['inference_observed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
