"""Tests for layer 1 (regex + entropy rules).

Purpose:
    Check that each built-in rule finds its value, that harmless text stays
    untouched (no false positives on versions, hashes, paths, placeholders),
    and that user words, patterns and the allowlist work.

Path in repo:
    tests/test_rules.py

Relations:
    - Tests src/prompt_guard/rules.py.
    - Uses fake secrets from tests/fakes.py.

How to run:
    pytest tests/test_rules.py
"""

import pytest

from prompt_guard.config import CustomPattern, RulesConfig
from prompt_guard.rules import RuleDetector, detect, shannon_entropy
from tests import fakes


def found(text, cfg=None):
    """Return (kind, value) pairs found in text."""
    return [(s.kind, s.value(text)) for s in detect(text, cfg)]


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        ("AWS_KEY", fakes.FAKE_AWS_KEY),
        ("GITHUB_TOKEN", fakes.FAKE_GITHUB_TOKEN),
        ("SLACK_TOKEN", fakes.FAKE_SLACK_TOKEN),
        ("API_KEY", fakes.FAKE_API_KEY),
        ("GOOGLE_API_KEY", fakes.FAKE_GOOGLE_KEY),
        ("JWT", fakes.FAKE_JWT),
        ("PRIVATE_KEY", fakes.FAKE_PEM),
        ("EMAIL", "jane.doe@example.org"),
        ("IP", "203.0.113.7"),
        ("IP", "2001:db8::1"),
        ("PHONE", "+1 555 010 0199"),
        ("PHONE", "(555) 010-0199"),
    ],
)
def test_builtin_rule_finds_value(kind, value):
    text = f"before {value} after"
    assert found(text) == [(kind, value)]


def test_url_password_only_password_is_redacted():
    text = "DATABASE_URL=postgres://app:Sup3rS3cret@db.internal:5432/main"
    assert ("PASSWORD", "Sup3rS3cret") in found(text)


def test_assignment_secret():
    assert found('db_password = "hunter2hunter2"') == [("SECRET", "hunter2hunter2")]
    assert found("API_KEY: abcdef123456") == [("SECRET", "abcdef123456")]


def test_bearer_token():
    text = "Authorization: Bearer abcdefghijklmnop1234"
    assert ("BEARER_TOKEN", "abcdefghijklmnop1234") in found(text)


def test_entropy_catches_random_string():
    assert found(f"value {fakes.FAKE_RANDOM} end") == [("SECRET", fakes.FAKE_RANDOM)]


@pytest.mark.parametrize(
    "text",
    [
        "version 1.2.3 and 10.4.2.1-beta",
        "commit 0123456789abcdef0123456789abcdef01234567",
        "path /usr/local/lib/python3/site-packages/foo",
        "the function getUserAccountSettingsById returns",
        "number 1234567890123456789012",
        "already redacted [[EMAIL_1]] and [[API_KEY_12]]",
        "server listens on 127.0.0.1 and localhost",
        "plain sentence with nothing sensitive in it.",
        "invalid ip 999.999.999.999",
    ],
)
def test_no_false_positives(text):
    assert found(text) == []


def test_entropy_can_be_disabled():
    cfg = RulesConfig(entropy=False)
    assert found(f"value {fakes.FAKE_RANDOM}", cfg) == []


def test_custom_words_case_insensitive_whole_word():
    cfg = RulesConfig(words=("Project-Falcon",))
    text = "We ship project-falcon today; project-falcons is another word."
    assert found(text, cfg) == [("CUSTOM", "project-falcon")]


def test_custom_pattern_has_priority():
    cfg = RulesConfig(patterns=(CustomPattern("TICKET", r"\bACME-\d{4}\b"),))
    assert found("see ACME-1234", cfg) == [("TICKET", "ACME-1234")]


def test_allowlist():
    cfg = RulesConfig(allowlist=("noreply@example.org",))
    text = "from noreply@example.org to jane@example.org"
    assert found(text, cfg) == [("EMAIL", "jane@example.org")]


def test_spans_do_not_overlap_and_are_sorted():
    text = f"key={fakes.FAKE_API_KEY} mail=a@b.co ip=198.51.100.2"
    spans = RuleDetector().detect(text)
    assert spans == sorted(spans)
    for a, b in zip(spans, spans[1:], strict=False):
        assert a.end <= b.start


def test_shannon_entropy():
    assert shannon_entropy("") == 0
    assert shannon_entropy("aaaa") == 0
    assert shannon_entropy("ab") == 1


def test_time_is_not_ipv6():
    assert found("started at 12:30:45 and ended") == []


def test_mailto_email_still_found():
    assert found("contact mailto:jane@example.org") == [("EMAIL", "jane@example.org")]


def test_mixed_config_file():
    text = "\n".join(
        [
            "[server]",
            "host = 192.0.2.10",
            "admin_email = ops@example.org",
            f"aws_access_key_id = {fakes.FAKE_AWS_KEY}",
            "redis = redis://default:r3disPass@cache.example.org:6379",
            "timeout = 30",
        ]
    )
    kinds = {kind for kind, _ in found(text)}
    assert kinds == {"IP", "EMAIL", "AWS_KEY", "PASSWORD"}
    assert ("PASSWORD", "r3disPass") in found(text)


@pytest.mark.parametrize(
    "host",
    [
        "build-07.corp-internal.lan",
        "nas.local",
        "db1.prod.internal",
        "printer.home.arpa",
        "GIT.Example.CORP",
    ],
)
def test_internal_hostname_is_one_span(host):
    text = f"Deploy failed on {host}, retry"
    assert found(text) == [("HOSTNAME", host)]


def test_hostname_in_url_keeps_port_and_path():
    text = "open http://build-07.lan:8080/status now"
    assert found(text) == [("HOSTNAME", "build-07.lan")]


@pytest.mark.parametrize(
    "text",
    [
        "see github.com and docs.python.org",
        "the lan is down",
        "file report.local.txt",
        "module config.internal_value",
    ],
)
def test_public_domains_and_lookalikes_not_hostnames(text):
    assert [k for k, _ in found(text) if k == "HOSTNAME"] == []


def test_custom_internal_domain():
    cfg = RulesConfig(internal_domains=("corp.example.com",))
    text = "ssh to jump1.corp.example.com, not www.example.com"
    assert found(text, cfg) == [("HOSTNAME", "jump1.corp.example.com")]


def test_email_wins_over_hostname():
    assert found("mail ops@build.lan") == [("EMAIL", "ops@build.lan")]


def test_shell_prompt_user_and_host():
    text = "ru@srv:~/tunnel-guard$ sudo tunnel-guard server status"
    assert found(text) == [("USERNAME", "ru"), ("HOSTNAME", "srv")]


def test_root_prompt_keeps_root_visible():
    assert found("root@web-01:/etc# ls") == [("HOSTNAME", "web-01")]


def test_sudo_password_line():
    assert found("[sudo] password for ru: ") == [("USERNAME", "ru")]


@pytest.mark.parametrize("cmd", ["ssh", "scp file", "rsync -av ./x", "sftp -P 2222"])
def test_ssh_style_user(cmd):
    text = f"{cmd} deploy@203.0.113.9"
    kinds = found(text)
    assert ("USERNAME", "deploy") in kinds
    assert ("IP", "203.0.113.9") in kinds


def test_user_at_host_without_prompt_is_not_username():
    # an email-like "name@host" without ":~" or ssh is left to the email rule
    assert [k for k, _ in found("mail ru@srv now") if k == "USERNAME"] == []


def test_private_domain_and_subdomains():
    cfg = RulesConfig(private_domains=("example-shop.ir",))
    text = (
        "nginx site /etc/nginx/sites-enabled/example-shop.ir, api.example-shop.ir and "
        "WWW.EXAMPLE-SHOP.IR; not example-shop.ir.backup or myexample-shop.ir"
    )
    values = [v for k, v in found(text, cfg) if k == "DOMAIN"]
    assert values == ["example-shop.ir", "api.example-shop.ir", "WWW.EXAMPLE-SHOP.IR"]


def test_email_on_private_domain_stays_email():
    cfg = RulesConfig(private_domains=("example-shop.ir",))
    assert found("write to ops@example-shop.ir", cfg) == [("EMAIL", "ops@example-shop.ir")]


@pytest.mark.parametrize(
    "ip", ["10.77.0.2", "192.168.1.238", "172.16.4.1", "100.64.0.9", "fd00::1", "127.0.0.1"]
)
def test_private_ips_can_stay_visible(ip):
    cfg = RulesConfig(hide_private_ips=False, allowlist=())
    assert found(f"addr {ip} here", cfg) == []
    assert found(f"addr {ip} here", RulesConfig(allowlist=())) == [("IP", ip)]


def test_public_ip_always_hidden():
    cfg = RulesConfig(hide_private_ips=False)
    assert found("endpoint 203.0.113.9:443", cfg) == [("IP", "203.0.113.9")]
