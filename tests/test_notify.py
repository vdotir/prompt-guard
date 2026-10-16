"""Tests for desktop notifications.

Purpose:
    Check the notify-send command line, that a missing notify-send is not an
    error, and that the CLI notifies only with --notify and never includes
    hidden values.

Path in repo:
    tests/test_notify.py

Relations:
    - Tests src/prompt_guard/notify.py and its use in src/prompt_guard/cli.py.

How to run:
    pytest tests/test_notify.py
"""

import io
import subprocess

from prompt_guard import notify
from prompt_guard.cli import main
from tests import fakes


def test_send_builds_command():
    calls = []
    ok = notify.send("Title", "Body", "critical", runner=calls.append, which=lambda n: "/x")
    assert ok is True
    assert calls == [
        ["notify-send", "--app-name", "prompt-guard", "--urgency", "critical", "Title", "Body"]
    ]


def test_send_without_notify_send():
    calls = []
    assert notify.send("T", runner=calls.append, which=lambda n: None) is False
    assert calls == []


def test_send_survives_runner_error():
    def boom(argv):
        raise subprocess.TimeoutExpired(argv, 5)

    assert notify.send("T", runner=boom, which=lambda n: "/x") is False


def run_cli(args, text, config, monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda *a, **k: sent.append(a) or True)
    out, err = io.StringIO(), io.StringIO()
    code = main([*args, "-c", config], stdin=io.StringIO(text), stdout=out, stderr=err)
    return code, out.getvalue(), sent


def make_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(f'[vault]\ndir = "{tmp_path / "v"}"\n')
    return str(p)


def test_redact_notifies_without_values(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    code, _, sent = run_cli(["redact", "--notify"], f"key {fakes.FAKE_API_KEY}", cfg, monkeypatch)
    assert code == 0
    assert len(sent) == 1
    assert "Redacted 1" in sent[0][0]
    assert fakes.FAKE_API_KEY not in " ".join(map(str, sent[0]))


def test_no_notification_without_flag(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    _, _, sent = run_cli(["redact"], "a@example.org", cfg, monkeypatch)
    assert sent == []


def test_error_notifies(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    code, _, sent = run_cli(["restore", "--notify", "-s", "empty"], "[[X_1]]", cfg, monkeypatch)
    assert code == 1
    assert sent[0][0] == "prompt-guard: error"
    assert "not changed" in sent[0][1]


def test_restore_unknown_is_critical(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    run_cli(["redact"], "a@example.org", cfg, monkeypatch)
    _, _, sent = run_cli(["restore", "--notify"], "[[EMAIL_1]] [[EMAIL_5]]", cfg, monkeypatch)
    assert sent[0][2] == "critical"
