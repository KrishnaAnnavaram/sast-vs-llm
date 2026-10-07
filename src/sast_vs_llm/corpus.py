"""The labelled corpus: Python samples with ground-truth labels and unit tests.

Labels name their line with an ``anchor`` (a text that occurs exactly once in the file), not a
number. The loader resolves the line, so an edit of the sample cannot leave a stale line number.
The sample files contain no hint of their labels.
"""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from sast_vs_llm.findings import CATEGORIES, RULES

KINDS = ("vulnerable", "smelly", "buggy", "clean")
STYLES = ("functions", "class", "optimized")
DIFFICULTIES = ("easy", "medium", "hard")


class CorpusError(ValueError):
    """The corpus breaks one or more rules. ``problems`` lists each one."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("corpus validation failed:\n  - " + "\n  - ".join(problems))


@dataclass(frozen=True)
class Label:
    category: str
    rule: str
    line_start: int
    line_end: int
    note: str = ""


@dataclass(frozen=True)
class UnitTest:
    call: str
    args: list
    expected: object
    cls: str | None = None


@dataclass
class Sample:
    id: str
    path: Path
    problem: str
    difficulty: str
    style: str
    kind: str
    labels: list[Label] = field(default_factory=list)
    tests: list[UnitTest] = field(default_factory=list)

    @property
    def code(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def n_lines(self) -> int:
        return len(self.code.splitlines())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


def default_corpus_dir() -> Path:
    return Path(str(resources.files("sast_vs_llm") / "corpus"))


def _resolve(code: str, anchor: str, span: int, sid: str, problems: list[str]) -> tuple[int, int] | None:
    lines = code.splitlines()
    hits = [i for i, line in enumerate(lines, 1) if anchor in line]
    if len(hits) != 1:
        problems.append(f"{sid}: anchor {anchor!r} occurs {len(hits)} times (must be 1)")
        return None
    start = hits[0]
    end = start + max(1, span) - 1
    if end > len(lines):
        problems.append(f"{sid}: label span {span} passes the end of the file")
        return None
    return start, end


def load_corpus(corpus_dir: str | Path | None = None, validate: bool = True) -> list[Sample]:
    """Read ``manifest.json`` and the sample files. With ``validate`` the corpus rules are checked."""
    root = Path(corpus_dir) if corpus_dir else default_corpus_dir()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    problems: list[str] = []
    samples: list[Sample] = []
    for entry in manifest["samples"]:
        sid = entry["id"]
        path = root / entry["file"]
        if not path.is_file():
            problems.append(f"{sid}: file {entry['file']} does not exist")
            continue
        code = path.read_text(encoding="utf-8")
        labels = []
        for lab in entry.get("labels", []):
            span = _resolve(code, lab["anchor"], lab.get("span", 1), sid, problems)
            if span:
                labels.append(Label(lab["category"], lab["rule"], span[0], span[1], lab.get("note", "")))
        tests = [UnitTest(t["call"], t["args"], t["expected"], t.get("class")) for t in entry.get("tests", [])]
        samples.append(Sample(sid, path, entry["problem"], entry["difficulty"], entry["style"], entry["kind"],
                              labels, tests))
    if validate:
        problems += check_corpus(samples)
    if problems:
        raise CorpusError(problems)
    return samples


def _normalised_ast(code: str) -> str:
    tree = ast.parse(code)
    for node in ast.walk(tree):  # docstrings do not make two variants different
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree, annotate_fields=False)


def check_corpus(samples: list[Sample]) -> list[str]:
    """Return a list of rule violations (empty when the corpus is valid)."""
    problems: list[str] = []
    ids = [s.id for s in samples]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"duplicate sample id {dup}")
    seen_ast: dict[str, str] = {}
    for s in samples:
        if s.kind not in KINDS:
            problems.append(f"{s.id}: unknown kind {s.kind!r}")
        if s.style not in STYLES:
            problems.append(f"{s.id}: unknown style {s.style!r}")
        if s.difficulty not in DIFFICULTIES:
            problems.append(f"{s.id}: unknown difficulty {s.difficulty!r}")
        try:
            dump = _normalised_ast(s.code)
        except SyntaxError as exc:
            problems.append(f"{s.id}: does not parse ({exc})")
            continue
        if dump in seen_ast:
            problems.append(f"{s.id}: same code as {seen_ast[dump]} (variants must differ)")
        seen_ast[dump] = s.id
        if s.kind == "clean" and s.labels:
            problems.append(f"{s.id}: a clean control must have no labels")
        if s.kind != "clean" and not s.labels:
            problems.append(f"{s.id}: kind {s.kind} needs at least one label")
        for lab in s.labels:
            if lab.category not in CATEGORIES:
                problems.append(f"{s.id}: unknown category {lab.category!r}")
            if lab.rule not in RULES or RULES[lab.rule][0] != lab.category:
                problems.append(f"{s.id}: rule {lab.rule!r} does not belong to category {lab.category!r}")
        if s.kind == "buggy" and not s.tests:
            problems.append(f"{s.id}: a buggy sample needs a unit test that shows the bug")
    return problems


def corpus_summary(samples: list[Sample]) -> dict:
    by_cat: dict[str, int] = {}
    for s in samples:
        for lab in s.labels:
            by_cat[lab.category] = by_cat.get(lab.category, 0) + 1
    return {
        "samples": len(samples),
        "clean_controls": sum(s.kind == "clean" for s in samples),
        "labels": sum(len(s.labels) for s in samples),
        "labels_by_category": by_cat,
        "unit_tests": sum(len(s.tests) for s in samples),
        "lines": sum(s.n_lines for s in samples),
    }
