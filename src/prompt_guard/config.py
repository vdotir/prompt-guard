"""Configuration loading for prompt-guard.

Purpose:
    Read the user's TOML config, fill in defaults for everything missing,
    and validate it (unknown keys, bad types, invalid regexes) so mistakes
    show up at start instead of as silent leaks.

Path in repo:
    src/prompt_guard/config.py

Relations:
    - config.example.toml (repo root) documents every key with its default.
    - src/prompt_guard/rules.py reads Config.rules.
    - src/prompt_guard/vault.py reads Config.vault.
    - src/prompt_guard/clipboard.py reads Config.clipboard.
    - src/prompt_guard/ner.py reads Config.ner.
    - src/prompt_guard/llm.py reads Config.llm.
    - Tested in tests/test_config.py.

Config file location (first match wins):
    1. the path passed to load_config(path)
    2. $PROMPT_GUARD_CONFIG
    3. $XDG_CONFIG_HOME/prompt-guard/config.toml
       (default ~/.config/prompt-guard/config.toml)
    A missing file is fine: all defaults are used.

How to run:
    Library module. Quick check of the effective config:
        python -c "from prompt_guard.config import load_config; print(load_config())"
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from prompt_guard.spans import KIND_RE


class ConfigError(ValueError):
    """Raised when the config file is invalid."""


@dataclass(frozen=True)
class CustomPattern:
    name: str
    regex: str


@dataclass(frozen=True)
class LayersConfig:
    rules: bool = True
    ner: bool = False
    llm: bool = False


@dataclass(frozen=True)
class RulesConfig:
    entropy: bool = True
    entropy_threshold: float = 4.0
    entropy_min_length: int = 20
    words: tuple[str, ...] = ()
    allowlist: tuple[str, ...] = ("127.0.0.1", "0.0.0.0", "255.255.255.255", "localhost")
    patterns: tuple[CustomPattern, ...] = ()


@dataclass(frozen=True)
class VaultConfig:
    dir: str = "~/.local/state/prompt-guard"
    ttl_hours: float = 24.0  # sessions unused for longer are deleted; 0 = never


@dataclass(frozen=True)
class NerConfig:
    model: str = "knowledgator/gliner-pii-base-v1.0"
    threshold: float = 0.3  # model card: 0.3 to start, lower finds more, higher is stricter
    labels: tuple[str, ...] = (
        "name",
        "location address",
        "location street",
        "organization",
        "username",
    )
    device: str = "cpu"  # "cpu" or "cuda"
    max_chunk_words: int = 200  # text is split so each chunk fits the model's window
    offline_after_download: bool = True  # load from the local cache, no network check


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = "http://localhost:1234/v1"
    model: str = "qwen3-8b"
    api_key: str = "lm-studio"
    timeout: float = 120.0
    max_chunk_chars: int = 6000  # text per request; keep well inside the model's context
    max_tokens: int = 2048  # answer length limit per request
    structured_output: str = "json_schema"  # "json_schema", "json_object" or "none"


CLIPBOARD_BACKENDS = ("auto", "wayland", "x11", "wsl", "macos")


@dataclass(frozen=True)
class ClipboardConfig:
    backend: str = "auto"  # one of CLIPBOARD_BACKENDS
    timeout: float = 10.0  # seconds for one clipboard command


@dataclass(frozen=True)
class Config:
    layers: LayersConfig = field(default_factory=LayersConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    vault: VaultConfig = field(default_factory=VaultConfig)
    ner: NerConfig = field(default_factory=NerConfig)
    llm: LlmConfig = field(default_factory=LlmConfig)
    clipboard: ClipboardConfig = field(default_factory=ClipboardConfig)
    source: str | None = None  # path the config was read from, if any


SECTIONS = {
    "layers": LayersConfig,
    "rules": RulesConfig,
    "vault": VaultConfig,
    "ner": NerConfig,
    "llm": LlmConfig,
    "clipboard": ClipboardConfig,
}


def default_config_path() -> Path:
    env = os.environ.get("PROMPT_GUARD_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "prompt-guard" / "config.toml"


def _check_type(where: str, value: Any, default: Any) -> Any:
    """Validate one value against the type of its default."""
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{where}: expected true/false, got {value!r}")
        return value
    if isinstance(default, int | float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{where}: expected a number, got {value!r}")
        return type(default)(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ConfigError(f"{where}: expected a string, got {value!r}")
        return value
    if isinstance(default, tuple):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where}: expected a list of strings")
        return tuple(value)
    raise ConfigError(f"{where}: unsupported setting")


def _parse_patterns(raw: Any) -> tuple[CustomPattern, ...]:
    if not isinstance(raw, list):
        raise ConfigError("rules.patterns: expected a list of {name, regex} tables")
    result = []
    for i, item in enumerate(raw):
        where = f"rules.patterns[{i}]"
        if not isinstance(item, dict) or set(item) != {"name", "regex"}:
            raise ConfigError(f"{where}: needs exactly the keys 'name' and 'regex'")
        name, regex = item["name"], item["regex"]
        if not isinstance(name, str) or not KIND_RE.match(name):
            raise ConfigError(f"{where}: name must be UPPER_SNAKE_CASE, got {name!r}")
        if not isinstance(regex, str) or not regex:
            raise ConfigError(f"{where}: regex must be a non-empty string")
        try:
            re.compile(regex)
        except re.error as exc:
            raise ConfigError(f"{where}: invalid regex: {exc}") from exc
        result.append(CustomPattern(name=name, regex=regex))
    return tuple(result)


def _parse_section(name: str, cls: type, raw: Any) -> Any:
    if not isinstance(raw, dict):
        raise ConfigError(f"[{name}] must be a table")
    defaults = cls()
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"[{name}]: unknown key(s): {', '.join(sorted(unknown))}")
    values = {}
    for key, value in raw.items():
        if name == "rules" and key == "patterns":
            values[key] = _parse_patterns(value)
        else:
            values[key] = _check_type(f"{name}.{key}", value, getattr(defaults, key))
    return cls(**values)


def parse_config(data: dict[str, Any], source: str | None = None) -> Config:
    """Build a Config from an already-parsed TOML dict."""
    unknown = set(data) - set(SECTIONS)
    if unknown:
        raise ConfigError(f"unknown section(s): {', '.join(sorted(unknown))}")
    parts = {
        name: _parse_section(name, cls, data[name])
        for name, cls in SECTIONS.items()
        if name in data
    }
    cfg = Config(**parts, source=source)
    if not 0 < cfg.rules.entropy_threshold <= 8:
        raise ConfigError("rules.entropy_threshold: must be between 0 and 8")
    if cfg.rules.entropy_min_length < 8:
        raise ConfigError("rules.entropy_min_length: must be at least 8")
    if cfg.vault.ttl_hours < 0:
        raise ConfigError("vault.ttl_hours: must be 0 (never expire) or more")
    if cfg.clipboard.backend not in CLIPBOARD_BACKENDS:
        raise ConfigError(f"clipboard.backend: must be one of {', '.join(CLIPBOARD_BACKENDS)}")
    if cfg.clipboard.timeout <= 0:
        raise ConfigError("clipboard.timeout: must be more than 0")
    if not 0 < cfg.ner.threshold < 1:
        raise ConfigError("ner.threshold: must be between 0 and 1")
    if not cfg.llm.base_url.startswith(("http://", "https://")):
        raise ConfigError("llm.base_url: must start with http:// or https://")
    if cfg.llm.timeout <= 0:
        raise ConfigError("llm.timeout: must be more than 0")
    if not 500 <= cfg.llm.max_chunk_chars <= 100_000:
        raise ConfigError("llm.max_chunk_chars: must be between 500 and 100000")
    if not 64 <= cfg.llm.max_tokens <= 32_768:
        raise ConfigError("llm.max_tokens: must be between 64 and 32768")
    if cfg.llm.structured_output not in ("json_schema", "json_object", "none"):
        raise ConfigError('llm.structured_output: must be "json_schema", "json_object" or "none"')
    if cfg.ner.device not in ("cpu", "cuda"):
        raise ConfigError('ner.device: must be "cpu" or "cuda"')
    if not 20 <= cfg.ner.max_chunk_words <= 350:
        raise ConfigError("ner.max_chunk_words: must be between 20 and 350")
    if not cfg.ner.labels:
        raise ConfigError("ner.labels: needs at least one label")
    return cfg


def load_config(path: str | Path | None = None) -> Config:
    """Load the config file, or return defaults if it does not exist.

    An explicitly given path that does not exist is an error.
    """
    explicit = path is not None
    p = Path(path).expanduser() if explicit else default_config_path()
    if not p.exists():
        if explicit:
            raise ConfigError(f"config file not found: {p}")
        return Config()
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{p}: {exc}") from exc
    return parse_config(data, source=str(p))
