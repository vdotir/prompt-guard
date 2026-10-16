"""Smoke tests for the package skeleton.

Purpose:
    Make sure the package imports and its version matches pyproject.toml.

Path in repo:
    tests/test_package.py

Relations:
    - Tests src/prompt_guard/__init__.py.
    - Reads pyproject.toml from the repo root.

How to run:
    pytest
"""

import re
from pathlib import Path

import prompt_guard

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_set():
    assert re.fullmatch(r"\d+\.\d+\.\d+", prompt_guard.__version__)


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == prompt_guard.__version__
