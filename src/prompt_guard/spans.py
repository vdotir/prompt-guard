"""Span model shared by all detection layers.

Purpose:
    A Span marks one sensitive substring in the input text: where it starts,
    where it ends, and what kind it is (EMAIL, API_KEY, ...). Every layer
    (rules, NER, LLM) returns spans; resolve_overlaps() merges them into one
    clean, non-overlapping list before replacement.

Path in repo:
    src/prompt_guard/spans.py

Relations:
    - Produced by src/prompt_guard/rules.py (and later ner.py, llm.py).
    - Consumed by the vault / redaction step (later step).
    - Tested in tests/test_spans.py.

How to run:
    Library module, no entry point. Tests:
        pytest tests/test_spans.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass

KIND_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@dataclass(frozen=True, order=True)
class Span:
    """A half-open range [start, end) of the text with a kind label."""

    start: int
    end: int
    kind: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"invalid span range: {self.start}..{self.end}")
        if not KIND_RE.match(self.kind):
            raise ValueError(f"invalid span kind: {self.kind!r}")

    @property
    def length(self) -> int:
        return self.end - self.start

    def value(self, text: str) -> str:
        return text[self.start : self.end]


def normalize_kind(label: str, default: str = "SENSITIVE") -> str:
    """Turn any label ("api key", "Street-Address") into a kind like API_KEY."""
    kind = re.sub(r"[^A-Z0-9]+", "_", label.upper()).strip("_")
    if not kind or not kind[0].isalpha():
        return default
    return kind


def resolve_overlaps(spans: list[Span]) -> list[Span]:
    """Return spans sorted by position with overlaps removed.

    When two spans overlap, the longer one wins; on equal length, the one
    that comes first in the input list wins (so earlier, more specific
    rules beat later, generic ones).
    """
    ranked = sorted(enumerate(spans), key=lambda p: (-p[1].length, p[0]))
    chosen: list[Span] = []
    for _, span in ranked:
        if all(span.end <= c.start or span.start >= c.end for c in chosen):
            chosen.append(span)
    return sorted(chosen)
