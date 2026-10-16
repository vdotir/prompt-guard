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
    - Layer 3: src/prompt_guard/llm.py. It sees the text with the spans of
      layers 1 and 2 already hidden, and only adds spans for exact values.
      An unreachable server is an error, never a silent skip.
    - Called by src/prompt_guard/cli.py; spans go to src/prompt_guard/vault.py.
    - Tested in tests/test_pipeline.py.

How to run:
    Library module, no entry point. Tests:
        pytest tests/test_pipeline.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from prompt_guard.config import Config
from prompt_guard.llm import LlmReviewer
from prompt_guard.ner import NerDetector
from prompt_guard.rules import RuleDetector
from prompt_guard.spans import Span, resolve_overlaps


@dataclass
class Detection:
    spans: list[Span]
    notes: list[str] = field(default_factory=list)  # warnings for the user


def detect_all(
    text: str,
    cfg: Config,
    *,
    ner_detector: NerDetector | None = None,
    llm_reviewer: LlmReviewer | None = None,
) -> Detection:
    """Run the enabled layers. Rule spans come first, so they win equal-length ties.

    Raises prompt_guard.ner.NerUnavailable or prompt_guard.llm.LlmUnavailable
    if an enabled layer cannot run.
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
        reviewer = llm_reviewer or LlmReviewer(cfg.llm, cfg.rules.allowlist)
        found = resolve_overlaps(spans)
        spans = found + reviewer.review(text, found)
    if not layers.rules:
        notes.append("layer 'rules' is disabled: secrets and keys will not be detected")
    return Detection(resolve_overlaps(spans), notes)
