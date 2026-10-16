"""Tests for the Span model and overlap resolution.

Purpose:
    Check span validation, kind normalization and the "longest wins" rule.

Path in repo:
    tests/test_spans.py

Relations:
    - Tests src/prompt_guard/spans.py.

How to run:
    pytest tests/test_spans.py
"""

import pytest

from prompt_guard.spans import Span, normalize_kind, resolve_overlaps


def test_span_rejects_bad_range():
    with pytest.raises(ValueError):
        Span(5, 5, "EMAIL")
    with pytest.raises(ValueError):
        Span(-1, 3, "EMAIL")


def test_span_rejects_bad_kind():
    with pytest.raises(ValueError):
        Span(0, 3, "email")


def test_span_value():
    assert Span(4, 7, "X").value("abc def ghi") == "def"


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("api key", "API_KEY"),
        ("Street-Address", "STREET_ADDRESS"),
        ("", "SENSITIVE"),
        ("123", "SENSITIVE"),
    ],
)
def test_normalize_kind(label, kind):
    assert normalize_kind(label) == kind


def test_longest_span_wins():
    spans = [Span(0, 5, "A"), Span(2, 12, "B"), Span(20, 25, "C")]
    assert resolve_overlaps(spans) == [Span(2, 12, "B"), Span(20, 25, "C")]


def test_tie_goes_to_first():
    assert resolve_overlaps([Span(0, 5, "FIRST"), Span(0, 5, "SECOND")]) == [Span(0, 5, "FIRST")]


def test_touching_spans_both_kept():
    assert resolve_overlaps([Span(0, 3, "A"), Span(3, 6, "B")]) == [
        Span(0, 3, "A"),
        Span(3, 6, "B"),
    ]
