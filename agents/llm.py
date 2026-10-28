"""Free-tier LLM client (docs/ARCHITECTURE.md §8.0, A12).

One OpenAI-compatible chat-completions call, tried over a chain of (provider, model) pairs:
  * LLM_PROVIDERS=groq; each provider has <NAME>_BASE_URL, <NAME>_MODEL (a comma-separated list, tried
    in order) and <NAME>_API_KEY in .env. Keys are never logged.
  * Each agent starts its chain with a different model (LLM_NOTES_FIRST_MODEL, LLM_ASSISTANT_FIRST_MODEL),
    so the Note Agent and the assistant don't drain the same free per-minute quota (rev 6 review).
  * A per-process token budget per model (rolling 60 s, LLM_TPM_LIMIT x share) skips a model before the
    provider would answer HTTP 429.
  * HTTP 429 / 5xx / timeouts / network errors / invalid JSON move to the next model; no retry loops.
    If everything fails the caller uses its deterministic fallback.
  * LLM_ENABLED=false (everyday development) and LLM_FORCE_FAIL=true (fault demo F5) fail fast.
  * LLM_CACHE=on (development and rehearsals only): data/llm_cache.sqlite, keyed by model and prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import requests

from common.config import ROOT

TIMEOUT_S = 15


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _flag(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Target:
    provider: str
    base_url: str
    model: str
    key: str = field(repr=False)


@dataclass
class Result:
    ok: bool
    data: dict | None = None
    model: str | None = None
    latency_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: list = field(default_factory=list)       # [(model, reason)]
    reason: str | None = None                          # why it failed overall
    cached: bool = False

    @property
    def tokens(self) -> int:
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


def targets(first_model: str | None = None) -> list[Target]:
    """The configured chain, with `first_model` moved to the front if present."""
    chain = []
    for name in [p.strip() for p in _env("LLM_PROVIDERS", "groq").split(",") if p.strip()]:
        prefix = name.upper()
        base, key = _env(f"{prefix}_BASE_URL").rstrip("/"), _env(f"{prefix}_API_KEY")
        for model in [m.strip() for m in _env(f"{prefix}_MODEL").split(",") if m.strip()]:
            if base and key:
                chain.append(Target(name, base, model, key))
    if first_model:
        chain.sort(key=lambda t: t.model != first_model)      # stable: the rest keep their order
    return chain


class TokenBudget:
    """Rolling 60 s token count per model for this process."""

    def __init__(self, limit_per_min: int) -> None:
        self.limit = limit_per_min
        self.used: dict[str, deque] = {}
        self.lock = threading.Lock()

    def _window(self, model: str, now: float) -> deque:
        q = self.used.setdefault(model, deque())
        while q and now - q[0][0] > 60:
            q.popleft()
        return q

    def allows(self, model: str, estimate: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.lock:
            return sum(n for _, n in self._window(model, now)) + estimate <= self.limit

    def record(self, model: str, tokens: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.lock:
            self._window(model, now).append((now, tokens))


class Client:
    def __init__(self, agent: str, log=None, share: float | None = None) -> None:
        self.agent = agent
        self.log = log
        first = _env(f"LLM_{agent.upper()}_FIRST_MODEL") or None
        self.chain = targets(first)
        share = share if share is not None else float(_env(f"LLM_{agent.upper()}_TPM_SHARE", "1.0"))
        self.budget = TokenBudget(int(int(_env("LLM_TPM_LIMIT", "8000")) * share))
        self.enabled = _flag("LLM_ENABLED", False)
        self.force_fail = _flag("LLM_FORCE_FAIL", False)
        self.cache_path = ROOT / "data" / "llm_cache.sqlite" if _env("LLM_CACHE", "off").lower() == "on" else None

    # ---------------------------------------------------------------- cache (development only)
    def _cache_get(self, key: str) -> Result | None:
        if self.cache_path is None or not self.cache_path.exists():
            return None
        with sqlite3.connect(self.cache_path) as c:
            row = c.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return Result(**{**json.loads(row[0]), "cached": True}) if row else None

    def _cache_put(self, key: str, result: Result) -> None:
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache_path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, value TEXT)")
            c.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, json.dumps(result.__dict__)))

    # ---------------------------------------------------------------- the call
    def complete_json(self, system: str, user: str, max_tokens: int = 1500, timeout_s: float = TIMEOUT_S,
                      wait_s: float = 0.0) -> Result:
        """wait_s: if every model is blocked only by this process's own token budget, wait up to this long for it
        to free up before giving up (M6b live finding: three lectures ending together exhausted it in one tick)."""
        if not self.enabled:
            return Result(False, reason="disabled")
        if self.force_fail:
            return Result(False, reason="forced_failure")
        if not self.chain:
            return Result(False, reason="no_provider_configured")
        key = hashlib.sha256(json.dumps([system, user, max_tokens, [t.model for t in self.chain]]).encode()).hexdigest()
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        estimate = (len(system) + len(user)) // 4 + max_tokens // 4
        deadline = time.time() + wait_s
        while wait_s > 0 and not any(self.budget.allows(t.model, estimate) for t in self.chain) \
                and time.time() < deadline:
            time.sleep(1.0)
        attempts = []
        for t in self.chain:
            if not self.budget.allows(t.model, estimate):
                attempts.append((t.model, "local_budget"))
                continue
            result = self._call(t, system, user, max_tokens, timeout_s)
            if result.ok:
                result.attempts = attempts
                self.budget.record(t.model, result.tokens or estimate)
                self._cache_put(key, result)
                if self.log:
                    self.log.info("llm_call", agent=self.agent, model=t.model, latency_s=result.latency_s,
                                  tokens=result.tokens, fallbacks=len(attempts))
                return result
            attempts.append((t.model, result.reason))
            if result.reason == "HTTP 429":
                self.budget.record(t.model, self.budget.limit)          # back off this model for a minute
        if self.log:
            self.log.warn("llm_all_failed", agent=self.agent, attempts=attempts)
        return Result(False, attempts=attempts, reason="all_failed")

    @staticmethod
    def _call(t: Target, system: str, user: str, max_tokens: int, timeout_s: float) -> Result:
        body = {"model": t.model, "temperature": 0.2, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if "gpt-oss" in t.model:
            body["reasoning_effort"] = "low"     # hidden reasoning tokens count against the quota
        started = time.perf_counter()
        try:
            r = requests.post(f"{t.base_url}/chat/completions", json=body, timeout=timeout_s,
                              headers={"Authorization": f"Bearer {t.key}"})
        except requests.RequestException as exc:
            return Result(False, reason=type(exc).__name__)
        latency = round(time.perf_counter() - started, 3)
        if r.status_code != 200:
            return Result(False, reason=f"HTTP {r.status_code}", latency_s=latency)
        try:
            payload = r.json()
            data = json.loads(payload["choices"][0]["message"].get("content") or "")
        except (ValueError, KeyError, IndexError, TypeError):
            return Result(False, reason="invalid_json", latency_s=latency)
        if not isinstance(data, dict):
            return Result(False, reason="invalid_json", latency_s=latency)
        usage = payload.get("usage") or {}
        return Result(True, data=data, model=t.model, latency_s=latency,
                      prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
