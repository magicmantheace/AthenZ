"""Preview-only chat export parsing; caller must explicitly choose to store samples."""
from __future__ import annotations
import json
from pathlib import Path
from .learning import LearningStore


def parse_chatgpt_export(path: Path, limit: int = 500) -> list[str]:
    if not 1 <= limit <= 10000 or path.stat().st_size > 250_000_000:
        raise ValueError('Invalid limit or oversized export')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError('Expected ChatGPT conversations.json list')
    samples = []
    for conversation in data:
        if not isinstance(conversation, dict):
            continue
        for node in (conversation.get('mapping') or {}).values():
            if not isinstance(node, dict):
                continue
            message = node.get('message') or {}
            if (message.get('author') or {}).get('role') != 'user':
                continue
            content = message.get('content') or {}
            if content.get('content_type') != 'text':
                continue
            text = '\n'.join(p for p in content.get('parts', []) if isinstance(p, str)).strip()
            if 35 <= len(text) <= 2200:
                samples.append((float(message.get('create_time') or 0), text))
    samples.sort(reverse=True)
    return list(dict.fromkeys(text for _, text in samples))[:limit]


def import_samples(store: LearningStore, samples: list[str], source: str, source_ref: str) -> int:
    if not source.strip() or not source_ref.strip():
        raise ValueError('Import source and identifier required for targeted purge')
    old = {row['text'] for row in store.list_items('writing_samples', limit=100000)}
    count = 0
    for item in samples:
        if item not in old:
            store.add_sample(item, source=source, source_ref=source_ref)
            old.add(item)
            count += 1
    return count
