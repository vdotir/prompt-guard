"""Command-line interface: prompt-guard (short name: pgd).

Purpose:
    redact    hide secrets and personal data before pasting into an online AI
    restore   put the real values back into the AI's reply
    clear     delete one session (or all) from the vault
    sessions  list the sessions in the vault
    llm-check test the connection to the LLM server and list its models

    Input and output default to the clipboard. If stdin is a pipe or a file,
    it is read instead; if stdout is a pipe or a file, the result goes there.
    -i and -o force stdin/stdout. Messages and the --show review go to stderr, so
    they never end up in the clipboard or the output file.

Path in repo:
    src/prompt_guard/cli.py

Relations:
    - Entry points "prompt-guard" and "pgd" in pyproject.toml; also
      src/prompt_guard/__main__.py for "python -m prompt_guard".
    - Uses config.py, pipeline.py (rules.py, ner.py, llm.py), vault.py,
      restore.py, clipboard.py.
    - Tested in tests/test_cli.py.

How to run:
    prompt-guard redact --show
    prompt-guard redact --ner --show
    prompt-guard redact --ner --llm --show
    prompt-guard llm-check
    prompt-guard restore
    prompt-guard redact -i -o < input.txt > redacted.txt
    prompt-guard --help
"""

from __future__ import annotations

import argparse
import dataclasses
import io as _io
import os
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from typing import TextIO

from prompt_guard import __version__
from prompt_guard.clipboard import Clipboard, ClipboardError
from prompt_guard.config import Config, ConfigError, load_config
from prompt_guard.llm import LlmUnavailable, list_models
from prompt_guard.ner import NerUnavailable
from prompt_guard.pipeline import detect_all
from prompt_guard.restore import restore
from prompt_guard.vault import (
    DEFAULT_SESSION,
    Replacement,
    Vault,
    VaultError,
    clear_all,
    clear_session,
    list_sessions,
)

EXIT_OK = 0
EXIT_ERROR = 1


class CliError(RuntimeError):
    """An error to report to the user without a traceback."""


def mask(value: str) -> str:
    """Show just enough of a value to recognize it, e.g. 'sk-f…ke (32 chars)'."""
    flat = value.replace("\n", " ")
    n = len(value)
    if n <= 4:
        shown = "*" * n
    elif n < 12:
        shown = f"{flat[:1]}…{flat[-1:]}"
    else:
        shown = f"{flat[:4]}…{flat[-2:]}"
    return f"{shown} ({n} chars)"


def is_redirected(stream: TextIO) -> bool:
    """True if the stream is a pipe or a regular file.

    A terminal, /dev/null or a socket (for example when started from a desktop
    shortcut) is not redirected, so the clipboard is used. Streams without a
    file descriptor (tests) count as redirected.
    """
    try:
        mode = os.fstat(stream.fileno()).st_mode
    except (OSError, ValueError, _io.UnsupportedOperation):
        return True
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)


class Io:
    """Where input comes from and where output goes."""

    def __init__(
        self,
        args: argparse.Namespace,
        cfg: Config,
        stdin: TextIO,
        stdout: TextIO,
        clipboard: Clipboard | None,
    ) -> None:
        self.use_stdin = args.stdin or is_redirected(stdin)
        self.use_stdout = args.stdout or is_redirected(stdout)
        self.stdin, self.stdout = stdin, stdout
        self._clipboard = clipboard
        self.cfg = cfg

    @property
    def clipboard(self) -> Clipboard:
        if self._clipboard is None:
            try:
                self._clipboard = Clipboard.from_config(self.cfg.clipboard)
            except ClipboardError as exc:
                raise CliError(str(exc)) from exc
        return self._clipboard

    def read(self) -> str:
        if self.use_stdin:
            return self.stdin.read()
        try:
            return self.clipboard.read()
        except ClipboardError as exc:
            raise CliError(f"cannot read clipboard: {exc}") from exc

    def write(self, text: str) -> str:
        """Write the result; return a short description of where it went."""
        if self.use_stdout:
            self.stdout.write(text)
            self.stdout.flush()
            return "written to stdout"
        try:
            self.clipboard.write(text)
        except ClipboardError as exc:
            raise CliError(f"cannot write clipboard: {exc}") from exc
        return "copied to clipboard"


def _summary(reps: list[Replacement]) -> str:
    counts = Counter(r.kind for r in reps)
    return ", ".join(f"{kind} {n}" for kind, n in sorted(counts.items()))


def cmd_redact(args, cfg, io, err) -> int:
    text = io.read()
    if not text.strip():
        raise CliError("input is empty: nothing to redact")
    layers = cfg.layers
    if args.ner is not None:
        layers = dataclasses.replace(layers, ner=args.ner)
    if args.llm is not None:
        layers = dataclasses.replace(layers, llm=args.llm)
    cfg = dataclasses.replace(cfg, layers=layers)
    if cfg.layers.ner:
        print(f"Running NER layer ({cfg.ner.model}, {cfg.ner.device})...", file=err)
    if cfg.layers.llm:
        print(f"Asking LLM ({cfg.llm.model} at {cfg.llm.base_url})...", file=err)
    try:
        detection = detect_all(text, cfg)
    except (NerUnavailable, LlmUnavailable) as exc:
        raise CliError(str(exc)) from exc
    for note in detection.notes:
        print(f"note: {note}", file=err)
    vault = Vault.open(cfg.vault, args.session)
    out, reps = vault.redact(text, detection.spans)
    if reps:
        vault.save()
    where = io.write(out)
    if not reps:
        print(f"No sensitive values found; text unchanged, {where}.", file=err)
        return EXIT_OK
    unique = {r.placeholder: r for r in reps}
    print(
        f"Redacted {len(reps)} value(s), {len(unique)} unique ({_summary(list(unique.values()))})"
        f" in session '{args.session}'; {where}.",
        file=err,
    )
    if args.show:
        width = max(len(p) for p in unique)
        for r in unique.values():
            print(f"  {r.placeholder:<{width}}  {mask(r.value)}", file=err)
    print("Check the text before you paste it.", file=err)
    return EXIT_OK


def cmd_restore(args, cfg, io, err) -> int:
    vault = Vault.open(cfg.vault, args.session)
    if not vault.forward:
        raise CliError(f"session '{args.session}' is empty or expired: nothing to restore with")
    text = io.read()
    result = restore(text, vault)
    vault.save()  # marks the session as used, so it does not expire mid-chat
    where = io.write(result.text)
    print(
        f"Restored {result.restored} placeholder(s) from session '{args.session}'; {where}.",
        file=err,
    )
    if result.unknown:
        print(
            "warning: unknown placeholder(s), left unchanged (the AI may have invented them): "
            + ", ".join(result.unknown),
            file=err,
        )
    return EXIT_OK


def cmd_clear(args, cfg, io, err) -> int:
    if args.all:
        names = clear_all(cfg.vault)
        print(f"Deleted {len(names)} session(s).", file=err)
    elif clear_session(cfg.vault, args.session):
        print(f"Deleted session '{args.session}'.", file=err)
    else:
        print(f"Session '{args.session}' does not exist.", file=err)
    return EXIT_OK


def cmd_sessions(args, cfg, io, err) -> int:
    names = list_sessions(cfg.vault)
    for name in names:
        io.stdout.write(name + "\n")
    if not names:
        print("No sessions.", file=err)
    return EXIT_OK


def cmd_llm_check(args, cfg, io, err) -> int:
    print(f"Server: {cfg.llm.base_url}", file=err)
    try:
        models = list_models(cfg.llm)
    except LlmUnavailable as exc:
        raise CliError(str(exc)) from exc
    for model in models:
        mark = "*" if model == cfg.llm.model else " "
        io.stdout.write(f"{mark} {model}\n")
    if cfg.llm.model in models:
        print(f"OK: model '{cfg.llm.model}' is available.", file=err)
        return EXIT_OK
    print(
        f"Model '{cfg.llm.model}' is not in this list. Set [llm] model to one of the ids "
        "above, or load the model in LM Studio.",
        file=err,
    )
    return EXIT_ERROR


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c",
        "--config",
        help="config file (default: $PROMPT_GUARD_CONFIG or ~/.config/prompt-guard/config.toml)",
    )
    common.add_argument(
        "-s",
        "--session",
        default=DEFAULT_SESSION,
        help=f"session name, one per AI chat (default: {DEFAULT_SESSION})",
    )
    io_opts = argparse.ArgumentParser(add_help=False)
    io_opts.add_argument(
        "-i", "--stdin", action="store_true", help="read stdin instead of the clipboard"
    )
    io_opts.add_argument(
        "-o", "--stdout", action="store_true", help="write stdout instead of the clipboard"
    )

    parser = argparse.ArgumentParser(
        prog="prompt-guard",
        description="Hide secrets and personal data before pasting into an online AI chat, "
        "and put them back into the reply. Everything stays on this machine.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("redact", parents=[common, io_opts], help="hide sensitive values")
    p.add_argument(
        "--show", action="store_true", help="list what was hidden (values partly masked) on stderr"
    )
    p.add_argument(
        "--ner",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="turn layer 2 (names, addresses, organizations) on or off for this run; "
        "default from the config",
    )
    p.add_argument(
        "--llm",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="turn layer 3 (local LLM review) on or off for this run; default from the config",
    )
    p.set_defaults(func=cmd_redact)

    p = sub.add_parser(
        "restore", parents=[common, io_opts], help="put real values back into the AI's reply"
    )
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("clear", parents=[common], help="delete a session from the vault")
    p.add_argument("--all", action="store_true", help="delete all sessions")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("sessions", parents=[common], help="list sessions in the vault")
    p.set_defaults(func=cmd_sessions, stdin=False, stdout=True)

    p = sub.add_parser(
        "llm-check", parents=[common], help="test the LLM server and list its models"
    )
    p.set_defaults(func=cmd_llm_check, stdin=False, stdout=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    clipboard: Clipboard | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    err = stderr or sys.stderr
    args = build_parser().parse_args(argv)
    args.stdin = getattr(args, "stdin", False)
    args.stdout = getattr(args, "stdout", False)
    try:
        cfg = load_config(args.config)
        io = Io(args, cfg, stdin, stdout, clipboard)
        return args.func(args, cfg, io, err)
    except (CliError, ConfigError, VaultError) as exc:
        print(f"prompt-guard: error: {exc}", file=err)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("prompt-guard: interrupted", file=err)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
