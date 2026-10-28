"""agents/llm.py: provider chain, per-agent first model, token budget, fallthrough rules (§8.0). No network."""

import json
from types import SimpleNamespace

import pytest

from agents import llm

MODELS = "openai/gpt-oss-120b,openai/gpt-oss-20b"


@pytest.fixture
def env(monkeypatch):
    for k, v in {"LLM_ENABLED": "true", "LLM_FORCE_FAIL": "false", "LLM_CACHE": "off", "LLM_PROVIDERS": "groq",
                 "GROQ_BASE_URL": "https://example.invalid/v1", "GROQ_MODEL": MODELS, "GROQ_API_KEY": "test-key",
                 "LLM_TPM_LIMIT": "8000", "LLM_NOTES_FIRST_MODEL": "", "LLM_ASSISTANT_FIRST_MODEL": "openai/gpt-oss-20b",
                 "LLM_NOTES_TPM_SHARE": "1.0"}.items():
        monkeypatch.setenv(k, v)
    return monkeypatch


def fake_post(script):
    """script: {model: status or 'json'}; records the models called, in order."""
    calls = []

    def post(url, json=None, timeout=None, headers=None):      # noqa: A002 - mirrors requests.post
        model = json["model"]
        calls.append(model)
        outcome = script.get(model, 200)
        if outcome == "garbage":
            body = {"choices": [{"message": {"content": "not json"}}]}
            return SimpleNamespace(status_code=200, json=lambda: body)
        if outcome != 200:
            return SimpleNamespace(status_code=outcome, json=lambda: {})
        body = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 900,
                                                                                 "completion_tokens": 300}}
        return SimpleNamespace(status_code=200, json=lambda: body)
    return post, calls


def test_disabled_and_forced_failure_never_touch_the_network(env):
    post, calls = fake_post({})
    env.setattr(llm.requests, "post", post)
    env.setenv("LLM_ENABLED", "false")
    assert llm.Client("notes").complete_json("s", "u").reason == "disabled"
    env.setenv("LLM_ENABLED", "true")
    env.setenv("LLM_FORCE_FAIL", "true")
    assert llm.Client("notes").complete_json("s", "u").reason == "forced_failure"
    assert calls == []


def test_each_agent_starts_with_its_own_model(env):
    assert [t.model for t in llm.Client("notes").chain] == MODELS.split(",")
    assert [t.model for t in llm.Client("assistant").chain] == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    assert "test-key" not in repr(llm.Client("notes").chain)          # keys never appear in logs or reprs


def test_429_invalid_json_and_errors_fall_through_to_the_next_model(env):
    post, calls = fake_post({"openai/gpt-oss-120b": 429})
    env.setattr(llm.requests, "post", post)
    r = llm.Client("notes").complete_json("s", "u")
    assert r.ok and r.model == "openai/gpt-oss-20b" and r.attempts == [("openai/gpt-oss-120b", "HTTP 429")]
    post, calls = fake_post({"openai/gpt-oss-120b": "garbage", "openai/gpt-oss-20b": 503})
    env.setattr(llm.requests, "post", post)
    r = llm.Client("notes").complete_json("s", "u")
    assert not r.ok and r.reason == "all_failed" and calls == MODELS.split(",")


def test_a_429_backs_that_model_off_for_a_minute(env):
    post, calls = fake_post({"openai/gpt-oss-120b": 429})
    env.setattr(llm.requests, "post", post)
    client = llm.Client("notes")
    client.complete_json("s", "u")
    client.complete_json("s", "u2")
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"]


def test_the_local_budget_skips_a_model_before_the_provider_would_refuse(env):
    post, calls = fake_post({})
    env.setattr(llm.requests, "post", post)
    env.setenv("LLM_NOTES_TPM_SHARE", "0.5")                      # 4,000 tokens/min for this process
    client = llm.Client("notes")
    for i in range(5):
        client.complete_json("s", f"u{i}", max_tokens=1000)      # each records 1,200 tokens; checked as ~1,000
    # The full max_tokens counts (§11.10): after 3,600 used a 4th request of up to 1,000 would pass 4,000.
    assert calls == ["openai/gpt-oss-120b"] * 3 + ["openai/gpt-oss-20b"] * 2


def test_a_preferred_model_goes_first_and_the_chain_follows(env):
    post, calls = fake_post({"openai/gpt-oss-20b": 429})
    env.setattr(llm.requests, "post", post)
    client = llm.Client("notes")
    assert client.complete_json("s", "u", prefer="openai/gpt-oss-20b").model == "openai/gpt-oss-120b"
    assert calls == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]


def test_a_daily_limit_blocks_that_model_until_the_provider_says(env):
    """Live run 28 Oct: Groq's tokens-per-day limit answers 429 with retry-after ~20 min; retrying every minute
    only wastes requests."""
    calls = []

    def post(url, json=None, timeout=None, headers=None):    # noqa: A002
        calls.append(json["model"])
        if json["model"] == "openai/gpt-oss-120b":
            return SimpleNamespace(status_code=429, json=lambda: {}, headers={"retry-after": "1179"})
        body = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}
        return SimpleNamespace(status_code=200, json=lambda: body, headers={})
    env.setattr(llm.requests, "post", post)
    client = llm.Client("notes")
    assert client.complete_json("s", "u1").model == "openai/gpt-oss-20b"
    client.budget.used.clear()                                     # a minute later: the 1-minute back-off is over
    assert client.complete_json("s", "u2").model == "openai/gpt-oss-20b"
    assert calls == ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "openai/gpt-oss-20b"]   # 120b not asked again


def test_budget_window_rolls_over():
    b = llm.TokenBudget(1000)
    b.record("m", 900, now=0.0)
    assert not b.allows("m", 200, now=30.0) and b.allows("m", 200, now=61.0)


def test_the_cache_answers_repeats_without_a_call(env, tmp_path):
    post, calls = fake_post({})
    env.setattr(llm.requests, "post", post)
    env.setenv("LLM_CACHE", "on")
    env.setattr(llm, "ROOT", tmp_path)
    client = llm.Client("notes")
    first, second = client.complete_json("s", "u"), client.complete_json("s", "u")
    assert first.ok and second.cached and json.dumps(second.data) == '{"ok": true}' and len(calls) == 1


def test_a_call_blocked_only_by_the_local_budget_waits_for_it(env):
    post, calls = fake_post({})
    env.setattr(llm.requests, "post", post)
    client = llm.Client("notes")
    for t in client.chain:
        client.budget.record(t.model, client.budget.limit, now=llm.time.time() - 58.5)   # frees in ~1.5 s
    started = llm.time.time()
    assert client.complete_json("s", "u", wait_s=5).ok
    assert 1.0 <= llm.time.time() - started < 5 and calls == ["openai/gpt-oss-120b"]
    for t in client.chain:
        client.budget.record(t.model, client.budget.limit)
    assert client.complete_json("s", "u2").reason == "all_failed"                    # no waiting by default


def test_a_request_larger_than_the_share_runs_alone_once_the_model_is_idle(env):
    """Live run 28 Oct: a consolidation (~5,000 tokens with its max_tokens) never fitted the notes' 4,800 share."""
    b = llm.TokenBudget(4800, ceiling=8000)
    assert b.allows("m", 5000, now=0.0)                          # nothing used: may run alone
    b.record("m", 1400, now=0.0)
    assert not b.allows("m", 5000, now=45.0) and b.allows("m", 5000, now=61.0)
    assert not llm.TokenBudget(4800, ceiling=8000).allows("m", 9000)   # never above the provider's limit
