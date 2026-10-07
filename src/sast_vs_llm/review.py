"""The LLM reviewer: a fixed, versioned prompt, a strict JSON parser and repeated runs.

The parser accepts only the documented fields. Each other top-level or finding field (for example a
"coverage" percentage or a letter grade) is counted as an *ungrounded field* and dropped, because the
reviewer ran no tests and no tools. Findings with an unknown category or a line outside the file are
dropped and counted too.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib import resources

from sast_vs_llm.findings import CATEGORIES, RULES, Finding
from sast_vs_llm.llm import LLMClient, LLMError

PROMPT_VERSION = "review_v1"
CODE_START, CODE_END = "<<<CODE", "CODE>>>"
ALLOWED_FINDING_FIELDS = {"category", "rule", "line_start", "line_end", "severity", "explanation"}
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
_CWE = re.compile(r"CWE[-_ ]?(\d+)", re.I)


def load_prompt(version: str = PROMPT_VERSION) -> str:
    return (resources.files("sast_vs_llm") / "prompts" / f"{version}.txt").read_text(encoding="utf-8")


def prompt_hash(version: str = PROMPT_VERSION) -> str:
    return hashlib.sha256(load_prompt(version).encode("utf-8")).hexdigest()[:16]


def render_user_prompt(code: str) -> str:
    numbered = "\n".join(f"{i:4d}| {line}" for i, line in enumerate(code.splitlines(), 1))
    return f"File under review (line numbers on the left):\n{CODE_START}\n{numbered}\n{CODE_END}"


def extract_code(user_prompt: str) -> str:
    """Invert ``render_user_prompt``: return the code without the line numbers."""
    body = user_prompt.split(CODE_START, 1)[-1].split(CODE_END, 1)[0].strip("\n")
    return "\n".join(line.split("| ", 1)[1] if "| " in line else "" for line in body.splitlines())


@dataclass
class ParsedReview:
    findings: list[Finding] = field(default_factory=list)
    ungrounded_fields: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    parse_error: str | None = None


def _json_from_text(text: str):
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    start = min([i for i in (candidate.find("{"), candidate.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise ValueError("no JSON object in the reply")
    return json.JSONDecoder().raw_decode(candidate[start:])[0]


def _canonical_rule(raw, category: str) -> str | None:
    if raw in (None, "", "null"):
        return None
    text = str(raw)
    if text in RULES and RULES[text][0] == category:
        return text
    m = _CWE.search(text)
    if m and f"CWE-{m.group(1)}" in RULES and category == "security":
        return f"CWE-{m.group(1)}"
    return None


def parse_review(text: str, n_lines: int, analyzer: str) -> ParsedReview:
    out = ParsedReview()
    try:
        doc = _json_from_text(text)
    except (ValueError, json.JSONDecodeError) as exc:
        out.parse_error = str(exc)
        return out
    if isinstance(doc, list):
        doc = {"findings": doc}
    if not isinstance(doc, dict) or not isinstance(doc.get("findings", []), list):
        out.parse_error = "the reply has no findings list"
        return out
    out.ungrounded_fields += [k for k in doc if k != "findings"]
    for i, item in enumerate(doc.get("findings", [])):
        if not isinstance(item, dict):
            out.dropped.append(f"#{i}: not an object")
            continue
        out.ungrounded_fields += [f"findings.{k}" for k in item if k not in ALLOWED_FINDING_FIELDS]
        category = str(item.get("category", "")).lower().strip()
        if category not in CATEGORIES:
            out.dropped.append(f"#{i}: unknown category {category!r}")
            continue
        try:
            start = int(item.get("line_start"))
            end = int(item.get("line_end", start) or start)
        except (TypeError, ValueError):
            out.dropped.append(f"#{i}: no valid line number")
            continue
        if not 1 <= start <= n_lines or end < start:
            out.dropped.append(f"#{i}: line {start}-{end} is not in the file (1-{n_lines})")
            continue
        out.findings.append(Finding(analyzer, category, start, min(end, n_lines),
                                    _canonical_rule(item.get("rule"), category),
                                    str(item.get("severity", "medium")).lower(),
                                    str(item.get("explanation", ""))[:500], str(item.get("rule") or "")))
    return out


class LLMReviewer:
    """An analyser that asks an LLM. One call for each sample and repeat."""

    def __init__(self, client: LLMClient, prompt_version: str = PROMPT_VERSION, name: str | None = None):
        self.client = client
        self.prompt_version = prompt_version
        self.system = load_prompt(prompt_version)
        self.name = name or f"llm:{client.model}"
        self.last: ParsedReview | None = None
        self.last_meta: dict = {}

    @property
    def version(self) -> str:
        return f"{self.client.model}|{self.prompt_version}|{prompt_hash(self.prompt_version)}"

    def available(self) -> bool:
        return True

    def analyze(self, sample, repeat: int = 0) -> list[Finding]:
        try:
            reply = self.client.complete(self.system, render_user_prompt(sample.code), seed=repeat)
        except LLMError as exc:
            self.last = ParsedReview(parse_error=f"LLM error: {exc}")
            self.last_meta = {"error": str(exc)}
            return []
        parsed = parse_review(reply.text, sample.n_lines, self.name)
        self.last = parsed
        self.last_meta = {"model": reply.model, "latency_s": round(reply.latency_s, 3), "usage": reply.usage,
                          "temperature": self.client.temperature, "prompt_version": self.prompt_version,
                          "prompt_sha": prompt_hash(self.prompt_version),
                          "ungrounded_fields": parsed.ungrounded_fields, "dropped": parsed.dropped,
                          "parse_error": parsed.parse_error}
        return parsed.findings
