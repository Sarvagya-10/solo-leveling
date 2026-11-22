"""AI provider clients tested with mocked HTTP (no network, no real keys)."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from shogun.ai import workflows
from shogun.ai.errors import (
    AIAuthError,
    AINotConfiguredError,
    AIRateLimitError,
    AIResponseError,
    AIUnavailableError,
)
from shogun.ai.groq_client import GroqClient, ModelInfo, choose_model, rank_models
from shogun.ai.schemas import RevisionCardDraft
from shogun.ai.search_client import SerpApiClient, _safe_url, html_to_text
from shogun.config import Secret, load_config
from shogun.logging_setup import RedactingFilter, redact

FAKE_KEY = Secret("gsk_" + "x" * 40)
NO_SLEEP = lambda _s: None  # noqa: E731


def transport(handler):
    return httpx.MockTransport(handler)


def models_payload(*ids):
    return {"object": "list", "data": [{"id": i, "owned_by": "x", "active": True} for i in ids]}


def test_missing_keys_raise_configuration_error():
    with pytest.raises(AINotConfiguredError, match="GROQ_API_KEY"):
        GroqClient(Secret(None))
    with pytest.raises(AINotConfiguredError, match="SERPAPI_API_KEY"):
        SerpApiClient(Secret(""))
    with pytest.raises(AINotConfiguredError):
        GroqClient(Secret("your-groq-api-key-here"))


def test_secret_never_rendered():
    s = Secret("gsk_supersecretvalue1234567890")
    assert "supersecret" not in repr(s) and "supersecret" not in str(s)
    cfg = load_config(override={"GROQ_API_KEY": "gsk_supersecretvalue1234567890"})
    assert "supersecret" not in repr(cfg)


def test_log_redaction():
    text = redact("calling https://serpapi.com/search?q=x&api_key=abcdef123456 with gsk_ABCDEFGHIJKLMNOP123")
    assert "abcdef123456" not in text and "gsk_ABCDEFGHIJKLMNOP123" not in text
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "key=%s", ("gsk_ABCDEFGHIJKLMNOPQRS",), None)
    RedactingFilter().filter(record)
    assert "gsk_" not in record.getMessage()


def test_model_ranking_and_choice():
    models = [ModelInfo(m, None, None, True) for m in
              ["whisper-large-v3", "llama-3.1-8b-instant", "llama-3.3-70b-versatile", "meta-llama/llama-guard-4-12b"]]
    ranked = [m.id for m in rank_models(models)]
    assert ranked == ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    assert choose_model(models, None)[0] == "llama-3.3-70b-versatile"
    assert choose_model(models, "llama-3.1-8b-instant")[0] == "llama-3.1-8b-instant"
    chosen, why = choose_model(models, "gone-model")
    assert chosen == "llama-3.3-70b-versatile" and "not available" in why
    unknown = [ModelInfo("vendor/newmodel-405b", None, None, True), ModelInfo("vendor/small-7b", None, None, True)]
    assert rank_models(unknown)[0].id == "vendor/newmodel-405b"


def test_auth_error_is_clean():
    client = GroqClient(FAKE_KEY, transport=transport(lambda r: httpx.Response(401, json={})), sleep=NO_SLEEP)
    with pytest.raises(AIAuthError) as exc:
        client.list_models()
    assert "gsk_" not in str(exc.value)


def test_rate_limit_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "1"}, json={})
        return httpx.Response(200, json=models_payload("llama-3.3-70b-versatile"))

    client = GroqClient(FAKE_KEY, transport=transport(handler), sleep=NO_SLEEP)
    assert client.list_models()[0].id == "llama-3.3-70b-versatile"
    assert calls["n"] == 3


def test_rate_limit_exhausted():
    client = GroqClient(FAKE_KEY, max_retries=1, transport=transport(lambda r: httpx.Response(429, json={})),
                        sleep=NO_SLEEP)
    with pytest.raises(AIRateLimitError):
        client.list_models()


def test_network_failure_maps_to_unavailable():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    client = GroqClient(FAKE_KEY, max_retries=1, transport=transport(handler), sleep=NO_SLEEP)
    with pytest.raises(AIUnavailableError):
        client.list_models()


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


CARD = {
    "basic_idea": "Eigenvalues are scalars lambda with Av = lambda v for non-zero v.",
    "essential_formulae": [{"name": "Characteristic equation", "expression": "det(A - lambda I) = 0", "note": None}],
    "question_types": [{"type": "Find eigenvalues", "recognition": "Small matrix given"}],
    "common_traps": ["Forgetting algebraic multiplicity"],
    "extra_observations": ["Trace equals sum of eigenvalues"],
    "connected_topic_codes": ["DA.2.13", "DA.9.99"],
    "practice_questions": [
        {"qtype": "MCQ", "marks": 1, "stem": "Eigenvalues of [[2,0],[0,3]] are?",
         "options": ["2 and 3", "1 and 6", "0 and 5", "2 and 2"], "answer_key": "A", "nat_low": None,
         "nat_high": None, "explanation": "Diagonal entries."},
        {"qtype": "NAT", "marks": 2, "stem": "Trace of [[1,2],[3,4]] equals?", "options": [],
         "answer_key": None, "nat_low": 5, "nat_high": 5, "explanation": "1 + 4 = 5."},
    ],
}


def test_chat_json_validates_and_retries_on_bad_output():
    replies = iter(["not json at all", "<think>hmm</think>" + json.dumps(CARD)])

    def handler(request):
        return _chat_response(next(replies))

    client = GroqClient(FAKE_KEY, transport=transport(handler), sleep=NO_SLEEP)
    draft, _ = client.chat_json("m", [{"role": "user", "content": "x"}], RevisionCardDraft)
    assert draft.essential_formulae[0].name == "Characteristic equation"


def test_chat_json_gives_up_after_second_invalid():
    client = GroqClient(FAKE_KEY, transport=transport(lambda r: _chat_response("{}")), sleep=NO_SLEEP)
    with pytest.raises(AIResponseError):
        client.chat_json("m", [{"role": "user", "content": "x"}], RevisionCardDraft)


def test_serpapi_search_and_errors():
    def handler(request):
        assert request.url.params["engine"] == "duckduckgo"
        return httpx.Response(200, json={"organic_results": [
            {"position": 1, "title": "GATE DA 2024 paper", "link": "https://gate.example/da2024", "snippet": "s"},
            {"position": 2, "title": "bad", "link": "javascript:alert(1)", "snippet": ""},
        ]})

    client = SerpApiClient(Secret("k" * 64), transport=transport(handler), sleep=NO_SLEEP)
    results = client.search("gate da pyq")
    assert [r.link for r in results] == ["https://gate.example/da2024"]
    bad = SerpApiClient(Secret("k" * 64), transport=transport(lambda r: httpx.Response(200, json={"error": "Invalid API key."})),
                        sleep=NO_SLEEP)
    with pytest.raises(AIAuthError):
        bad.search("x")


def test_url_safety_and_html_text():
    for url in ("file:///etc/passwd", "http://localhost/x", "http://127.0.0.1/", "http://10.0.0.5/a"):
        with pytest.raises(AIResponseError):
            _safe_url(url)
    assert _safe_url("https://gate2027.iitm.ac.in/") == "https://gate2027.iitm.ac.in/"
    text = html_to_text("<html><script>x=1</script><p>Hello</p><p>World</p></html>")
    assert "x=1" not in text and text.split() == ["Hello", "World"]


def test_hallucination_guard():
    src = "Q.27 In GATE 2024 the following was asked: Let X be a random variable with mean 3 and variance 4."
    assert workflows.appears_in(src, "Let X be a random variable with mean 3 and variance 4.")
    assert not workflows.appears_in(src, "Let Y be a Poisson random variable with rate 7 find P(Y=0)")
