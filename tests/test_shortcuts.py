"""Tests for GNOME keyboard shortcuts.

Purpose:
    Check the commands written into gsettings, that existing user shortcuts
    are kept, that install is idempotent, and that remove only touches
    prompt-guard's own entries. A fake gsettings stores values in a dict.

Path in repo:
    tests/test_shortcuts.py

Relations:
    - Tests src/prompt_guard/shortcuts.py.

How to run:
    pytest tests/test_shortcuts.py
"""

import pytest

from prompt_guard.shortcuts import (
    BASE,
    LIST_KEY,
    SCHEMA,
    GnomeShortcuts,
    ShortcutError,
    build,
    gnome_available,
    manual_instructions,
    parse_list,
)

USER_PATH = f"{BASE}custom0/"


class FakeGsettings:
    def __init__(self):
        self.values = {(SCHEMA, LIST_KEY): f"['{USER_PATH}']"}
        self.resets = []

    def __call__(self, argv):
        cmd = argv[1]
        if cmd == "list-schemas":
            return f"org.gnome.desktop.interface\n{SCHEMA}\n"
        schema, key = argv[2], argv[3]
        if cmd == "get":
            value = self.values.get((schema, key), "''")
            return value if key == LIST_KEY else repr(value)
        if cmd == "set":
            self.values[(schema, key)] = argv[4]
            return ""
        if cmd == "reset":
            self.resets.append((schema, key))
            self.values.pop((schema, key), None)
            return ""
        raise AssertionError(argv)


def shortcuts_for_test(**kw):
    return build(pgd="/home/u/prompt-guard/.venv/bin/pgd", **kw)


def test_build_commands():
    redact, restore = shortcuts_for_test(redact_args="--ner --llm")
    assert redact.command == "/home/u/prompt-guard/.venv/bin/pgd redact --notify --ner --llm"
    assert restore.command == "/home/u/prompt-guard/.venv/bin/pgd restore --notify"
    assert redact.binding == "<Control><Alt>r"
    assert restore.binding == "<Control><Alt>u"


def test_build_quotes_paths_with_spaces():
    redact, _ = build(pgd="/home/u/my tools/pgd")
    assert redact.command.startswith("'/home/u/my tools/pgd' redact")


@pytest.mark.parametrize(
    ("output", "paths"),
    [("@as []", []), ("['/a/', '/b/']", ["/a/", "/b/"]), ("['/a/']\n", ["/a/"])],
)
def test_parse_list(output, paths):
    assert parse_list(output) == paths


def test_parse_list_rejects_garbage():
    with pytest.raises(ShortcutError):
        parse_list("not a list")


def test_install_keeps_user_shortcuts_and_is_idempotent():
    fake = FakeGsettings()
    gnome = GnomeShortcuts(fake)
    wanted = shortcuts_for_test()
    gnome.install(wanted)
    gnome.install(wanted)
    paths = parse_list(fake.values[(SCHEMA, LIST_KEY)])
    assert paths == [USER_PATH, wanted[0].path, wanted[1].path]
    active = gnome.show(wanted)
    assert [b for _, b, _ in active] == ["<Control><Alt>r", "<Control><Alt>u"]


def test_remove_only_ours():
    fake = FakeGsettings()
    gnome = GnomeShortcuts(fake)
    wanted = shortcuts_for_test()
    gnome.install(wanted)
    assert gnome.remove(wanted) == 2
    assert parse_list(fake.values[(SCHEMA, LIST_KEY)]) == [USER_PATH]
    assert gnome.show(wanted) == []


def test_gnome_available():
    assert gnome_available(which=lambda n: "/usr/bin/gsettings", runner=FakeGsettings()) is True
    assert gnome_available(which=lambda n: None, runner=FakeGsettings()) is False


def test_manual_instructions_list_commands():
    text = manual_instructions(shortcuts_for_test())
    assert "redact --notify" in text and "restore --notify" in text


class FakeGnome:
    installed = []

    def __init__(self, *args):
        pass

    def install(self, wanted):
        FakeGnome.installed = wanted


@pytest.mark.parametrize(
    ("flags", "suffix"),
    [
        ([], "redact --notify"),
        (["--ner"], "redact --notify --ner"),
        (["--ner", "--llm"], "redact --notify --ner --llm"),
    ],
)
def test_cli_install_flags(tmp_path, monkeypatch, flags, suffix):
    import io

    from prompt_guard import shortcuts
    from prompt_guard.cli import main

    monkeypatch.setattr(shortcuts, "gnome_available", lambda: True)
    monkeypatch.setattr(shortcuts, "GnomeShortcuts", FakeGnome)
    monkeypatch.setattr(shortcuts, "pgd_path", lambda: "/venv/bin/pgd")
    cfg = tmp_path / "c.toml"
    cfg.write_text("")
    code = main(
        ["shortcuts", "install", "-c", str(cfg), *flags], stdout=io.StringIO(), stderr=io.StringIO()
    )
    assert code == 0
    assert FakeGnome.installed[0].command == f"/venv/bin/pgd {suffix}"
