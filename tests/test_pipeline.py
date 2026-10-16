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


class LabelEverything:
    """Fake NER model that returns fixed (value, label) pairs."""

    def __init__(self, pairs):
        self.pairs = pairs

    def predict_entities(self, text, labels, threshold=0.5):
        out = []
        for value, label in self.pairs:
            i = text.find(value)
            while i >= 0:
                out.append({"start": i, "end": i + len(value), "label": label, "score": 0.9})
                i = text.find(value, i + 1)
        return out


JSON_LINE = '{"peer_name": "dev", "client_address": "10.77.0.2", "endpoint": "203.0.113.9"}'


def run_with_ner(hide_private_ips):
    from prompt_guard.config import RulesConfig
    from prompt_guard.ner import NerDetector

    cfg = Config(
        layers=LayersConfig(ner=True), rules=RulesConfig(hide_private_ips=hide_private_ips)
    )
    model = LabelEverything(
        [("10.77.0.2", "location address"), ("203.0.113.9", "location address")]
    )
    det = NerDetector(cfg.ner, model=model)
    spans = detect_all(JSON_LINE, cfg, ner_detector=det).spans
    return [(s.kind, s.value(JSON_LINE)) for s in spans]


def test_ner_ip_follows_private_ip_policy():
    # The private IP stays visible; the public one is hidden as IP, not ADDRESS.
    assert run_with_ner(hide_private_ips=False) == [("IP", "203.0.113.9")]


def test_ner_ip_gets_ip_kind_when_hidden():
    assert run_with_ner(hide_private_ips=True) == [("IP", "10.77.0.2"), ("IP", "203.0.113.9")]


def test_llm_ip_follows_private_ip_policy():
    from prompt_guard.config import RulesConfig
    from prompt_guard.llm import LlmReviewer

    def server(url, payload, headers, timeout):
        content = '{"items": [{"value": "10.77.0.2", "type": "ADDRESS"}]}'
        return {"choices": [{"message": {"content": content}}]}

    cfg = Config(layers=LayersConfig(llm=True), rules=RulesConfig(hide_private_ips=False))
    spans = detect_all(JSON_LINE, cfg, llm_reviewer=LlmReviewer(cfg.llm, http=server)).spans
    assert [s.kind for s in spans] == ["IP"]
    assert spans[0].value(JSON_LINE) == "203.0.113.9"
