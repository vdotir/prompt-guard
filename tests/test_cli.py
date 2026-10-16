"""Tests for the command-line interface.

Purpose:
    Run the CLI end to end with in-memory streams and a fake clipboard:
    redact, restore, clear, sessions, --show masking, stdin/stdout versus
    clipboard selection, and error handling.

Path in repo:
    tests/test_cli.py

Relations:
    - Tests src/prompt_guard/cli.py with config.py, vault.py, restore.py,
      clipboard.py and pipeline.py.
    - Uses fake secrets from tests/fakes.py.

How to run:
    pytest tests/test_cli.py
"""

import io
import os

import pytest

from prompt_guard import llm, ner
from prompt_guard.cli import is_redirected, main, mask
from prompt_guard.clipboard import Backend, Clipboard
from tests import fakes


class MemoryClipboard(Clipboard):
    def __init__(self, text=""):
        super().__init__(Backend("test", ("r",), ("w",)))
        self.text = text

    def read(self):
        return self.text

    def write(self, text):
        self.text = text


@pytest.fixture
def config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(f'[vault]\ndir = "{tmp_path / "vault"}"\n', encoding="utf-8")
    return str(p)


@pytest.fixture
def terminal():
    """Streams that look like a terminal (not redirected), so the clipboard is used."""
    fin = open(os.devnull)
    fout = open(os.devnull, "w")
    yield fin, fout
    fin.close()
    fout.close()


def run(args, stdin_text="", **kw):
    out, err = io.StringIO(), io.StringIO()
    code = main(
        args,
        stdin=kw.pop("stdin", io.StringIO(stdin_text)),
        stdout=kw.pop("stdout", out),
        stderr=err,
        **kw,
    )
    return code, out.getvalue(), err.getvalue()


def test_redact_and_restore_via_pipes(config):
    original = f"mail jane@example.org, key {fakes.FAKE_API_KEY}"
    code, redacted, err = run(["redact", "-c", config], original)
    assert code == 0
    assert redacted == "mail [[EMAIL_1]], key [[API_KEY_1]]"
    assert "Redacted 2 value(s)" in err
    reply = "Use [[API_KEY_1]] and write to [EMAIL_1]."
    code, restored, err = run(["restore", "-c", config], reply)
    assert code == 0
    assert restored == f"Use {fakes.FAKE_API_KEY} and write to jane@example.org."
    assert "Restored 2" in err


def test_clipboard_round_trip(config, terminal):
    fin, fout = terminal
    cb = MemoryClipboard("ip 203.0.113.7")
    code, _, err = run(["redact", "-c", config], stdin=fin, stdout=fout, clipboard=cb)
    assert code == 0
    assert cb.text == "ip [[IP_1]]"
    assert "copied to clipboard" in err
    cb.text = "the address is [[IP_1]]"
    run(["restore", "-c", config], stdin=fin, stdout=fout, clipboard=cb)
    assert cb.text == "the address is 203.0.113.7"


def test_show_masks_values(config):
    _, _, err = run(["redact", "-c", config, "--show"], f"key {fakes.FAKE_API_KEY}")
    assert "[[API_KEY_1]]" in err
    assert fakes.FAKE_API_KEY not in err
    assert f"({len(fakes.FAKE_API_KEY)} chars)" in err


def test_secret_never_in_stderr_without_show(config):
    _, _, err = run(["redact", "-c", config], f"key {fakes.FAKE_API_KEY}")
    assert fakes.FAKE_API_KEY not in err


def test_nothing_found(config):
    code, out, err = run(["redact", "-c", config], "plain text")
    assert code == 0
    assert out == "plain text"
    assert "No sensitive values found" in err


def test_empty_input_is_error(config):
    code, out, err = run(["redact", "-c", config], "  \n")
    assert code == 1
    assert out == ""
    assert "empty" in err


def test_sessions_are_separate(config):
    run(["redact", "-c", config, "-s", "chat-a"], "a@example.org")
    _, out, _ = run(["redact", "-c", config, "-s", "chat-b"], "b@example.org")
    assert out == "[[EMAIL_1]]"
    _, out, _ = run(["restore", "-c", config, "-s", "chat-a"], "[[EMAIL_1]]")
    assert out == "a@example.org"


def test_restore_unknown_placeholder_warns(config):
    run(["redact", "-c", config], "a@example.org")
    code, out, err = run(["restore", "-c", config], "[[EMAIL_1]] [[EMAIL_7]]")
    assert code == 0
    assert out == "a@example.org [[EMAIL_7]]"
    assert "[[EMAIL_7]]" in err and "warning" in err


def test_restore_empty_session_is_error(config):
    code, out, err = run(["restore", "-c", config, "-s", "nothing"], "[[EMAIL_1]]")
    assert code == 1
    assert out == ""
    assert "empty or expired" in err


def test_clear_and_sessions(config):
    run(["redact", "-c", config, "-s", "one"], "a@example.org")
    run(["redact", "-c", config, "-s", "two"], "b@example.org")
    _, out, _ = run(["sessions", "-c", config])
    assert out.split() == ["one", "two"]
    _, _, err = run(["clear", "-c", config, "-s", "one"])
    assert "Deleted session 'one'" in err
    _, _, err = run(["clear", "-c", config, "-s", "one"])
    assert "does not exist" in err
    _, _, err = run(["clear", "-c", config, "--all"])
    assert "Deleted 1 session(s)" in err


def test_ner_unavailable_is_error_and_writes_nothing(config, monkeypatch):
    def missing(cfg):
        raise ner.NerUnavailable("layer 'ner' needs the optional extra")

    monkeypatch.setattr(ner, "load_model", missing)
    code, out, err = run(["redact", "-c", config, "--ner"], "Jane Doe, a@example.org")
    assert code == 1
    assert out == ""
    assert "optional extra" in err


def test_no_ner_flag_overrides_config(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text(f'[layers]\nner = true\n[vault]\ndir = "{tmp_path / "v"}"\n')

    def fail(cfg):
        raise AssertionError("model must not load with --no-ner")

    monkeypatch.setattr(ner, "load_model", fail)
    code, out, _ = run(["redact", "-c", str(p), "--no-ner"], "a@example.org")
    assert code == 0
    assert out == "[[EMAIL_1]]"


def test_llm_down_is_error_and_writes_nothing(config, monkeypatch):
    def down(url, payload, headers, timeout):
        raise llm.LlmUnavailable("cannot reach the server")

    monkeypatch.setattr(llm, "http_json", down)
    code, out, err = run(["redact", "-c", config, "--llm"], "Bob Marsh, a@example.org")
    assert code == 1
    assert out == ""
    assert "cannot reach" in err


def test_llm_finds_extra_value(config, monkeypatch):
    def server(url, payload, headers, timeout):
        content = '{"items": [{"value": "Bob Marsh", "type": "PERSON"}]}'
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(llm, "http_json", server)
    code, out, _ = run(["redact", "-c", config, "--llm"], "Bob Marsh, a@example.org")
    assert code == 0
    assert out == "[[PERSON_1]], [[EMAIL_1]]"


@pytest.mark.parametrize(("model", "code"), [("qwen3-8b", 0), ("missing-model", 1)])
def test_llm_check(tmp_path, monkeypatch, model, code):
    p = tmp_path / "c.toml"
    p.write_text(f'[llm]\nmodel = "{model}"\n')

    def server(url, payload, headers, timeout):
        return {"data": [{"id": "qwen3-8b"}, {"id": "gemma-3-4b"}]}

    monkeypatch.setattr(llm, "http_json", server)
    rc, out, err = run(["llm-check", "-c", str(p)])
    assert rc == code
    assert "qwen3-8b" in out and "gemma-3-4b" in out


def test_bad_config_is_clean_error(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("[rules]\nnope = 1\n")
    code, _, err = run(["redact", "-c", str(p)], "x")
    assert code == 1
    assert "unknown key" in err


def test_bad_session_name(config):
    code, _, err = run(["redact", "-c", config, "-s", "../x"], "a@example.org")
    assert code == 1
    assert "invalid session name" in err


def test_is_redirected(tmp_path):
    assert is_redirected(io.StringIO()) is True
    with open(os.devnull) as f:
        assert is_redirected(f) is False
    with open(tmp_path / "f.txt", "w") as f:
        assert is_redirected(f) is True


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("abc", "*** (3 chars)"),
        ("abcdefgh", "a…h (8 chars)"),
        ("abcdefghijklmnop", "abcd…op (16 chars)"),
    ],
)
def test_mask(value, shown):
    assert mask(value) == shown
