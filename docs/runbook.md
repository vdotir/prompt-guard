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

## Tests and fake secrets

The repo is public and GitHub push protection scans every push. Tests never contain token-shaped literals: `tests/fakes.py` builds obviously fake tokens from pieces at runtime. Follow the same rule for new tests.

## Usage

The CLI is not available yet. See the status table in README.md.
