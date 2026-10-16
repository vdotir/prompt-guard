"""Tests for layer 3 (local LLM review).

Purpose:
    Check the request sent to the server, parsing of the model's answer
    (think blocks, code fences, wrong shapes), that only exact values in the
    original text become spans, that already-hidden values are not sent, and
    that errors stop the run. A fake HTTP function replaces the server; one
    optional test talks to a real server and is skipped unless
    PROMPT_GUARD_LLM_TEST=1 is set.

Path in repo:
    tests/test_llm.py

Relations:
    - Tests src/prompt_guard/llm.py and its use in src/prompt_guard/pipeline.py.

How to run:
    pytest tests/test_llm.py
    PROMPT_GUARD_LLM_TEST=1 pytest tests/test_llm.py   # also a real server from your config
"""

import json
import os

import pytest

from prompt_guard.config import Config, LayersConfig, LlmConfig, load_config
from prompt_guard.llm import (
    LlmReviewer,
    LlmUnavailable,
    http_json,
    list_models,
    mask_text,
    parse_items,
    split_text,
)
from prompt_guard.pipeline import detect_all
from prompt_guard.spans import Span


class FakeServer:
    """Answers chat requests with given items; records requests."""

    def __init__(self, items=(), content=None):
        self.items = list(items)
        self.content = content
        self.requests = []

    def __call__(self, url, payload, headers, timeout):
        self.requests.append((url, payload, headers))
        if payload is None:
            return {"data": [{"id": "qwen3-8b"}, {"id": "other-model"}]}
        content = self.content
        if content is None:
            content = json.dumps({"items": [{"value": v, "type": t} for v, t in self.items]})
        return {"choices": [{"message": {"content": content}}]}


def review(text, items, known=(), cfg=None, allowlist=()):
    server = FakeServer(items)
    spans = LlmReviewer(cfg or LlmConfig(), allowlist, http=server).review(text, list(known))
    return [(s.kind, s.value(text)) for s in spans], server


def test_request_shape():
    _, server = review("hello build-07", [])
    url, payload, headers = server.requests[0]
    assert url == "http://localhost:1234/v1/chat/completions"
    assert payload["model"] == "qwen3-8b"
    assert payload["temperature"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["messages"][0]["role"] == "system"
    assert "hello build-07" in payload["messages"][1]["content"]
    assert headers["Authorization"] == "Bearer lm-studio"


@pytest.mark.parametrize(("mode", "has_format"), [("json_object", True), ("none", False)])
def test_structured_output_modes(mode, has_format):
    _, server = review("x", [], cfg=LlmConfig(structured_output=mode))
    assert ("response_format" in server.requests[0][1]) is has_format


def test_exact_values_become_spans():
    text = "Ask Bob Marsh on build-07.corp.lan, then Bob Marsh again."
    found, _ = review(text, [("Bob Marsh", "PERSON"), ("build-07.corp.lan", "HOSTNAME")])
    assert found == [
        ("PERSON", "Bob Marsh"),
        ("HOSTNAME", "build-07.corp.lan"),
        ("PERSON", "Bob Marsh"),
    ]


def test_values_not_in_text_are_ignored():
    found, _ = review("nothing here", [("Invented Name", "PERSON")])
    assert found == []


def test_value_inside_longer_word_is_ignored():
    found, _ = review("the falconry club", [("falcon", "ORG")])
    assert found == []


def test_generic_words_short_values_and_allowlist_ignored():
    text = "password: ab and token for Helpdesk"
    items = [("password", "SECRET"), ("ab", "PASSWORD"), ("Helpdesk", "ORG")]
    found, _ = review(text, items, allowlist=("helpdesk",))
    assert found == []


def test_known_spans_are_masked_and_not_doubled():
    text = "mail jane@example.org to Bob Marsh"
    known = [Span(5, 21, "EMAIL")]
    found, server = review(text, [("jane@example.org", "EMAIL"), ("Bob Marsh", "PERSON")], known)
    sent = server.requests[0][1]["messages"][1]["content"]
    assert "jane@example.org" not in sent
    assert "[[EMAIL_1]]" in sent
    assert found == [("PERSON", "Bob Marsh")]


def test_placeholders_from_model_are_ignored():
    found, _ = review("see [[EMAIL_1]]", [("[[EMAIL_1]]", "EMAIL"), ("EMAIL_1]]", "EMAIL")])
    assert found == []


def test_unknown_type_becomes_sensitive():
    found, _ = review("code ZX-99-ALPHA", [("ZX-99-ALPHA", "OTHER")])
    assert found == [("SENSITIVE", "ZX-99-ALPHA")]


@pytest.mark.parametrize(
    "content",
    [
        '<think>let me see</think>{"items": [{"value": "Bob Marsh", "type": "PERSON"}]}',
        '```json\n{"items": [{"value": "Bob Marsh", "type": "PERSON"}]}\n```',
        'Sure! {"items": [{"value": "Bob Marsh", "type": "person"}]}',
    ],
)
def test_parse_tolerates_wrappers(content):
    assert parse_items(content) == [("Bob Marsh", "PERSON")]


@pytest.mark.parametrize("content", ["no json here", '{"other": []}', "{broken"])
def test_parse_rejects_bad_answers(content):
    with pytest.raises(LlmUnavailable):
        parse_items(content)


def test_bad_answer_stops_review():
    server = FakeServer(content="I cannot help with that.")
    with pytest.raises(LlmUnavailable):
        LlmReviewer(http=server).review("Bob Marsh", [])


def test_long_text_sent_in_pieces():
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(40)) + "\nBob Marsh\n"
    found, server = review(text, [("Bob Marsh", "PERSON")], cfg=LlmConfig(max_chunk_chars=600))
    assert len(server.requests) > 1
    assert ("PERSON", "Bob Marsh") in found


def test_split_text_limits_and_keeps_content():
    text = "a" * 1500 + "\nshort line\n" + "b" * 100
    pieces = split_text(text, 500)
    assert all(len(p) <= 500 for p in pieces)
    assert "".join(pieces) == text


def test_mask_text():
    text = "a jane@example.org b 192.0.2.1"
    spans = [Span(2, 18, "EMAIL"), Span(21, 30, "IP")]
    assert mask_text(text, spans) == "a [[EMAIL_1]] b [[IP_1]]"


def test_list_models():
    assert list_models(LlmConfig(), http=FakeServer()) == ["qwen3-8b", "other-model"]


def test_unreachable_server_is_clear_error():
    cfg = LlmConfig(base_url="http://127.0.0.1:9/v1", timeout=2)
    with pytest.raises(LlmUnavailable, match="cannot reach"):
        list_models(cfg, http=http_json)


def test_pipeline_runs_all_layers():
    text = "mail jane@example.org to Bob Marsh"
    cfg = Config(layers=LayersConfig(llm=True))
    server = FakeServer([("Bob Marsh", "PERSON")])
    spans = detect_all(text, cfg, llm_reviewer=LlmReviewer(cfg.llm, http=server)).spans
    assert [(s.kind, s.value(text)) for s in spans] == [
        ("EMAIL", "jane@example.org"),
        ("PERSON", "Bob Marsh"),
    ]


@pytest.mark.skipif(
    os.environ.get("PROMPT_GUARD_LLM_TEST") != "1",
    reason="set PROMPT_GUARD_LLM_TEST=1 to use the LLM server from your config",
)
def test_real_server_finds_a_hostname():
    cfg = load_config()
    text = "Deploy failed on host build-07.corp-internal.lan, ask Margaret Thompson."
    spans = LlmReviewer(cfg.llm).review(text, [])
    values = {s.value(text) for s in spans}
    assert values & {"build-07.corp-internal.lan", "Margaret Thompson"}


def test_http_json_against_local_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            answer = json.dumps({"echo": body["model"], "auth": self.headers["Authorization"]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(answer.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        answer = http_json(url, {"model": "m"}, {"Authorization": "Bearer k"}, 5)
        assert answer == {"echo": "m", "auth": "Bearer k"}
    finally:
        server.shutdown()
