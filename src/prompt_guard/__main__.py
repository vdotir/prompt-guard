"""Allow "python -m prompt_guard".

Purpose:
    Run the CLI without the installed "prompt-guard" / "pgd" scripts.

Path in repo:
    src/prompt_guard/__main__.py

Relations:
    - Calls main() in src/prompt_guard/cli.py.

How to run:
    python -m prompt_guard --help
"""

from prompt_guard.cli import main

raise SystemExit(main())
