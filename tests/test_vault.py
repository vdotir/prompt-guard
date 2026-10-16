"""Tests for the session vault.

Purpose:
    Check placeholders, consistency across messages, file permissions,
    atomic save/load, expiry, clearing, and session name validation.

Path in repo:
    tests/test_vault.py

Relations:
    - Tests src/prompt_guard/vault.py.
    - Uses src/prompt_guard/rules.py for realistic spans.

How to run:
    pytest tests/test_vault.py
"""

import json
import os
import stat

import pytest

from prompt_guard.config import VaultConfig
from prompt_guard.rules import detect
from prompt_guard.spans import Span
from prompt_guard.vault import (
    Vault,
    VaultError,
    clear_all,
    clear_session,
    list_sessions,
    purge_expired,
)

NOW = 1_800_000_000.0
HOUR = 3600.0


@pytest.fixture
def cfg(tmp_path):
    return VaultConfig(dir=str(tmp_path / "vault"), ttl_hours=24.0)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_redact_replaces_spans(cfg):
    v = Vault.open(cfg)
    text = "mail jane@example.org from 203.0.113.7"
    out, reps = v.redact(text, detect(text))
    assert out == "mail [[EMAIL_1]] from [[IP_1]]"
    assert [(r.placeholder, r.value) for r in reps] == [
        ("[[EMAIL_1]]", "jane@example.org"),
        ("[[IP_1]]", "203.0.113.7"),
    ]


def test_same_value_same_placeholder(cfg):
    v = Vault.open(cfg)
    text = "a@example.org, b@example.org, a@example.org"
    out, _ = v.redact(text, detect(text))
    assert out == "[[EMAIL_1]], [[EMAIL_2]], [[EMAIL_1]]"


def test_consistency_across_messages_and_reload(cfg):
    v = Vault.open(cfg)
    v.redact("x a@example.org", detect("x a@example.org"))
    v.save()
    v2 = Vault.open(cfg)
    text = "y b@example.org then a@example.org"
    out, _ = v2.redact(text, detect(text))
    assert out == "y [[EMAIL_2]] then [[EMAIL_1]]"


def test_known_value_replaced_without_detection(cfg):
    v = Vault.open(cfg)
    v.redact("name Falcon here", [Span(5, 11, "CUSTOM")])
    out, reps = v.redact("again Falcon, not Falconry", [])
    assert out == "again [[CUSTOM_1]], not Falconry"
    assert len(reps) == 1


def test_existing_placeholders_untouched(cfg):
    v = Vault.open(cfg)
    text = "keep [[EMAIL_1]] as is"
    out, reps = v.redact(text, [Span(5, 16, "SECRET")])
    assert out == text
    assert reps == []


def test_file_and_dir_permissions(cfg):
    v = Vault.open(cfg)
    v.redact("a@example.org", detect("a@example.org"))
    v.save()
    assert mode(v.path) == 0o600
    assert mode(v.path.parent) == 0o700
    assert not list(v.path.parent.glob(".tmp-*"))


def test_loose_permissions_are_tightened(cfg):
    v = Vault.open(cfg)
    v.save()
    os.chmod(v.path, 0o644)
    Vault.open(cfg)
    assert mode(v.path) == 0o600


def test_saved_file_format(cfg):
    v = Vault.open(cfg, "chat-1")
    v.redact("a@example.org", detect("a@example.org"))
    v.save()
    data = json.loads(v.path.read_text())
    assert data["version"] == 1
    assert data["session"] == "chat-1"
    assert data["forward"] == {"a@example.org": "[[EMAIL_1]]"}
    assert data["counters"] == {"EMAIL": 1}


def test_damaged_file_raises(cfg):
    v = Vault.open(cfg)
    v.save()
    v.path.write_text("{not json")
    with pytest.raises(VaultError):
        Vault.open(cfg)


def test_expired_session_is_deleted(cfg):
    v = Vault.open(cfg, now=NOW)
    v.redact("a@example.org", detect("a@example.org"))
    v.save(now=NOW)
    fresh = Vault.open(cfg, now=NOW + 25 * HOUR)
    assert fresh.forward == {}
    assert not v.path.exists()


def test_recent_session_kept(cfg):
    v = Vault.open(cfg, now=NOW)
    v.redact("a@example.org", detect("a@example.org"))
    v.save(now=NOW)
    assert Vault.open(cfg, now=NOW + 23 * HOUR).forward


def test_ttl_zero_never_expires(cfg):
    cfg0 = VaultConfig(dir=cfg.dir, ttl_hours=0)
    v = Vault.open(cfg0, now=NOW)
    v.save(now=NOW)
    assert purge_expired(cfg0, now=NOW + 1000 * HOUR) == []
    assert v.path.exists()


def test_purge_only_old_sessions(cfg):
    Vault.open(cfg, "old", now=NOW).save(now=NOW)
    Vault.open(cfg, "new", now=NOW).save(now=NOW + 20 * HOUR)
    assert purge_expired(cfg, now=NOW + 30 * HOUR) == ["old"]
    assert list_sessions(cfg) == ["new"]


def test_clear_session_and_all(cfg):
    Vault.open(cfg, "a").save()
    Vault.open(cfg, "b").save()
    assert clear_session(cfg, "a") is True
    assert clear_session(cfg, "a") is False
    assert clear_all(cfg) == ["b"]
    assert list_sessions(cfg) == []


@pytest.mark.parametrize("name", ["", "../etc", "a/b", ".hidden", "x" * 65, "has space"])
def test_bad_session_names(cfg, name):
    with pytest.raises(VaultError):
        Vault.open(cfg, name)


def test_list_sessions_without_dir(tmp_path):
    assert list_sessions(VaultConfig(dir=str(tmp_path / "missing"))) == []


def test_short_known_values_not_searched_again(cfg):
    v = Vault.open(cfg)
    v.redact("ru@srv:~$ ls", [Span(0, 2, "USERNAME"), Span(3, 6, "HOSTNAME")])
    out, reps = v.redact("files in /srv/releases and the ru locale", [])
    assert out == "files in /srv/releases and the ru locale"
    assert reps == []


def test_long_known_values_still_searched_again(cfg):
    v = Vault.open(cfg)
    v.redact("host build-07 down", [Span(5, 13, "HOSTNAME")])
    out, _ = v.redact("again build-07", [])
    assert out == "again [[HOSTNAME_1]]"
