"""Conservative local lexical leak screen for blinded Twin writing evaluation.

Never returns owner text, matches or source identifiers. This is intentionally
not a semantic similarity model: passing does NOT prove held-out independence.
"""
from __future__ import annotations

import re
import unicodedata


def _words(text: str) -> tuple[str, ...]:
    """Normalize punctuation, whitespace and common Unicode compatibility forms."""
    return tuple(re.findall(
        r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def strongly_overlaps(first: str, second: str) -> bool:
    """Find full copies, long verbatim passages, and near-copy token patterns.

    Only substantial phrases trigger fuzzy checks, preventing short common
    expressions from blocking independent writing. Multiword n-gram tests
    remain inexpensive for large local samples and require no dependencies.
    """
    if not isinstance(first, str) or not isinstance(second, str):
        raise ValueError("Writing overlap inputs must be text")
    a, b = _words(first), _words(second)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter = a if len(a) <= len(b) else b
    longer = b if len(a) <= len(b) else a
    # Do not infer content leakage from small, commonplace phrases. The
    # exact whole-sample copy check above still detects short duplicates.
    if len(shorter) < 8 or len(" ".join(shorter)) < 48:
        return False

    # A long verbatim fragment within otherwise unrelated prose is not
    # independent evidence, even if it came from a 5000-word owner sample.
    chunks = {tuple(longer[i:i + 8]) for i in range(len(longer) - 7)}
    for offset in range(len(shorter) - 7):
        fragment = tuple(shorter[offset:offset + 8])
        if len(" ".join(fragment)) >= 48 and fragment in chunks:
            return True

    # Near copies with a handful of substitutions or moved punctuation.
    # Relative to the SHORTER sequence: a task quoting a large portion of
    # one passage must be screened even if the source is much longer.
    pairs_a = {a[i:i + 2] for i in range(len(a) - 1)}
    pairs_b = {b[i:i + 2] for i in range(len(b) - 1)}
    return (bool(pairs_a and pairs_b)
            and len(pairs_a & pairs_b) >= 5
            and len(pairs_a & pairs_b) / min(len(pairs_a), len(pairs_b)) >= 0.72)


