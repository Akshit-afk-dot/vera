"""Claim checker: every number in model-written text must match a number computed by code.

A number written with d decimals matches a fact if they agree to within half a unit in the last written digit,
or within 0.5% relative. Percentages also match fractions (0.125 <-> 12.5%). Channel IDs are not numbers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable

NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)?%?")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])")


def facts_from(obj, out: set[float] | None = None) -> set[float]:
    """Every number anywhere in a nested dict/list (results, summary, evidence)."""
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)) and math.isfinite(obj):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            facts_from(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            facts_from(v, out)
    return out


def with_percentages(facts: set[float], totals: Iterable[int]) -> set[float]:
    """Add the shares a writer may legitimately state: count/total as %, and fractions as %."""
    extra = set(facts)
    for t in totals:
        if t:
            extra |= {round(100 * f / t, 6) for f in facts if 0 <= f <= t and float(f).is_integer()}
    extra |= {round(100 * f, 6) for f in facts if 0 < abs(f) < 1.5}
    return extra


def _strip_ids(sentence: str, channel_ids: Iterable[str]) -> str:
    for cid in sorted(channel_ids, key=len, reverse=True):
        sentence = re.sub(rf"(?<![\w]){re.escape(cid)}(?![\w])", " ", sentence)
    return sentence


def bad_numbers(sentence: str, facts: set[float], channel_ids: Iterable[str]) -> list[str]:
    text = _strip_ids(sentence, channel_ids)
    bad = []
    for m in NUM.finditer(text):
        raw = m.group(0)
        s = raw.rstrip("%").replace(",", ".")
        try:
            x = float(s)
        except ValueError:
            continue
        decimals = len(s.split(".")[1]) if "." in s else 0
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        if not any(abs(x - f) <= tol or (f and abs(x - f) / abs(f) <= 0.005) for f in facts):
            bad.append(raw)
    return bad


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text.strip()) if s.strip()]
