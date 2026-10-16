"""Tests for the detection pipeline.

Purpose:
    Check that enabled layers run, disabled ones do not, and that layers not
    yet available give a note instead of failing.

Path in repo:
    tests/test_pipeline.py

Relations:
    - Tests src/prompt_guard/pipeline.py.

How to run:
    pytest tests/test_pipeline.py
"""

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


def test_future_layers_give_notes():
    d = detect_all(TEXT, Config(layers=LayersConfig(ner=True, llm=True)))
    assert [s.kind for s in d.spans] == ["EMAIL"]
    assert len(d.notes) == 2
