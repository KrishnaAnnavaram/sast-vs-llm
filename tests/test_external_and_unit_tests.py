import pytest

from sast_vs_llm.analyzers.external import (BanditAnalyzer, ToolNotAvailable, parse_bandit, parse_pylint, parse_ruff,
                                            parse_semgrep)
from sast_vs_llm.analyzers.unit_tests import UnitTestAnalyzer, run_tests
from sast_vs_llm.matching import match


def test_parse_bandit_maps_tests_and_skips_import_notes():
    doc = {"results": [
        {"test_id": "B602", "line_range": [7], "issue_severity": "HIGH", "issue_text": "shell", "issue_cwe": {"id": 78}},
        {"test_id": "B404", "line_range": [1], "issue_severity": "LOW", "issue_text": "import"},
        {"test_id": "B999", "line_range": [3, 4], "issue_severity": "MEDIUM", "issue_cwe": {"id": 89}},
    ]}
    found = parse_bandit(doc)
    assert [(f.rule, f.line_start, f.line_end) for f in found] == [("CWE-78", 7, 7), ("CWE-89", 3, 4)]
    assert found[0].severity == "high" and found[0].raw_rule == "B602"


def test_parse_pylint_maps_symbols_and_drops_conventions_and_environment():
    items = [
        {"symbol": "dangerous-default-value", "type": "warning", "line": 4, "endLine": 4, "message": "m"},
        {"symbol": "missing-function-docstring", "type": "convention", "line": 1},
        {"symbol": "import-error", "type": "error", "line": 3},
        {"symbol": "no-member", "type": "error", "line": 9},
        {"symbol": "too-few-public-methods", "type": "refactor", "line": 1},
    ]
    found = parse_pylint(items)
    assert [(f.rule, f.category) for f in found] == [
        ("SMELL-mutable-default", "maintainability"), ("BUG-other", "correctness"), ("SMELL-other", "maintainability")]


def test_parse_ruff_and_semgrep():
    ruff = parse_ruff([{"code": "S608", "location": {"row": 5}, "end_location": {"row": 6}, "message": "sql"},
                       {"code": "E501", "location": {"row": 1}}])
    assert [(f.rule, f.line_start, f.line_end) for f in ruff] == [("CWE-89", 5, 6)]
    sem = parse_semgrep({"results": [{"check_id": "x", "start": {"line": 2}, "end": {"line": 2},
                                      "extra": {"severity": "ERROR", "metadata": {"cwe": ["CWE-502: Deserialization"]}}}]})
    assert sem[0].rule == "CWE-502" and sem[0].severity == "high"


def test_missing_tool_raises(by_id, monkeypatch):
    analyzer = BanditAnalyzer()
    monkeypatch.setattr(analyzer, "available", lambda: False)
    with pytest.raises(ToolNotAvailable):
        analyzer.analyze(by_id["ping_host"])


def test_bandit_real_run(by_id):
    pytest.importorskip("bandit")
    found = BanditAnalyzer().analyze(by_id["ping_host"])
    assert any(f.rule == "CWE-78" for f in found)


@pytest.mark.parametrize("sid", ["anagram_functions", "anagram_class", "majority_optimized"])
def test_unit_tests_expose_hidden_logic_errors(by_id, sid):
    s = by_id[sid]
    found = UnitTestAnalyzer().analyze(s)
    assert found and all(f.category == "correctness" for f in found)
    assert not match(s.labels, found, strict=True).fn


def test_correct_samples_pass_their_tests(samples):
    for s in samples:
        if s.kind != "buggy" and s.tests:
            assert all(r["ok"] for r in run_tests(s)), s.id


def test_failure_finding_covers_the_function(by_id):
    s = by_id["anagram_functions"]
    f = UnitTestAnalyzer().analyze(s)[0]
    assert s.code.splitlines()[f.line_start - 1].startswith("def is_anagram")
    assert f.line_end >= s.labels[0].line_end
