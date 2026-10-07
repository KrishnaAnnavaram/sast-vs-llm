"""Match findings to ground-truth labels.

A finding matches a label when:

1. the category is the same,
2. the line ranges overlap after a tolerance of ``tol`` lines on each side, and
3. in ``strict`` mode, the rule families are the same. A ``BUG-test-failure`` or ``BUG-other``
   finding matches any correctness label, because a failed test shows the bug but not its kind.

Each label matches at most one finding and each finding at most one label (greedy, by line distance).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sast_vs_llm.corpus import Label
from sast_vs_llm.findings import Finding, rule_family

GENERIC_CORRECTNESS = {"BUG-test-failure", "BUG-other"}


def _overlaps(label: Label, f: Finding, tol: int) -> bool:
    return f.line_start <= label.line_end + tol and label.line_start <= f.line_end + tol


def _rule_ok(label: Label, f: Finding, strict: bool) -> bool:
    if not strict:
        return True
    if label.category == "correctness" and f.rule in GENERIC_CORRECTNESS:
        return True
    return rule_family(f.rule) == rule_family(label.rule)


def _distance(label: Label, f: Finding) -> int:
    return abs(f.line_start - label.line_start) + abs(f.line_end - label.line_end)


@dataclass
class MatchResult:
    tp: list[tuple[Label, Finding]] = field(default_factory=list)
    fp: list[Finding] = field(default_factory=list)
    fn: list[Label] = field(default_factory=list)


def match(labels: list[Label], findings: list[Finding], tol: int = 2, strict: bool = False) -> MatchResult:
    pairs = [
        (_distance(lab, f), li, fi)
        for li, lab in enumerate(labels)
        for fi, f in enumerate(findings)
        if lab.category == f.category and _overlaps(lab, f, tol) and _rule_ok(lab, f, strict)
    ]
    used_l, used_f = set(), set()
    res = MatchResult()
    for _, li, fi in sorted(pairs):
        if li in used_l or fi in used_f:
            continue
        used_l.add(li)
        used_f.add(fi)
        res.tp.append((labels[li], findings[fi]))
    res.fp = [f for i, f in enumerate(findings) if i not in used_f]
    res.fn = [lab for i, lab in enumerate(labels) if i not in used_l]
    return res
