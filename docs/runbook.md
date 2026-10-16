# Runbook

How to set up, test, and work on prompt-guard. This file is updated with every step.

## Requirements

- Python 3.11 or newer, with the venv module (on Debian/Ubuntu: the `python3.X-venv` package that matches your Python version)
- git
- GitHub CLI (`gh`), only for creating the repository

## Development setup

If `python3 -m venv` says ensurepip is not available, install the venv package first (replace 3.14 with your Python version):

```bash
sudo apt install python3.14-venv
```

```bash
cd ~/prompt-guard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Install for daily use

The same venv works for development and daily use. `pip install -e .` creates two commands in the venv: `prompt-guard` and its short name `pgd`.

To use `pgd` without activating the venv, link it into `~/.local/bin` (on Ubuntu this folder is already on PATH after you log in again):

```bash
mkdir -p ~/.local/bin && ln -sf ~/prompt-guard/.venv/bin/pgd ~/.local/bin/pgd && ln -sf ~/prompt-guard/.venv/bin/prompt-guard ~/.local/bin/prompt-guard
```

### Clipboard tools

prompt-guard uses the system's clipboard tools. Install the one for your desktop:

Ubuntu with Wayland (default on recent Ubuntu):

```bash
sudo apt install wl-clipboard
```

Ubuntu with X11:

```bash
sudo apt install xclip
```

WSL uses `powershell.exe` from Windows; nothing to install. macOS has `pbcopy` and `pbpaste` built in.

Check which clipboard backend is picked:

```bash
python -m prompt_guard.clipboard
```

To force one, set `backend` under `[clipboard]` in the config (`wayland`, `x11`, `wsl`, `macos`).

Ubuntu in a VMware VM: copy and paste between the VM and the host needs open-vm-tools-desktop in the VM. prompt-guard only works on the VM's own clipboard; VMware tools carry it to the host.

```bash
sudo apt install open-vm-tools-desktop
```

## Checks before every commit

```bash
ruff check .
ruff format --check .
pytest
```

## Repository rules

- All code, comments, file names, and docs are in English.
- Every code file starts with a header comment: purpose, path in repo, relations, how to run.
- Every part has pytest tests and passes ruff.
- The repo is public: no real names, IPs, hostnames, or keys. Test fixtures use obviously fake secrets.
- Local config (`config.toml`) and vault files are in `.gitignore` and are never committed.

## Configuration

Create the config from the example and edit it:

```bash
mkdir -p ~/.config/prompt-guard && cp config.example.toml ~/.config/prompt-guard/config.toml
```

Use another file for one run:

```bash
PROMPT_GUARD_CONFIG=/path/to/config.toml python -c "from prompt_guard.config import load_config; print(load_config())"
```

A typo in a key name, a wrong type, or an invalid regex stops the program with a clear error. This is on purpose: a silently ignored rule would mean a silent leak.

## Layer 1: rules

Built-in kinds: PRIVATE_KEY, AWS_KEY, GITHUB_TOKEN, SLACK_TOKEN, API_KEY, GOOGLE_API_KEY, JWT, PASSWORD (in URLs), BEARER_TOKEN, SECRET (key = value assignments and high-entropy strings), EMAIL, IP (v4 and v6), PHONE, plus CUSTOM (your words) and your own pattern names.

Try layer 1 on any text:

```bash
echo "mail ops@example.org, DB=postgres://u:pa55word@db:5432/x" | python -m prompt_guard.rules
```

Tuning:

- Too many harmless strings flagged as SECRET: raise `entropy_threshold` (for example 4.3) or `entropy_min_length`.
- A value that must stay visible: add it to `allowlist`.
- A secret format that is not caught: add a `[[rules.patterns]]` entry.

## Session vault

Each chat with an online AI should use its own session. Without a session name, the session `default` is used.

- Placeholders look like `[[EMAIL_1]]`. Within a session the same value always gets the same placeholder, also in later messages. A value already in the vault is hidden again even if no detector finds it the next time.
- Files: `~/.local/state/prompt-guard/<session>.json` (change with `[vault] dir`). The folder has mode 0700 and each file 0600. If the permissions get looser, they are tightened again on the next run.
- Expiry: a session not used for `ttl_hours` (default 24) is deleted the next time any session is opened. `ttl_hours = 0` keeps sessions until you clear them.
- The vault file holds every real value of the session. Do not copy it, back it up, or put it under git.

Check the vault folder and its permissions:

```bash
ls -la ~/.local/state/prompt-guard/
```

## Restore

Restore replaces placeholders in the AI's reply with the real values. It also accepts the forms chats often produce: `[[ X_1 ]]`, `\[\[X_1\]\]`, `[X_1]`, `<X_1>`, `&lt;X_1&gt;`. Single brackets and angle brackets are only replaced when the placeholder is in the vault, so normal text such as `[ITEM_1]` stays as it is.

A `[[X_N]]` placeholder that is not in the vault is left unchanged and reported as unknown. Usually the AI invented it; check that part of the reply by hand.

Tip: tell the online AI once at the start of the chat to keep `[[...]]` placeholders exactly as they are.

## Tests and fake secrets

The repo is public and GitHub push protection scans every push. Tests never contain token-shaped literals: `tests/fakes.py` builds obviously fake tokens from pieces at runtime. Follow the same rule for new tests.

## Usage

### Daily workflow

1. Copy the text for the AI (code, log, config, message).
2. Redact the clipboard and review what was hidden:

```bash
pgd redact --show
```

3. Paste into the online chat. Before sending, look at the text once more.
4. Copy the AI's reply, then restore your real values into the clipboard:

```bash
pgd restore
```

5. When the chat is over, delete its session:

```bash
pgd clear
```

### One session per chat

Placeholder numbers belong to a session. Use a name per chat so two chats do not mix:

```bash
pgd redact -s backup-script --show
```

```bash
pgd restore -s backup-script
```

List and delete sessions:

```bash
pgd sessions
```

```bash
pgd clear --all
```

### Pipes and files

If stdin is a pipe or a file, it is read instead of the clipboard. If stdout is a pipe or a file, the result goes there. `-i` and `-o` force stdin/stdout.

```bash
pgd redact < app.log > app.safe.log
```

```bash
journalctl -u myservice -n 200 | pgd redact -s logs | less
```

Messages and the `--show` list always go to stderr, so they never end up in the clipboard or the output file. `--show` masks values (for example `ops@…rg (15 chars)`), so real secrets do not stay in the terminal scrollback.

### Exit codes

- 0: done (also when nothing was found, or when restore warns about unknown placeholders)
- 1: error (bad config, empty input, empty or expired session, no clipboard tool); nothing is written
- 2: wrong command-line usage

### Troubleshooting

- `no desktop session found`: there is no DISPLAY, WAYLAND_DISPLAY or WSL, for example over SSH. Use pipes, or `-i` and `-o`.
- `no clipboard tool found`: install the tool named in the message (see "Clipboard tools").
- `session 'default' is empty or expired`: the session was cleared or not used for `ttl_hours`. Restore needs the same session that redacted the text.
- `unknown placeholder(s)`: the AI wrote a placeholder that was never created. Check that part of the reply by hand.
