"""Restore real values in the AI's reply.

Purpose:
    Replace placeholders such as [[EMAIL_1]] in the AI's reply with the real
    values from the session vault. Online chats sometimes change the
    brackets, so these forms are also accepted:
        [[X_1]]   [[ X_1 ]]   \\[\\[X_1\\]\\]   [X_1]   <X_1>   &lt;X_1&gt;
    Single-bracket and angle forms are only replaced when the placeholder is
    in the vault, so normal text like "[ITEM_1]" is left alone.
    Double-bracket placeholders that are not in the vault are reported as
    unknown (the AI may have invented them) and left unchanged.

Path in repo:
    src/prompt_guard/restore.py

Relations:
    - Reads Vault.reverse from src/prompt_guard/vault.py.
    - Called by the CLI "restore" command (later step).
    - Tested in tests/test_restore.py.

How to run:
    Library module, no entry point. Tests:
        pytest tests/test_restore.py
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from prompt_guard.vault import Vault

_NAME = r"([A-Z][A-Z0-9_]*_\d+)"
# Order matters: the double-bracket forms must be tried before single ones.
TAG_RE = re.compile(
    r"\\\[\\\[\s*" + _NAME + r"\s*\\\]\\\]"  # \[\[X_1\]\] (Markdown-escaped)
    r"|\[\[\s*" + _NAME + r"\s*\]\]"  # [[X_1]]
    r"|\[" + _NAME + r"\]"  # [X_1]
    r"|<" + _NAME + r">"  # <X_1>
    r"|&lt;" + _NAME + r"&gt;"  # &lt;X_1&gt;
)
DOUBLE_GROUPS = (1, 2)


@dataclass(frozen=True)
class RestoreResult:
    text: str
    restored: int
    unknown: tuple[str, ...]  # placeholders not found in the vault


def restore(text: str, vault: Vault) -> RestoreResult:
    reverse = vault.reverse
    restored = 0
    unknown: list[str] = []

    def sub(m: re.Match[str]) -> str:
        nonlocal restored
        group = m.lastindex or 0
        key = f"[[{m.group(group)}]]"
        if key in reverse:
            restored += 1
            return reverse[key]
        if group in DOUBLE_GROUPS and key not in unknown:
            unknown.append(key)
        return m.group(0)

    return RestoreResult(TAG_RE.sub(sub, text), restored, tuple(unknown))
