"""Tests for the detection pipeline.

Purpose:
    Check that enabled layers run, disabled ones do not, and that a layer
    that cannot run (NER not installed, LLM server down) fails loudly
    instead of being skipped.

Path in repo:
    tests/test_pipeline.py

Relations:
    - Tests src/prompt_guard/pipeline.py.

How to run:
    pytest tests/test_pipeline.py
"""

import pytest

from prompt_guard import llm, ner
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


def test_llm_unavailable_raises(monkeypatch):
    def down(url, payload, headers, timeout):
        raise llm.LlmUnavailable("down")

    monkeypatch.setattr(llm, "http_json", down)
    with pytest.raises(llm.LlmUnavailable):
        detect_all(TEXT, Config(layers=LayersConfig(llm=True)))


def test_ner_unavailable_raises(monkeypatch):
    def missing(cfg):
        raise ner.NerUnavailable("missing")

    monkeypatch.setattr(ner, "load_model", missing)
    with pytest.raises(ner.NerUnavailable):
        detect_all(TEXT, Config(layers=LayersConfig(ner=True)))
