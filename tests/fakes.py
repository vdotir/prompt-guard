"""Fake secrets for tests, built at runtime.

Purpose:
    The repo is public and GitHub push protection scans every push. Writing
    token-shaped strings literally in the source could trigger it. This
    module builds clearly fake values from pieces at runtime, so no
    token-shaped literal is ever committed.

Path in repo:
    tests/fakes.py

Relations:
    - Imported by tests/test_rules.py and later test modules.

How to run:
    Not run directly; imported by pytest tests.
"""

from __future__ import annotations


def _join(*parts: str) -> str:
    return "".join(parts)


FAKE_AWS_KEY = _join("AK", "IA", "FAKE" * 4)
FAKE_GITHUB_TOKEN = _join("gh", "p_", "FakeToken0" * 4)
FAKE_SLACK_TOKEN = _join("xo", "xb-", "0000-fake-fake-fake")
FAKE_API_KEY = _join("s", "k-", "fakefake" * 4)
FAKE_GOOGLE_KEY = _join("AI", "za", "Fake" * 8, "abc")
FAKE_JWT = _join("ey", "J", "fakeheader01", ".", "ey", "J", "fakepayload02", ".", "fakesignature03")
FAKE_PEM = _join(
    "-----BEGIN ",
    "PRIVATE KEY-----\n",
    "FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE\n",
    "-----END ",
    "PRIVATE KEY-----",
)
# Random-looking but obviously fake (mixed letters and digits, high entropy).
FAKE_RANDOM = _join("q7Zr2Lw9", "Xk4Tn8Vb", "1Hm6Pd3J")
