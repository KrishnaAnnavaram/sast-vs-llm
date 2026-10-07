"""LLM clients behind one small interface: ``complete(system, user) -> LLMReply``.

- ``OpenAICompatibleClient``: OpenAI, LM Studio, Ollama, vLLM and other servers with ``/chat/completions``.
- ``GeminiClient``: the Google Generative Language REST API.
- ``ScriptedLLM``: replays fixed replies (tests).
- ``SimulatedReviewer``: an offline stand-in that is NOT a language model (see its docstring).

The clients use only the standard library (``urllib``), with temperature 0 by default.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol


class LLMError(RuntimeError):
    """The LLM call failed (network, HTTP status or an unexpected reply)."""


@dataclass
class LLMReply:
    text: str
    model: str
    latency_s: float
    usage: dict = field(default_factory=dict)


class LLMClient(Protocol):
    name: str
    model: str
    temperature: float

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply: ...


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL from settings
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMError(str(exc)) from exc


class OpenAICompatibleClient:
    name = "openai"

    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1", api_key: str | None = None,
                 temperature: float = 0.0, timeout: float = 120.0):
        if "api.openai.com" in base_url and not api_key:
            raise LLMError("OPENAI_API_KEY is necessary for api.openai.com")
        self.model, self.base_url, self.api_key = model, base_url.rstrip("/"), api_key
        self.temperature, self.timeout = temperature, timeout

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply:
        payload = {"model": self.model, "temperature": self.temperature,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if seed is not None:
            payload["seed"] = seed
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        t0 = time.perf_counter()
        data = _post_json(f"{self.base_url}/chat/completions", payload, headers, self.timeout)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected reply: {str(data)[:200]}") from exc
        return LLMReply(text, data.get("model", self.model), time.perf_counter() - t0, data.get("usage", {}))


class GeminiClient:
    name = "gemini"

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None, temperature: float = 0.0,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta", timeout: float = 120.0):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is necessary for the Gemini provider")
        self.model, self.api_key, self.temperature = model, api_key, temperature
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply:
        payload = {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json"}}
        if seed is not None:
            payload["generationConfig"]["seed"] = seed
        t0 = time.perf_counter()
        data = _post_json(f"{self.base_url}/models/{self.model}:generateContent",
                          payload, {"x-goog-api-key": self.api_key}, self.timeout)
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected reply: {str(data)[:200]}") from exc
        return LLMReply(text, self.model, time.perf_counter() - t0, data.get("usageMetadata", {}))


class ScriptedLLM:
    """Return the given replies in sequence (the last one repeats). For tests."""

    name = "scripted"
    temperature = 0.0

    def __init__(self, replies: list[str], model: str = "scripted"):
        if not replies:
            raise ValueError("ScriptedLLM needs at least one reply")
        self.replies, self.model, self.calls = list(replies), model, []

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply:
        self.calls.append((system, user, seed))
        text = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return LLMReply(text, self.model, 0.0)


class SimulatedReviewer:
    """An offline stand-in for an LLM reviewer. It is NOT a language model.

    It runs the ``builtin`` analyser on the code in the prompt, then adds seeded noise: it drops some
    findings, moves some lines, adds an invented finding and sometimes adds an ungrounded "coverage"
    grade. Its only purpose is to exercise the LLM path (prompt, JSON parse, repeats, consistency)
    with no network. Its scores say nothing about real LLMs.
    """

    name = "simulated"

    def __init__(self, keep: float = 0.75, jitter: int = 1, invent: float = 0.3, seed: int = 0):
        self.keep, self.jitter, self.invent, self.base_seed = keep, jitter, invent, seed
        self.model = f"simulated-keep{keep}"
        self.temperature = 0.0

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply:
        from sast_vs_llm.analyzers.builtin import analyze_code
        from sast_vs_llm.review import extract_code

        code = extract_code(user)
        digest = hashlib.sha256(f"{self.base_seed}|{seed}|{code}".encode("utf-8")).hexdigest()
        rng = random.Random(int(digest[:12], 16))  # stable across processes, unlike hash()
        n_lines = max(1, len(code.splitlines()))
        items = []
        for f in analyze_code(code):
            if rng.random() > self.keep:
                continue
            shift = rng.randint(-self.jitter, self.jitter)
            start = min(n_lines, max(1, f.line_start + shift))
            items.append({"category": f.category, "rule": f.rule, "line_start": start,
                          "line_end": max(start, min(n_lines, f.line_end + shift)), "severity": f.severity,
                          "explanation": f"{f.message[:1].upper()}{f.message[1:]}."})
        if rng.random() < self.invent:
            line = rng.randint(1, n_lines)
            items.append({"category": "maintainability", "rule": "SMELL-other", "line_start": line,
                          "line_end": line, "severity": "low", "explanation": "Consider a clearer name."})
        reply = {"findings": items}
        if rng.random() < 0.3:
            reply["coverage"] = "85%"  # an ungrounded metric, as real chat replies sometimes give
        return LLMReply("```json\n" + json.dumps(reply) + "\n```", self.model, 0.0)
