"""Tests for layer 2 (GLiNER NER).

Purpose:
    Check chunking, offset mapping, label-to-kind mapping, trimming, the
    allowlist and placeholder protection with a fake model, so no download
    or torch install is needed. One optional test runs the real model; it is
    skipped unless PROMPT_GUARD_NER_TEST=1 is set (it downloads the model on
    the first run).

Path in repo:
    tests/test_ner.py

Relations:
    - Tests src/prompt_guard/ner.py and its use in src/prompt_guard/pipeline.py.

How to run:
    pytest tests/test_ner.py
    PROMPT_GUARD_NER_TEST=1 pytest tests/test_ner.py   # also the real model
"""

import os
import re

import pytest

from prompt_guard.config import Config, LayersConfig, NerConfig
from prompt_guard.ner import NerDetector, chunks, label_kind
from prompt_guard.pipeline import detect_all


class FakeModel:
    """Finds fixed words; records every chunk it was given."""

    def __init__(self, words):
        self.words = words  # {"Jane Doe": "name", ...}
        self.calls = []

    def predict_entities(self, text, labels, threshold=0.5):
        self.calls.append(text)
        found = []
        for word, label in self.words.items():
            for m in re.finditer(re.escape(word), text):
                found.append({"start": m.start(), "end": m.end(), "label": label, "score": 0.9})
        return found


def found(text, words, cfg=None, allowlist=()):
    det = NerDetector(cfg or NerConfig(), allowlist, model=FakeModel(words))
    return [(s.kind, s.value(text)) for s in det.detect(text)]


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("name", "PERSON"),
        ("location street", "ADDRESS"),
        ("organization", "ORG"),
        ("username", "USERNAME"),
        ("vehicle id", "VEHICLE_ID"),
    ],
)
def test_label_kind(label, kind):
    assert label_kind(label) == kind


def test_finds_entities_with_kinds():
    text = "Ask Jane Doe at Example Corp about 12 Example Road."
    words = {
        "Jane Doe": "name",
        "Example Corp": "organization",
        "12 Example Road": "location street",
    }
    assert found(text, words) == [
        ("PERSON", "Jane Doe"),
        ("ORG", "Example Corp"),
        ("ADDRESS", "12 Example Road"),
    ]


def test_trims_punctuation_and_spaces():
    text = "hello (Jane Doe), bye"
    assert found(text, {"(Jane Doe),": "name"}) == [("PERSON", "Jane Doe")]


def test_allowlist_and_short_values_skipped():
    text = "by J and by Support Team"
    assert (
        found(text, {"J": "name", "Support Team": "organization"}, allowlist=("support team",))
        == []
    )


def test_placeholders_are_never_entities():
    text = "Send to [[PERSON_1]] now"
    assert found(text, {"[[PERSON_1]]": "name", "PERSON_1": "name"}) == []


def test_chunks_cover_text_and_respect_size():
    text = "\n".join(f"line {i} word word word" for i in range(50))
    pieces = list(chunks(text, 20))
    assert all(len(p.split()) <= 20 for _, p in pieces)
    assert [w for _, p in pieces for w in p.split()] == text.split()
    for offset, piece in pieces:
        assert text[offset : offset + len(piece)] == piece


def test_chunks_prefer_line_breaks():
    text = "a b c d\ne f g h i j"
    assert [p for _, p in chunks(text, 6)] == ["a b c d", "e f g h i j"]


def test_offsets_mapped_from_later_chunks():
    filler = " ".join(["word"] * 30)
    text = f"{filler}\n{filler}\nContact Jane Doe today."
    model = FakeModel({"Jane Doe": "name"})
    det = NerDetector(NerConfig(max_chunk_words=25), model=model)
    spans = det.detect(text)
    assert len(model.calls) > 1
    assert [(s.kind, s.value(text)) for s in spans] == [("PERSON", "Jane Doe")]


def test_empty_text_does_not_call_model():
    model = FakeModel({})
    assert NerDetector(model=model).detect("  \n ") == []
    assert model.calls == []


def test_pipeline_merges_rules_and_ner():
    text = "Jane Doe <jane@example.org>"
    cfg = Config(layers=LayersConfig(ner=True))
    det = NerDetector(cfg.ner, model=FakeModel({"Jane Doe": "name"}))
    spans = detect_all(text, cfg, ner_detector=det).spans
    assert [(s.kind, s.value(text)) for s in spans] == [
        ("PERSON", "Jane Doe"),
        ("EMAIL", "jane@example.org"),
    ]


@pytest.mark.skipif(
    os.environ.get("PROMPT_GUARD_NER_TEST") != "1",
    reason="set PROMPT_GUARD_NER_TEST=1 to run the real GLiNER model",
)
def test_real_model_finds_a_name():
    pytest.importorskip("gliner")
    text = "Please forward the invoice to Margaret Thompson in accounting."
    kinds = {s.kind for s in NerDetector().detect(text)}
    assert "PERSON" in kinds


def test_known_loader_warnings_are_silenced(monkeypatch):
    import sys
    import types
    import warnings

    from prompt_guard import ner as ner_module

    class FakeGLiNER:
        @staticmethod
        def from_pretrained(model, **kwargs):
            warnings.warn(
                "`torch.jit.script` is not supported in Python 3.14+ and may break.",
                FutureWarning,
                stacklevel=2,
            )
            warnings.warn(
                "The `resume_download` argument is deprecated and ignored.",
                UserWarning,
                stacklevel=2,
            )
            warnings.warn("something else", UserWarning, stacklevel=2)
            return "model"

    monkeypatch.setitem(sys.modules, "gliner", types.SimpleNamespace(GLiNER=FakeGLiNER))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert ner_module.load_model(NerConfig()) == "model"
    assert [str(w.message) for w in caught] == ["something else"]


def test_hostname_rule_beats_ner_pieces():
    text = "Deploy failed on build-07.corp-internal.lan, ask Margaret."
    cfg = Config(layers=LayersConfig(ner=True))
    model = FakeModel({"build-07": "username", "corp-internal": "organization", "Margaret": "name"})
    det = NerDetector(cfg.ner, model=model)
    spans = detect_all(text, cfg, ner_detector=det).spans
    assert [(s.kind, s.value(text)) for s in spans] == [
        ("HOSTNAME", "build-07.corp-internal.lan"),
        ("PERSON", "Margaret"),
    ]
