# Runbook

How to set up, test, and work on prompt-guard. This file is updated with every step.

## Requirements

- Python 3.10 or newer
- git
- GitHub CLI (`gh`), only for creating the repository

## Development setup

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

## Usage

Not available yet. See the status table in README.md.
