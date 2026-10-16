"""Tests for restoring real values in the AI's reply.

Purpose:
    Check the full round trip (redact -> reply -> restore), the accepted
    mangled placeholder forms, and reporting of unknown placeholders.

Path in repo:
    tests/test_restore.py

Relations:
    - Tests src/prompt_guard/restore.py together with vault.py and rules.py.
    - Uses fake secrets from tests/fakes.py.

How to run:
    pytest tests/test_restore.py
"""

import pytest

from prompt_guard.config import VaultConfig
from prompt_guard.restore import restore
from prompt_guard.rules import detect
from prompt_guard.vault import Vault
from tests import fakes


@pytest.fixture
def vault(tmp_path):
    v = Vault.open(VaultConfig(dir=str(tmp_path / "vault")))
    text = f"mail jane@example.org key={fakes.FAKE_API_KEY}"
    v.redact(text, detect(text))
    return v


def test_round_trip(tmp_path):
    v = Vault.open(VaultConfig(dir=str(tmp_path / "vault")))
    original = "\n".join(
        [
            "host = 192.0.2.10",
            "admin = ops@example.org",
            f"token = {fakes.FAKE_GITHUB_TOKEN}",
            "db = postgres://app:Sup3rS3cret@db.example.org/main",
        ]
    )
    redacted, _ = v.redact(original, detect(original))
    for secret in ("192.0.2.10", "ops@example.org", fakes.FAKE_GITHUB_TOKEN, "Sup3rS3cret"):
        assert secret not in redacted
    assert restore(redacted, v).text == original


@pytest.mark.parametrize(
    "form",
    [
        "[[EMAIL_1]]",
        "[[ EMAIL_1 ]]",
        r"\[\[EMAIL_1\]\]",
        "[EMAIL_1]",
        "<EMAIL_1>",
        "&lt;EMAIL_1&gt;",
    ],
)
def test_mangled_forms(vault, form):
    result = restore(f"send to {form} now", vault)
    assert result.text == "send to jane@example.org now"
    assert result.restored == 1
    assert result.unknown == ()


def test_unknown_double_bracket_reported_and_kept(vault):
    result = restore("use [[EMAIL_9]] and [[EMAIL_1]] and [[EMAIL_9]]", vault)
    assert result.text == "use [[EMAIL_9]] and jane@example.org and [[EMAIL_9]]"
    assert result.unknown == ("[[EMAIL_9]]",)


def test_unknown_single_bracket_is_normal_text(vault):
    result = restore("see [ITEM_1] and <TAG_2>", vault)
    assert result.text == "see [ITEM_1] and <TAG_2>"
    assert result.unknown == ()


def test_several_placeholders(vault):
    result = restore("[[EMAIL_1]] / [[API_KEY_1]]", vault)
    assert result.text == f"jane@example.org / {fakes.FAKE_API_KEY}"
    assert result.restored == 2


def test_lowercase_is_not_a_placeholder(vault):
    assert restore("[[email_1]]", vault).text == "[[email_1]]"
