"""Test package marker.

Purpose:
    Makes tests/ a package so tests can import shared helpers (tests/fakes.py).

Path in repo:
    tests/__init__.py

Relations:
    - Imported implicitly by pytest; tests use "from tests import fakes".

How to run:
    Not run directly.
"""
