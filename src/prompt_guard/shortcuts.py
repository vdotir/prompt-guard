"""Keyboard shortcuts for redact and restore (GNOME).

Purpose:
    Add two GNOME custom keyboard shortcuts, so the daily workflow needs no
    terminal:
        Ctrl+Alt+R   pgd redact --notify    (hide values in the clipboard)
        Ctrl+Alt+U   pgd restore --notify   (put them back into the AI's reply)
    The shortcuts are stored with gsettings, next to any shortcuts the user
    already has; only prompt-guard's own entries are added or removed.
    On other desktops (KDE, Xfce, ...) the commands are printed so they can
    be added in that desktop's keyboard settings.

Path in repo:
    src/prompt_guard/shortcuts.py

Relations:
    - "pgd shortcuts install | remove | show" in src/prompt_guard/cli.py.
    - The commands call the CLI with --notify (src/prompt_guard/notify.py).
    - Tested in tests/test_shortcuts.py with a fake gsettings.

How to run:
    pgd shortcuts install
    pgd shortcuts show
    pgd shortcuts remove
"""

from __future__ import annotations

import ast
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
LIST_KEY = "custom-keybindings"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
ITEM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"

DEFAULT_REDACT_KEY = "<Control><Alt>r"
DEFAULT_RESTORE_KEY = "<Control><Alt>u"

# runner(argv) -> stdout text; raises ShortcutError on failure
Runner = Callable[[list[str]], str]


class ShortcutError(RuntimeError):
    """Raised when shortcuts cannot be read or written."""


@dataclass(frozen=True)
class Shortcut:
    ident: str
    name: str
    command: str
    binding: str

    @property
    def path(self) -> str:
        return f"{BASE}{self.ident}/"


def run_gsettings(argv: list[str]) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(f"cannot run {argv[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise ShortcutError(f"{' '.join(argv[:3])} failed: {proc.stderr.strip()}")
    return proc.stdout


def pgd_path() -> str:
    """Absolute path of the pgd command in the running environment (venv)."""
    candidate = Path(sys.executable).parent / "pgd"
    if candidate.exists():
        return str(candidate)
    found = shutil.which("pgd")
    if found:
        return str(Path(found).resolve())
    raise ShortcutError("cannot find the pgd command; install with: pip install -e .")


def build(
    redact_key: str = DEFAULT_REDACT_KEY,
    restore_key: str = DEFAULT_RESTORE_KEY,
    redact_args: str = "",
    pgd: str | None = None,
) -> list[Shortcut]:
    exe = shlex.quote(pgd or pgd_path())
    extra = " ".join(shlex.quote(a) for a in shlex.split(redact_args))
    redact_cmd = f"{exe} redact --notify" + (f" {extra}" if extra else "")
    return [
        Shortcut("prompt-guard-redact", "prompt-guard: redact clipboard", redact_cmd, redact_key),
        Shortcut(
            "prompt-guard-restore",
            "prompt-guard: restore clipboard",
            f"{exe} restore --notify",
            restore_key,
        ),
    ]


def parse_list(output: str) -> list[str]:
    text = output.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise ShortcutError(f"unexpected gsettings output: {output.strip()!r}") from exc
    if not isinstance(value, list):
        raise ShortcutError(f"unexpected gsettings output: {output.strip()!r}")
    return [str(v) for v in value]


def gnome_available(
    which: Callable[[str], str | None] = shutil.which, runner: Runner = run_gsettings
) -> bool:
    if not which("gsettings"):
        return False
    try:
        return SCHEMA in runner(["gsettings", "list-schemas"]).split()
    except ShortcutError:
        return False


class GnomeShortcuts:
    def __init__(self, runner: Runner = run_gsettings) -> None:
        self.run = runner

    def current(self) -> list[str]:
        return parse_list(self.run(["gsettings", "get", SCHEMA, LIST_KEY]))

    def _set_list(self, paths: list[str]) -> None:
        self.run(["gsettings", "set", SCHEMA, LIST_KEY, str(paths)])

    def install(self, shortcuts: list[Shortcut]) -> None:
        paths = self.current()
        for sc in shortcuts:
            item = f"{ITEM_SCHEMA}:{sc.path}"
            self.run(["gsettings", "set", item, "name", sc.name])
            self.run(["gsettings", "set", item, "command", sc.command])
            self.run(["gsettings", "set", item, "binding", sc.binding])
            if sc.path not in paths:
                paths.append(sc.path)
        self._set_list(paths)

    def remove(self, shortcuts: list[Shortcut]) -> int:
        paths = self.current()
        ours = {sc.path for sc in shortcuts}
        removed = 0
        for sc in shortcuts:
            item = f"{ITEM_SCHEMA}:{sc.path}"
            for key in ("name", "command", "binding"):
                self.run(["gsettings", "reset", item, key])
            if sc.path in paths:
                removed += 1
        self._set_list([p for p in paths if p not in ours])
        return removed

    def show(self, shortcuts: list[Shortcut]) -> list[tuple[str, str, str]]:
        """(name, binding, command) of prompt-guard entries that are active."""
        paths = self.current()
        result = []
        for sc in shortcuts:
            if sc.path not in paths:
                continue
            item = f"{ITEM_SCHEMA}:{sc.path}"
            binding = ast.literal_eval(self.run(["gsettings", "get", item, "binding"]).strip())
            command = ast.literal_eval(self.run(["gsettings", "get", item, "command"]).strip())
            result.append((sc.name, str(binding), str(command)))
        return result


def manual_instructions(shortcuts: list[Shortcut]) -> str:
    lines = ["Add these as custom shortcuts in your desktop's keyboard settings:"]
    for sc in shortcuts:
        lines.append(f"  {sc.binding:<18} {sc.command}")
    return "\n".join(lines)
