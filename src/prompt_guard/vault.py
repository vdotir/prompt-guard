"""Session vault: reversible mapping between real values and placeholders.

Purpose:
    Replace detected spans with placeholders like [[EMAIL_1]] and remember
    the mapping, so the AI's reply can be restored later. Each chat uses its
    own session; within a session the same value always gets the same
    placeholder, across messages. A value already in the vault (4 characters
    or longer) is replaced in new text even if no detector flagged it this
    time.

    Storage: one JSON file per session in the vault directory. The directory
    is created with mode 0700 and each file with mode 0600; writes are atomic
    (temp file + rename). Sessions unused for longer than ttl_hours are
    deleted automatically whenever any session is opened.

Path in repo:
    src/prompt_guard/vault.py

Relations:
    - Input spans come from src/prompt_guard/rules.py (later ner.py, llm.py).
    - Settings from Config.vault (src/prompt_guard/config.py).
    - src/prompt_guard/restore.py reads the reverse mapping.
    - The CLI (later step) calls Vault.open / redact / save / clear_session.
    - Tested in tests/test_vault.py.

How to run:
    Library module, no entry point. Tests:
        pytest tests/test_vault.py
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from prompt_guard.config import VaultConfig
from prompt_guard.spans import Span, resolve_overlaps

FORMAT_VERSION = 1
DEFAULT_SESSION = "default"
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
# Values shorter than this are not searched again in later messages; the
# detectors still find them where their pattern matches (a prompt, a sudo line).
MIN_KNOWN_LENGTH = 4
PLACEHOLDER_RE = re.compile(r"\[\[([A-Z][A-Z0-9_]*)_(\d+)\]\]")


class VaultError(RuntimeError):
    """Raised for invalid sessions or unreadable vault files."""


def placeholder(kind: str, number: int) -> str:
    return f"[[{kind}_{number}]]"


@dataclass(frozen=True)
class Replacement:
    """One replaced value, for the --show review output."""

    placeholder: str
    kind: str
    value: str


def check_session_name(name: str) -> str:
    if not SESSION_RE.match(name):
        raise VaultError(f"invalid session name {name!r}: use 1-64 letters, digits, '-' or '_'")
    return name


def vault_dir(cfg: VaultConfig) -> Path:
    return Path(cfg.dir).expanduser()


def _ensure_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        path.chmod(0o700)


def _atomic_write(path: Path, data: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def purge_expired(cfg: VaultConfig, now: float | None = None) -> list[str]:
    """Delete session files not updated within ttl_hours. Returns their names."""
    if cfg.ttl_hours == 0:
        return []
    d = vault_dir(cfg)
    if not d.is_dir():
        return []
    limit = (time.time() if now is None else now) - cfg.ttl_hours * 3600
    removed = []
    for f in d.glob("*.json"):
        if f.stat().st_mtime < limit:
            f.unlink(missing_ok=True)
            removed.append(f.stem)
    return sorted(removed)


def list_sessions(cfg: VaultConfig) -> list[str]:
    d = vault_dir(cfg)
    return sorted(f.stem for f in d.glob("*.json")) if d.is_dir() else []


def clear_session(cfg: VaultConfig, session: str) -> bool:
    """Delete one session file. Returns True if it existed."""
    path = vault_dir(cfg) / f"{check_session_name(session)}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def clear_all(cfg: VaultConfig) -> list[str]:
    names = list_sessions(cfg)
    for name in names:
        clear_session(cfg, name)
    return names


def _bounded_finditer(value: str, text: str):
    """Find value in text, not as part of a longer word (for word-like edges)."""
    left = r"(?<!\w)" if re.match(r"\w", value) else ""
    right = r"(?!\w)" if re.search(r"\w$", value) else ""
    return re.finditer(left + re.escape(value) + right, text)


class Vault:
    """Mapping for one session. Use Vault.open(); call save() after changes."""

    def __init__(
        self,
        path: Path,
        session: str,
        forward: dict[str, str],
        counters: dict[str, int],
        created: float,
    ) -> None:
        self.path = path
        self.session = session
        self.forward = forward  # real value -> placeholder
        self.counters = counters  # kind -> last number used
        self.created = created
        self.dirty = False

    @classmethod
    def open(
        cls, cfg: VaultConfig, session: str = DEFAULT_SESSION, now: float | None = None
    ) -> Vault:
        check_session_name(session)
        purge_expired(cfg, now)
        d = vault_dir(cfg)
        path = d / f"{session}.json"
        if not path.exists():
            return cls(path, session, {}, {}, time.time() if now is None else now)
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            path.chmod(0o600)  # someone loosened it: tighten again
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != FORMAT_VERSION:
                raise VaultError(f"{path}: unsupported vault format {data.get('version')!r}")
            forward = {str(k): str(v) for k, v in data["forward"].items()}
            counters = {str(k): int(v) for k, v in data["counters"].items()}
            created = float(data["created"])
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise VaultError(f"{path}: damaged vault file ({exc})") from exc
        return cls(path, session, forward, counters, created)

    @property
    def reverse(self) -> dict[str, str]:
        """placeholder -> real value"""
        return {ph: value for value, ph in self.forward.items()}

    def tag(self, kind: str, value: str) -> str:
        """Return the placeholder for value, creating one if needed."""
        existing = self.forward.get(value)
        if existing:
            return existing
        number = self.counters.get(kind, 0) + 1
        self.counters[kind] = number
        ph = placeholder(kind, number)
        self.forward[value] = ph
        self.dirty = True
        return ph

    def redact(self, text: str, spans: list[Span]) -> tuple[str, list[Replacement]]:
        """Replace spans (plus any value already in the vault) with placeholders.

        Returns the new text and the list of replacements in text order.
        """
        candidates = list(spans)
        # Known values first in the list: they win ties and keep their kind.
        known = []
        for value, ph in self.forward.items():
            if len(value) < MIN_KNOWN_LENGTH:
                continue  # "ru" or "dev" would also hit unrelated words and paths
            m = PLACEHOLDER_RE.fullmatch(ph)
            kind = m.group(1) if m else "VALUE"
            known += [Span(x.start(), x.end(), kind) for x in _bounded_finditer(value, text)]
        # Never redact inside an existing placeholder.
        guarded = [m.span() for m in PLACEHOLDER_RE.finditer(text)]
        chosen = [
            s
            for s in resolve_overlaps(known + candidates)
            if all(s.end <= a or s.start >= b for a, b in guarded)
        ]
        parts: list[str] = []
        done: list[Replacement] = []
        pos = 0
        for s in chosen:
            value = s.value(text)
            ph = self.tag(s.kind, value)
            parts += [text[pos : s.start], ph]
            done.append(Replacement(ph, s.kind, value))
            pos = s.end
        parts.append(text[pos:])
        return "".join(parts), done

    def save(self, now: float | None = None) -> None:
        """Write the session file (always, so its mtime marks the last use)."""
        _ensure_dir(self.path.parent)
        data = {
            "version": FORMAT_VERSION,
            "session": self.session,
            "created": self.created,
            "updated": time.time() if now is None else now,
            "counters": self.counters,
            "forward": self.forward,
        }
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=1))
        if now is not None:
            os.utime(self.path, (now, now))
        self.dirty = False
