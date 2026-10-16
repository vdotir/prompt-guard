"""Layer 1: deterministic detection with regex and entropy.

Purpose:
    Find secrets and structured personal data that have a known shape:
    private keys, cloud and API tokens, JWTs, credentials in URLs,
    "password = ..." style assignments, emails, IPs, phone numbers,
    internal hostnames (names ending in .lan, .internal, ...), the user's
    own domains, user and host names in shell prompts, sudo and ssh lines,
    the user's own words and patterns, and long random-looking strings
    (Shannon entropy). Returns Span objects; it never changes the text.

Path in repo:
    src/prompt_guard/rules.py

Relations:
    - Uses Span / resolve_overlaps from src/prompt_guard/spans.py.
    - Reads settings from Config.rules (src/prompt_guard/config.py),
      including internal_domains (HOSTNAME), private_domains (DOMAIN) and
      hide_private_ips.
    - Its spans feed the vault / redaction step (later step).
    - Tested in tests/test_rules.py.

How to run:
    Library module. Quick manual check:
        echo "mail me at someone@example.org" | python -m prompt_guard.rules
"""

from __future__ import annotations

import ipaddress
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass

from prompt_guard.config import RulesConfig
from prompt_guard.spans import Span, resolve_overlaps


@dataclass(frozen=True)
class Rule:
    """A built-in pattern. `group` is the regex group that holds the value."""

    kind: str
    pattern: re.Pattern[str]
    group: int = 0


def _rx(pattern: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(pattern, flags)


# Order matters only on equal-length overlaps: earlier = more specific.
BUILTIN_RULES: tuple[Rule, ...] = (
    Rule(
        "PRIVATE_KEY",
        _rx(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    ),
    Rule("AWS_KEY", _rx(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Rule("GITHUB_TOKEN", _rx(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    Rule("SLACK_TOKEN", _rx(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    Rule("API_KEY", _rx(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}")),
    Rule("GOOGLE_API_KEY", _rx(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    Rule("JWT", _rx(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    Rule("PASSWORD", _rx(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:([^/\s@]+)@", re.IGNORECASE), group=1),
    Rule(
        "BEARER_TOKEN",
        _rx(r"\bBearer\s+([A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE),
        group=1,
    ),
    Rule(
        "SECRET",
        _rx(
            r"""(?ix)
            \b(?:[a-z0-9]+[_-])*
              (?:pass(?:word|wd|phrase)?|pwd|secret|token|api[_-]?key|apikey
                 |access[_-]?key|private[_-]?key|client[_-]?secret|auth)
              (?:[_-][a-z0-9]+)*\b
            ["']?\s*[:=]\s*["']?
            ([^\s"',;]{6,})
            """
        ),
        group=1,
    ),
    # Shell prompt "user@host:~/dir$" and "user@host:/dir#": the host part.
    Rule(
        "HOSTNAME",
        _rx(r"(?<![\w@.-])[a-z_][a-z0-9_-]{0,31}@([A-Za-z0-9][A-Za-z0-9-]{0,62}):[~/]"),
        group=1,
    ),
    # ... and the user part, also in "[sudo] password for user:" and "ssh user@".
    Rule(
        "USERNAME",
        _rx(r"(?<![\w@.-])([a-z_][a-z0-9_-]{0,31})@[A-Za-z0-9][A-Za-z0-9-]{0,62}:[~/]"),
        group=1,
    ),
    Rule("USERNAME", _rx(r"\[sudo\] password for ([a-z_][a-z0-9_-]{0,31}):"), group=1),
    Rule(
        "USERNAME",
        _rx(r"\b(?:ssh|scp|sftp|rsync)\b[^\n@]*?\s([a-z_][a-z0-9_-]{0,31})@"),
        group=1,
    ),
    Rule("EMAIL", _rx(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    # IPv4; a trailing "-beta" style suffix means a version number, not an IP.
    Rule("IP", _rx(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.]|-[A-Za-z])")),
    # IPv6 candidates (at least two colons); validated with the ipaddress module.
    Rule("IP", _rx(r"(?<![\w:])(?=[0-9A-Fa-f:]*:[0-9A-Fa-f]*:)[0-9A-Fa-f:]{3,39}(?![\w:])")),
    Rule(
        "PHONE",
        _rx(r"(?<![\w+])(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)"),
    ),
    Rule("PHONE", _rx(r"(?<![\w+])\+\d{8,15}(?!\w)")),
)

# Full "scheme://user:password@" prefix; emails inside it are not real emails.
URL_CREDENTIALS = _rx(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@[^\s/:]+", re.IGNORECASE)
# Candidate tokens for the entropy check: long runs of key-like characters.
ENTROPY_CANDIDATE = _rx(r"[A-Za-z0-9+/_=\-]{8,}")
# Placeholders the vault writes, e.g. [[EMAIL_1]]: never redact them again.
PLACEHOLDER = _rx(r"\[\[[A-Z][A-Z0-9_]*_\d+\]\]")


def shannon_entropy(s: str) -> float:
    """Bits per character of s (0 for an empty string)."""
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def _looks_random(token: str, cfg: RulesConfig) -> bool:
    if len(token) < cfg.entropy_min_length:
        return False
    has_digit = any(ch.isdigit() for ch in token)
    has_alpha = any(ch.isalpha() for ch in token)
    if not (has_digit and has_alpha):
        return False  # plain words, long numbers, separators
    if "/" in token and token.count("/") > 2:
        return False  # file paths
    return shannon_entropy(token) > cfg.entropy_threshold


# Only reachable inside a local network (RFC 1918, carrier-grade NAT, loopback,
# link-local, IPv6 unique-local). Documentation ranges are not in this list.
LOCAL_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

# Account names that say nothing about the person; hiding them only confuses the AI.
COMMON_USERNAMES = {"root", "git", "admin", "ubuntu", "user", "www-data", "nobody"}


def parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def is_local_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Addresses that only mean something inside a local network."""
    return any(ip in net for net in LOCAL_NETWORKS if net.version == ip.version)


def domain_rule(domains: tuple[str, ...]) -> Rule:
    """The user's own domains: the domain itself and any subdomain, as DOMAIN."""
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    names = "|".join(re.escape(d) for d in sorted(domains, key=len, reverse=True))
    pattern = rf"(?<![\w.-])(?:{label}\.)*(?:{names})(?![\w-]|\.[A-Za-z0-9])"
    return Rule("DOMAIN", _rx(pattern, re.IGNORECASE))


def hostname_rule(domains: tuple[str, ...]) -> Rule:
    """Internal hostnames: one or more labels, then one of the given suffixes.

    "build-07.corp-internal.lan" is one HOSTNAME, so it is hidden whole and
    no part of it (".lan") stays visible. The suffix alone ("lan") is not
    matched: at least one label must come before it.
    """
    label = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    suffixes = "|".join(re.escape(d) for d in sorted(domains, key=len, reverse=True))
    pattern = rf"(?<![\w.-])(?:{label}\.)+(?:{suffixes})(?![\w-]|\.[A-Za-z0-9])"
    return Rule("HOSTNAME", _rx(pattern, re.IGNORECASE))


class RuleDetector:
    """Find spans with built-in rules plus the user's words and patterns."""

    def __init__(self, cfg: RulesConfig | None = None) -> None:
        self.cfg = cfg or RulesConfig()
        self.allow = {a.casefold() for a in self.cfg.allowlist}
        custom = [Rule(p.name, _rx(p.regex)) for p in self.cfg.patterns]
        words = [
            Rule("CUSTOM", _rx(r"(?<!\w)" + re.escape(w) + r"(?!\w)", re.IGNORECASE))
            for w in self.cfg.words
            if w.strip()
        ]
        hosts = [hostname_rule(self.cfg.internal_domains)] if self.cfg.internal_domains else []
        domains = [domain_rule(self.cfg.private_domains)] if self.cfg.private_domains else []
        # User rules come first so they win ties against built-in ones.
        self.rules: tuple[Rule, ...] = (*custom, *words, *domains, *hosts, *BUILTIN_RULES)

    def _keep(self, kind: str, value: str) -> bool:
        if not value.strip() or value.casefold() in self.allow:
            return False
        if PLACEHOLDER.fullmatch(value):
            return False
        if kind == "IP":
            ip = parse_ip(value)
            if ip is None:
                return False
            if not self.cfg.hide_private_ips and is_local_ip(ip):
                return False
        if kind == "USERNAME" and value in COMMON_USERNAMES:
            return False
        return True

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for rule in self.rules:
            for m in rule.pattern.finditer(text):
                start, end = m.span(rule.group)
                if start < 0 or end <= start:
                    continue
                if self._keep(rule.kind, text[start:end]):
                    spans.append(Span(start, end, rule.kind))
        url_creds = [m.span() for m in URL_CREDENTIALS.finditer(text)]
        spans = [
            s
            for s in spans
            if s.kind != "EMAIL" or all(s.end <= a or s.start >= b for a, b in url_creds)
        ]
        if self.cfg.entropy:
            for m in ENTROPY_CANDIDATE.finditer(text):
                token = m.group()
                if _looks_random(token, self.cfg) and self._keep("SECRET", token):
                    spans.append(Span(m.start(), m.end(), "SECRET"))
        # Never touch existing placeholders, even if a rule matched inside one.
        guarded = [p.span() for p in PLACEHOLDER.finditer(text)]
        spans = [s for s in spans if all(s.end <= a or s.start >= b for a, b in guarded)]
        return resolve_overlaps(spans)


def detect(text: str, cfg: RulesConfig | None = None) -> list[Span]:
    """Convenience wrapper: detect spans with one-off settings."""
    return RuleDetector(cfg).detect(text)


def main() -> None:
    text = sys.stdin.read()
    for span in detect(text):
        print(f"{span.kind:<14} {span.start:>6}-{span.end:<6} {span.value(text)!r}")


if __name__ == "__main__":
    main()
