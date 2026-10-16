"""Tests for clipboard backend selection and the Clipboard wrapper.

Purpose:
    Check auto-detection for WSL, Wayland, X11 and macOS, the fallback from
    xclip to xsel, helpful errors, and CRLF handling for the Windows
    clipboard. No real clipboard tool is called: a fake runner records the
    commands.

Path in repo:
    tests/test_clipboard.py

Relations:
    - Tests src/prompt_guard/clipboard.py.

How to run:
    pytest tests/test_clipboard.py
"""

import pytest

from prompt_guard.clipboard import (
    Clipboard,
    ClipboardError,
    candidates,
    is_wsl,
    pick_backend,
    run_command,
)


def which_from(*names):
    return lambda tool: f"/usr/bin/{tool}" if tool in names else None


class FakeRunner:
    def __init__(self, output=""):
        self.calls = []
        self.output = output

    def __call__(self, argv, input_text, timeout):
        self.calls.append((argv, input_text))
        return self.output


def test_candidates_order():
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert candidates(env, "linux", wsl=False) == ["wayland", "x11"]
    assert candidates(env, "linux", wsl=True) == ["wsl", "wayland", "x11"]
    assert candidates({}, "darwin", wsl=False) == ["macos"]
    assert candidates({}, "linux", wsl=False) == []


def test_is_wsl(tmp_path):
    pv = tmp_path / "version"
    pv.write_text("Linux version 6.6.0-microsoft-standard-WSL2")
    assert is_wsl({}, pv) is True
    pv.write_text("Linux version 6.8.0-generic")
    assert is_wsl({}, pv) is False
    assert is_wsl({"WSL_DISTRO_NAME": "Ubuntu"}, pv) is True
    assert is_wsl({}, tmp_path / "missing") is False


def test_auto_prefers_wayland_when_tools_exist():
    b = pick_backend(
        "auto",
        which_from("wl-copy", "wl-paste", "xclip"),
        {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"},
        "linux",
        wsl=False,
    )
    assert b.name == "wayland"


def test_auto_falls_back_to_x11_without_wl_clipboard():
    b = pick_backend(
        "auto", which_from("xclip"), {"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}, "linux", wsl=False
    )
    assert b.name == "x11"
    assert b.read_cmd[0] == "xclip"


def test_x11_uses_xsel_when_no_xclip():
    b = pick_backend("x11", which_from("xsel"), {}, "linux", wsl=False)
    assert b.read_cmd[0] == "xsel"


def test_wsl_backend():
    b = pick_backend("auto", which_from("powershell.exe"), {}, "linux", wsl=True)
    assert b.name == "wsl"
    assert b.crlf is True


def test_no_session_error_mentions_stdin_option():
    with pytest.raises(ClipboardError, match="-i/-o"):
        pick_backend("auto", which_from(), {}, "linux", wsl=False)


def test_missing_tool_error_names_package():
    with pytest.raises(ClipboardError, match="wl-clipboard"):
        pick_backend("auto", which_from(), {"WAYLAND_DISPLAY": "w"}, "linux", wsl=False)


def test_unknown_backend():
    with pytest.raises(ClipboardError):
        pick_backend("windows", which_from(), {}, "linux", wsl=False)


def test_read_and_write_commands():
    b = pick_backend("wayland", which_from("wl-copy", "wl-paste"), {}, "linux", wsl=False)
    runner = FakeRunner("hello")
    cb = Clipboard(b, runner=runner)
    assert cb.read() == "hello"
    cb.write("bye")
    assert runner.calls == [(["wl-paste", "--no-newline"], None), (["wl-copy"], "bye")]


def test_wsl_crlf_conversion():
    b = pick_backend("wsl", which_from("powershell.exe"), {}, "linux", wsl=True)
    runner = FakeRunner("a\r\nb\r\n")
    cb = Clipboard(b, runner=runner)
    assert cb.read() == "a\nb\n"
    cb.write("x\ny")
    assert runner.calls[-1][1] == "x\r\ny"


def test_run_command_missing_tool():
    with pytest.raises(ClipboardError, match="not found"):
        run_command(["no-such-clipboard-tool-xyz"], None, 1.0)


def test_run_command_reads_and_writes():
    assert run_command(["printf", "abc"], None, 5.0) == "abc"
    assert run_command(["cat"], "ignored output", 5.0) == ""


def test_run_command_failure():
    with pytest.raises(ClipboardError, match="exit 1"):
        run_command(["false"], None, 5.0)


def test_writer_that_stays_in_background_does_not_block():
    # Like wl-copy and xclip: read the input, then leave a background process
    # running that still holds the inherited stdout/stderr.
    import time

    start = time.monotonic()
    out = run_command(["sh", "-c", "cat >/dev/null; (sleep 5) &"], "secret", 3.0)
    assert out == ""
    assert time.monotonic() - start < 2.5


def test_writer_failure_reports_stderr():
    with pytest.raises(ClipboardError, match="boom"):
        run_command(["sh", "-c", "cat >/dev/null; echo boom >&2; exit 3"], "x", 5.0)
