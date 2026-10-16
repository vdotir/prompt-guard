"""prompt-guard package.

Purpose:
    Local, reversible redaction of secrets and personal data before text is
    pasted into an online AI chat. This file only marks the package and holds
    the version number.

Path in repo:
    src/prompt_guard/__init__.py

Relations:
    - pyproject.toml declares the same version.
    - tests/test_package.py checks that the package imports and the versions match.
    - Later modules (rules, vault, cli, clipboard, ner, llm) live next to this file.

How to run:
    Nothing to run yet. Check the import with:
        python -c "import prompt_guard; print(prompt_guard.__version__)"
"""

__version__ = "0.2.0"
