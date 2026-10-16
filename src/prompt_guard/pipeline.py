"""Detection pipeline: run the enabled layers and merge their spans.

Purpose:
    One place that decides which detection layers run, in which order, and
    merges their results into one non-overlapping span list. The CLI only
    talks to this module, so adding the NER and LLM layers later does not
    change the CLI.

Path in repo:
    src/prompt_guard/pipeline.py

Relations:
    - Layer 1: src/prompt_guard/rules.py.
    - Layer 2: src/prompt_guard/ner.py (optional extra; a missing install is
      an error, never a silent skip).
    - Layer 3 (llm.py) is added in a later step; until then, enabling it in
      the config gives a note.
    - Called by src/prompt_guard/cli.py; spans go to src/prompt_guard/vault.py.
    - Tested in tests/test_pipeline.py.

How to run:
    Library module, no entry point. Tests:
        pytest tests/test_pipeline.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prompt_guard.config import Config
from prompt_guard.ner import NerDetector
from prompt_guard.rules import RuleDetector
from prompt_guard.spans import Span, resolve_overlaps


@dataclass
class Detection:
    spans: list[Span]
    notes: list[str] = field(default_factory=list)  # warnings for the user


def detect_all(text: str, cfg: Config, *, ner_detector: NerDetector | None = None) -> Detection:
    """Run the enabled layers. Rule spans come first, so they win equal-length ties.

    Raises prompt_guard.ner.NerUnavailable if layer 2 is enabled but cannot run.
    """
    spans: list[Span] = []
    notes: list[str] = []
    layers = cfg.layers
    if layers.rules:
        spans += RuleDetector(cfg.rules).detect(text)
    if layers.ner:
        detector = ner_detector or NerDetector(cfg.ner, cfg.rules.allowlist)
        spans += detector.detect(text)
    if layers.llm:
        notes.append("layer 'llm' is enabled but not available in this version; skipped")
    if not layers.rules:
        notes.append("layer 'rules' is disabled: secrets and keys will not be detected")
    return Detection(resolve_overlaps(spans), notes)
