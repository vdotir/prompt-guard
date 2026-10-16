"""Desktop notifications for runs without a terminal.

Purpose:
    When prompt-guard runs from a keyboard shortcut, nobody sees stderr. With
    --notify, the CLI also shows a short desktop notification (done, nothing
    found, warnings, errors). Notifications never contain the hidden values.
    Uses notify-send (package libnotify-bin on Ubuntu); if it is missing, the
    notification is skipped without an error.

Path in repo:
    src/prompt_guard/notify.py

Relations:
    - Called by src/prompt_guard/cli.py when --notify is given.
    - Tested in tests/test_notify.py.

How to run:
    Library module. Send a test notification:
        python -m prompt_guard.notify
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

APP_NAME = "prompt-guard"

# runner(argv) -> None; may raise OSError or subprocess errors
Runner = Callable[[list[str]], None]


def _run(argv: list[str]) -> None:
    subprocess.run(argv, check=False, timeout=5, capture_output=True)


def send(
    title: str,
    body: str = "",
    urgency: str = "normal",
    runner: Runner = _run,
    which: Callable[[str], str | None] = shutil.which,
) -> bool:
    """Show a notification. Returns False if it could not be shown."""
    if not which("notify-send"):
        return False
    argv = ["notify-send", "--app-name", APP_NAME, "--urgency", urgency, title]
    if body:
        argv.append(body)
    try:
        runner(argv)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def main() -> None:
    ok = send("prompt-guard", "Notifications work.")
    print("sent" if ok else "notify-send not found (sudo apt install libnotify-bin)")


if __name__ == "__main__":
    main()
