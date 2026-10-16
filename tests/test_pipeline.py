"""Tests for the detection pipeline.

Purpose:
    Check that enabled layers run, disabled ones do not, that a layer not
    yet available (llm) gives a note, and that a missing NER install fails
    loudly instead of being skipped.

Path in repo:
    tests/test_pipeline.py

Relations:
    - Tests src/prompt_guard/pipeline.py.

How to run:
    pytest tests/test_pipeline.py
"""

import pytest

from prompt_guard import ner
from prompt_guard.config import Config, LayersConfig
from prompt_guard.pipeline import detect_all

TEXT = "mail jane@example.org"


def test_rules_layer_runs_by_default():
    d = detect_all(TEXT, Config())
    assert [s.kind for s in d.spans] == ["EMAIL"]
    assert d.notes == []


def test_rules_disabled_gives_warning():
    d = detect_all(TEXT, Config(layers=LayersConfig(rules=False)))
    assert d.spans == []
    assert any("disabled" in n for n in d.notes)


def test_future_llm_layer_gives_note():
    d = detect_all(TEXT, Config(layers=LayersConfig(llm=True)))
    assert [s.kind for s in d.spans] == ["EMAIL"]
    assert len(d.notes) == 1


def test_ner_unavailable_raises(monkeypatch):
    def missing(cfg):
        raise ner.NerUnavailable("missing")

    monkeypatch.setattr(ner, "load_model", missing)
    with pytest.raises(ner.NerUnavailable):
        detect_all(TEXT, Config(layers=LayersConfig(ner=True)))
