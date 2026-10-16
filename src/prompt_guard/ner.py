"""Layer 2: named-entity detection with a GLiNER PII model.

Purpose:
    Find personal data that has no fixed shape: names, street addresses,
    organizations, usernames. Uses a GLiNER model (zero-shot NER) running
    locally with torch. The model sees the text in chunks that fit its window;
    span offsets are mapped back to the full text.

    gliner and torch are optional dependencies (extra "ner"). They are only
    imported when this layer is used, so layer 1 works without them.

    Privacy: the model is downloaded from Hugging Face once. With
    offline_after_download (default), later runs load it from the local cache
    and make no network request at all. Text never leaves the machine.

Path in repo:
    src/prompt_guard/ner.py

Relations:
    - Settings from Config.ner (src/prompt_guard/config.py); allowlist from
      Config.rules.
    - Returns Span objects (src/prompt_guard/spans.py).
    - Called by src/prompt_guard/pipeline.py.
    - Tested in tests/test_ner.py with a fake model (no download needed).

How to run:
    Library module. Try it on some text (downloads the model the first time):
        echo "Send it to Jane Doe at 12 Example Road" | python -m prompt_guard.ner
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from typing import Any, Protocol

from prompt_guard.config import NerConfig
from prompt_guard.spans import Span, normalize_kind, resolve_overlaps

PLACEHOLDER_RE = re.compile(r"\[\[[A-Z][A-Z0-9_]*_\d+\]\]")
WORD_RE = re.compile(r"\S+")

# Friendly placeholder kinds for common labels; other labels are normalized
# ("vehicle id" -> VEHICLE_ID).
LABEL_KINDS = {
    "name": "PERSON",
    "person": "PERSON",
    "first name": "PERSON",
    "last name": "PERSON",
    "location address": "ADDRESS",
    "location street": "ADDRESS",
    "street_address": "ADDRESS",
    "street address": "ADDRESS",
    "address": "ADDRESS",
    "organization": "ORG",
    "company": "ORG",
    "username": "USERNAME",
    "user_name": "USERNAME",
    "user name": "USERNAME",
}

TRIM = " \t\r\n.,;:!?\"'()[]{}<>"


class NerUnavailable(RuntimeError):
    """Raised when the optional NER dependencies or the model are missing."""


class EntityModel(Protocol):
    def predict_entities(
        self, text: str, labels: list[str], threshold: float = 0.5
    ) -> list[dict[str, Any]]: ...


def label_kind(label: str) -> str:
    return LABEL_KINDS.get(label.strip().lower(), normalize_kind(label))


def chunks(text: str, max_words: int) -> Iterator[tuple[int, str]]:
    """Yield (offset, chunk) pieces of at most max_words words.

    Pieces end at a line break when possible, so a name is rarely cut in half.
    """
    words = list(WORD_RE.finditer(text))
    i = 0
    while i < len(words):
        j = min(i + max_words, len(words))
        if j < len(words):
            # Prefer to end the chunk after a word followed by a newline.
            for k in range(j - 1, i, -1):
                gap = text[words[k].end() : words[k + 1].start()]
                if "\n" in gap:
                    j = k + 1
                    break
        start, end = words[i].start(), words[j - 1].end()
        yield start, text[start:end]
        i = j


def load_model(cfg: NerConfig) -> EntityModel:
    """Load the GLiNER model; local cache first, download only if needed."""
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    try:
        from gliner import GLiNER
    except ImportError as exc:
        raise NerUnavailable(
            "layer 'ner' needs the optional extra: install torch (CPU) and run "
            'pip install -e ".[ner]" (see docs/runbook.md), or disable it with --no-ner'
        ) from exc
    if cfg.offline_after_download:
        try:
            return GLiNER.from_pretrained(cfg.model, local_files_only=True, map_location=cfg.device)
        except Exception:  # not cached yet: fall through to download
            pass
    try:
        return GLiNER.from_pretrained(cfg.model, map_location=cfg.device)
    except Exception as exc:  # report any loader failure the same way
        raise NerUnavailable(f"cannot load NER model {cfg.model!r}: {exc}") from exc


class NerDetector:
    def __init__(
        self,
        cfg: NerConfig | None = None,
        allowlist: tuple[str, ...] = (),
        model: EntityModel | None = None,
    ) -> None:
        self.cfg = cfg or NerConfig()
        self.allow = {a.casefold() for a in allowlist}
        self._model = model

    @property
    def model(self) -> EntityModel:
        if self._model is None:
            self._model = load_model(self.cfg)
        return self._model

    def _span(self, text: str, start: int, end: int, label: str) -> Span | None:
        # Trim punctuation and spaces the model sometimes includes.
        while start < end and text[start] in TRIM:
            start += 1
        while end > start and text[end - 1] in TRIM:
            end -= 1
        value = text[start:end]
        if len(value) < 2 or value.casefold() in self.allow:
            return None
        return Span(start, end, label_kind(label))

    def detect(self, text: str) -> list[Span]:
        if not text.strip():
            return []
        labels = list(self.cfg.labels)
        spans: list[Span] = []
        for offset, piece in chunks(text, self.cfg.max_chunk_words):
            for ent in self.model.predict_entities(piece, labels, threshold=self.cfg.threshold):
                span = self._span(
                    text, offset + int(ent["start"]), offset + int(ent["end"]), str(ent["label"])
                )
                if span is not None:
                    spans.append(span)
        guarded = [m.span() for m in PLACEHOLDER_RE.finditer(text)]
        spans = [s for s in spans if all(s.end <= a or s.start >= b for a, b in guarded)]
        return resolve_overlaps(spans)


def main() -> None:
    text = sys.stdin.read()
    try:
        spans = NerDetector().detect(text)
    except NerUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    for span in spans:
        print(f"{span.kind:<10} {span.start:>6}-{span.end:<6} {span.value(text)!r}")


if __name__ == "__main__":
    main()
