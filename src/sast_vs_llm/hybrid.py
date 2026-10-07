"""Hybrid review: SAST findings plus an LLM triage step that keeps or drops each finding.

The measure is the change in precision and recall. A good triage step removes false positives and
keeps the true positives.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sast_vs_llm.corpus import Sample
from sast_vs_llm.findings import Finding
from sast_vs_llm.llm import LLMClient, LLMError, LLMReply
from sast_vs_llm.matching import match
from sast_vs_llm.metrics import prf
from sast_vs_llm.review import extract_code, render_user_prompt
from sast_vs_llm.runner import Results

TRIAGE_PROMPT_V1 = (
    "You check the findings of a static analysis tool. For each numbered finding, decide if it is a real "
    "problem in the given code. Reply with JSON only: {\"keep\": [<numbers of the real findings>]}."
)
_FINDING_LINE = re.compile(r"^#(\d+) \[(\w+)\] lines (\d+)-(\d+)", re.M)


def render_triage_prompt(sample: Sample, findings: list[Finding]) -> str:
    items = "\n".join(f"#{i} [{f.category}] lines {f.line_start}-{f.line_end} {f.rule or ''}: {f.message}"
                      for i, f in enumerate(findings))
    return f"{render_user_prompt(sample.code)}\n\nFindings:\n{items}"


def parse_keep(text: str, n: int) -> set[int]:
    """Indices to keep. An unreadable reply keeps every finding (the safe default)."""
    m = re.search(r"\{.*\}", text, re.S)
    try:
        keep = json.loads(m.group(0))["keep"] if m else None
        return {int(i) for i in keep if 0 <= int(i) < n}
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return set(range(n))


def triage(sample: Sample, findings: list[Finding], client: LLMClient) -> list[Finding]:
    if not findings:
        return []
    try:
        reply = client.complete(TRIAGE_PROMPT_V1, render_triage_prompt(sample, findings), seed=0)
    except LLMError:
        return list(findings)
    keep = parse_keep(reply.text, len(findings))
    return [f for i, f in enumerate(findings) if i in keep]


class SimulatedTriage:
    """Offline stand-in for an LLM triage step. It is NOT a language model.

    It keeps a finding only when the ``builtin`` analyser reports the same category within 2 lines.
    The result shows how the hybrid measurement works. It is not a claim about LLM triage.
    """

    name = "simulated-triage"
    model = "simulated-triage"
    temperature = 0.0

    def complete(self, system: str, user: str, seed: int | None = None) -> LLMReply:
        from sast_vs_llm.analyzers.builtin import analyze_code

        code = extract_code(user)
        reference = analyze_code(code)
        keep = []
        for m in _FINDING_LINE.finditer(user.split("\n\nFindings:\n", 1)[-1]):
            idx, cat, start = int(m.group(1)), m.group(2), int(m.group(3))
            if any(r.category == cat and abs(r.line_start - start) <= 2 for r in reference):
                keep.append(idx)
        return LLMReply(json.dumps({"keep": keep}), self.model, 0.0)


@dataclass
class HybridResult:
    analyzer: str
    before: dict
    after: dict


def evaluate_hybrid(results: Results, samples: list[Sample], analyzer: str, client: LLMClient,
                    tol: int = 2, strict: bool = False) -> HybridResult:
    per_sample = results.findings.get(analyzer)
    if per_sample is None:
        raise KeyError(f"no stored results for analyzer {analyzer!r}")
    b = [0, 0, 0]
    a = [0, 0, 0]
    for s in samples:
        if s.id not in per_sample:
            continue
        found = per_sample[s.id][0]
        kept = triage(s, found, client)
        for counts, fs in ((b, found), (a, kept)):
            m = match(s.labels, fs, tol=tol, strict=strict)
            counts[0] += len(m.tp)
            counts[1] += len(m.fp)
            counts[2] += len(m.fn)
    return HybridResult(analyzer, prf(*b), prf(*a))
