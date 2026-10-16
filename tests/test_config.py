"""Tests for config loading and validation.

Purpose:
    Check defaults, file lookup order, and that bad settings fail loudly.
    Also check that config.example.toml in the repo always parses.

Path in repo:
    tests/test_config.py

Relations:
    - Tests src/prompt_guard/config.py.
    - Reads config.example.toml from the repo root.

How to run:
    pytest tests/test_config.py
"""

from pathlib import Path

import pytest

from prompt_guard.config import Config, ConfigError, load_config, parse_config

ROOT = Path(__file__).resolve().parents[1]


def test_missing_default_file_gives_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPT_GUARD_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load_config() == Config()


def test_missing_explicit_file_is_error(tmp_path):
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.toml")


def test_env_var_path(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text("[layers]\nner = true\n", encoding="utf-8")
    monkeypatch.setenv("PROMPT_GUARD_CONFIG", str(p))
    cfg = load_config()
    assert cfg.layers.ner is True
    assert cfg.source == str(p)


def test_xdg_path(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMPT_GUARD_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "prompt-guard").mkdir()
    (tmp_path / "prompt-guard" / "config.toml").write_text('[llm]\nmodel = "x"\n')
    assert load_config().llm.model == "x"


def test_example_file_parses():
    cfg = load_config(ROOT / "config.example.toml")
    assert cfg.rules.patterns


def test_partial_section_keeps_other_defaults():
    cfg = parse_config({"rules": {"words": ["acme"]}})
    assert cfg.rules.words == ("acme",)
    assert cfg.rules.entropy is True
    assert cfg.llm == Config().llm


def test_int_accepted_for_float():
    assert parse_config({"llm": {"timeout": 30}}).llm.timeout == 30.0


@pytest.mark.parametrize(
    "data",
    [
        {"unknown": {}},
        {"rules": {"typo_key": 1}},
        {"layers": {"ner": "yes"}},
        {"rules": {"entropy_threshold": "high"}},
        {"rules": {"words": "acme"}},
        {"rules": {"entropy_threshold": 9}},
        {"rules": {"entropy_min_length": 3}},
        {"ner": {"threshold": 1.5}},
        {"vault": {"ttl_hours": -1}},
        {"ner": {"device": "tpu"}},
        {"llm": {"base_url": "localhost:1234"}},
        {"llm": {"timeout": 0}},
        {"llm": {"max_chunk_chars": 10}},
        {"llm": {"max_tokens": 1}},
        {"llm": {"structured_output": "xml"}},
        {"ner": {"max_chunk_words": 5}},
        {"ner": {"labels": []}},
        {"clipboard": {"backend": "windows"}},
        {"clipboard": {"timeout": 0}},
        {"rules": {"patterns": [{"name": "lower", "regex": "x"}]}},
        {"rules": {"patterns": [{"name": "BAD", "regex": "("}]}},
        {"rules": {"patterns": [{"name": "X"}]}},
        {"layers": "on"},
    ],
)
def test_invalid_config_raises(data):
    with pytest.raises(ConfigError):
        parse_config(data)


def test_bad_toml_raises(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[layers\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)
