"""Clipboard access through the system's own tools.

Purpose:
    Read and write the clipboard without extra Python packages, by calling
    the standard command-line tools of each environment:
        WSL      powershell.exe Get-Clipboard / Set-Clipboard (Windows clipboard)
        Wayland  wl-paste / wl-copy               (package: wl-clipboard)
        X11      xclip, or xsel as a second choice (package: xclip or xsel)
        macOS    pbpaste / pbcopy                  (built in)
    "auto" picks the first one that fits the running environment and has
    its tools installed. Text is always passed as UTF-8.

Path in repo:
    src/prompt_guard/clipboard.py

Relations:
    - Settings from Config.clipboard (src/prompt_guard/config.py).
    - Used by src/prompt_guard/cli.py for default input and output.
    - Tested in tests/test_clipboard.py (with a fake command runner).

How to run:
    Library module. Show which backend auto-detection picks:
        python -m prompt_guard.clipboard
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from prompt_guard.config import ClipboardConfig


class ClipboardError(RuntimeError):
    """Raised when no clipboard tool is available or a tool fails."""


# Runner signature: (argv, input_text or None, timeout) -> stdout text.
Runner = Callable[[list[str], str | None, float], str]

PS_READ = (
    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
    "$t = Get-Clipboard -Raw; if ($t) { [Console]::Out.Write($t) }"
)
PS_WRITE = (
    "[Console]::InputEncoding=[Text.Encoding]::UTF8; "
    "Set-Clipboard -Value ([Console]::In.ReadToEnd())"
)


def run_command(argv: list[str], input_text: str | None, timeout: float) -> str:
    """Run a clipboard tool.

    Writers (wl-copy, xclip) leave a background process that serves the
    clipboard until something else is copied. That process inherits the
    writer's stdout and stderr. If those were pipes, waiting for the pipes to
    close would block until the timeout, even though the copy worked. So a
    writer gets no stdout, and its stderr goes to a temporary file instead of
    a pipe.
    """
    try:
        if input_text is None:
            proc = subprocess.run(
                argv, capture_output=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL
            )
            stderr = proc.stderr or b""
        else:
            with tempfile.TemporaryFile() as errfile:
                proc = subprocess.run(
                    argv,
                    input=input_text.encode("utf-8"),
                    stdout=subprocess.DEVNULL,
                    stderr=errfile,
                    timeout=timeout,
                    check=False,
                )
                errfile.seek(0)
                stderr = errfile.read()
    except FileNotFoundError as exc:
        raise ClipboardError(f"{argv[0]} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClipboardError(f"{argv[0]} did not answer within {timeout:g}s") from exc
    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace").strip()
        raise ClipboardError(f"{argv[0]} failed (exit {proc.returncode}): {err}")
    return (proc.stdout or b"").decode("utf-8", "replace") if input_text is None else ""


@dataclass(frozen=True)
class Backend:
    name: str
    read_cmd: tuple[str, ...]
    write_cmd: tuple[str, ...]
    crlf: bool = False  # Windows tools return \r\n line endings


BACKENDS: dict[str, tuple[Backend, ...]] = {
    "wsl": (
        Backend(
            "wsl",
            ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_READ),
            ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_WRITE),
            crlf=True,
        ),
    ),
    "wayland": (Backend("wayland", ("wl-paste", "--no-newline"), ("wl-copy",)),),
    "x11": (
        Backend(
            "x11",
            ("xclip", "-o", "-selection", "clipboard"),
            ("xclip", "-i", "-selection", "clipboard"),
        ),
        Backend("x11", ("xsel", "--clipboard", "--output"), ("xsel", "--clipboard", "--input")),
    ),
    "macos": (Backend("macos", ("pbpaste",), ("pbcopy",)),),
}


def is_wsl(env: Mapping[str, str] | None = None, proc_version: Path | None = None) -> bool:
    env = os.environ if env is None else env
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    path = proc_version or Path("/proc/version")
    try:
        return "microsoft" in path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False


def candidates(
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    wsl: bool | None = None,
) -> list[str]:
    """Backend names that fit the environment, best first."""
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if platform == "darwin":
        return ["macos"]
    names = []
    if wsl if wsl is not None else is_wsl(env):
        names.append("wsl")
    if env.get("WAYLAND_DISPLAY"):
        names.append("wayland")
    if env.get("DISPLAY"):
        names.append("x11")
    return names


def pick_backend(
    name: str = "auto",
    which: Callable[[str], str | None] = shutil.which,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    wsl: bool | None = None,
) -> Backend:
    names = candidates(env, platform, wsl) if name == "auto" else [name]
    if name != "auto" and name not in BACKENDS:
        raise ClipboardError(f"unknown clipboard backend {name!r}")
    for n in names:
        for backend in BACKENDS[n]:
            if which(backend.read_cmd[0]) and which(backend.write_cmd[0]):
                return backend
    if name == "auto" and not names:
        raise ClipboardError(
            "no desktop session found (no DISPLAY, WAYLAND_DISPLAY or WSL); "
            "use -i/-o to read stdin and write stdout"
        )
    tools = {
        "wayland": "install wl-clipboard",
        "x11": "install xclip (or xsel)",
        "wsl": "powershell.exe must be reachable from WSL",
        "macos": "pbcopy/pbpaste are missing",
    }
    hints = "; ".join(f"{n}: {tools[n]}" for n in names)
    raise ClipboardError(f"no clipboard tool found ({hints}); or use -i/-o for stdin/stdout")


class Clipboard:
    def __init__(
        self, backend: Backend, timeout: float = 10.0, runner: Runner = run_command
    ) -> None:
        self.backend = backend
        self.timeout = timeout
        self.runner = runner

    @classmethod
    def from_config(cls, cfg: ClipboardConfig, runner: Runner = run_command) -> Clipboard:
        return cls(pick_backend(cfg.backend), cfg.timeout, runner)

    def read(self) -> str:
        text = self.runner(list(self.backend.read_cmd), None, self.timeout)
        if self.backend.crlf:
            text = text.replace("\r\n", "\n")
        return text

    def write(self, text: str) -> None:
        if self.backend.crlf:
            text = text.replace("\r\n", "\n").replace("\n", "\r\n")
        self.runner(list(self.backend.write_cmd), text, self.timeout)


def main() -> None:
    try:
        b = pick_backend()
    except ClipboardError as exc:
        print(f"no clipboard: {exc}")
        raise SystemExit(1) from exc
    print(f"backend: {b.name} (read: {b.read_cmd[0]}, write: {b.write_cmd[0]})")


if __name__ == "__main__":
    main()
