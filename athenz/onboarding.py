"""Read-only, offline first-run guidance for AthenZ's local desktop.

This module intentionally has no profile, process, GPU or network access. It
never grants consent, provisions models, or starts a coding worker. Readiness
probes are separate, explicit actions in the Setup tab.
"""
from __future__ import annotations

import argparse
import json


STEPS = (
    ('Private profile', 'Your identity, chats, approvals and task state stay in the private AthenZ profile outside Git. Backups are plaintext unless protected separately.'),
    ('Local Ollama', 'Install Ollama and a supported model yourself, then use Probe Ollama to check the loopback connection. The probe does not send conversations.'),
    ('Try your Twin first', 'Chat opens in Twin Mode. Ask a question and use Preview Twin evidence to inspect approved context before sending; a match is not proof of your answer. Agent Mode remains an explicit alternative. Replies are generated only when you send a prompt.'),
    ('Review memory', 'Pending memories and training examples remain unapproved until you inspect the complete record and explicitly approve it.'),
    ('Supervised coding', 'Coding requires your trusted Git repository, named file scopes and approval of the exact patch SHA-256; the scheduler is off by default.'),
    ('Back up safely', 'Before substantial use, explicitly create and verify a private backup or selected-file bundle. Existing backups are unencrypted and excludes installed Ollama weights.'),
    ('Hardware testing', 'GPU readiness, Windows display scaling, CUDA training and WSL2 Docker are not certified by the CI build. Hardware probes require your action.'),
)


def guide() -> dict:
    """Return public instructions only; no external calls, paths or private content."""
    return {
        'schema': 1,
        'title': 'Getting started with AthenZ',
        'steps': [{'title': title, 'detail': detail, 'requires_owner_action': True}
                  for title, detail in STEPS],
        'grants_consent': False,
        'starts_background_work': False,
        'installs_models': False,
        'initiates_hardware_probe': False,
        'collects_private_data': False,
    }


def guide_text() -> str:
    data = guide()
    lines = [data['title'], '', 'LOCAL ONLY — nothing runs or probes automatically.', '']
    for index, step in enumerate(data['steps'], 1):
        lines.extend([f"{index}. {step['title']}", f"   {step['detail']}", ''])
    lines.append('Use the separate Setup controls to request readiness checks. No check grants AI permissions.')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Read-only offline AthenZ first-run guidance')
    parser.add_argument('--json', action='store_true', help='Machine-readable non-personal checklist')
    options = parser.parse_args(argv)
    print(json.dumps(guide(), indent=2) if options.json else guide_text())


if __name__ == '__main__':
    main()
