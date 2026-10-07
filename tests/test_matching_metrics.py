import math

import pytest

from sast_vs_llm.corpus import Label
from sast_vs_llm.findings import Finding
from sast_vs_llm.matching import match
from sast_vs_llm.metrics import jaccard, mean_pairwise_jaccard, prf, wilson


def F(cat, start, end=None, rule=None):
    return Finding("a", cat, start, end or start, rule)


LAB = Label("security", "CWE-78", 10, 10)


def test_overlap_with_tolerance():
    assert match([LAB], [F("security", 12)]).tp
    assert not match([LAB], [F("security", 13)]).tp
    assert match([LAB], [F("security", 13)], tol=3).tp


def test_category_must_match():
    res = match([LAB], [F("maintainability", 10)])
    assert len(res.fp) == 1 and len(res.fn) == 1


def test_strict_mode_checks_rule_family():
    assert not match([LAB], [F("security", 10, rule="CWE-89")], strict=True).tp
    assert match([LAB], [F("security", 10, rule="CWE-89")], strict=False).tp
    cred = Label("security", "CWE-798", 3, 3)
    assert match([cred], [F("security", 3, rule="CWE-259")], strict=True).tp  # child CWE


def test_test_failure_matches_any_correctness_label_in_strict_mode():
    lab = Label("correctness", "BUG-off-by-one", 5, 5)
    assert match([lab], [F("correctness", 1, 9, "BUG-test-failure")], strict=True).tp


def test_matching_is_one_to_one_and_prefers_closest():
    res = match([LAB], [F("security", 11), F("security", 10)])
    assert len(res.tp) == 1 and res.tp[0][1].line_start == 10 and len(res.fp) == 1


def test_finding_rejects_bad_values():
    with pytest.raises(ValueError):
        F("style", 1)
    with pytest.raises(ValueError):
        F("security", 5, 2)
    with pytest.raises(ValueError):
        F("security", 1, rule="CWE-1")


def test_wilson_interval():
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.490, abs=0.01) and hi == pytest.approx(0.943, abs=0.01)
    assert all(math.isnan(v) for v in wilson(0, 0))


def test_prf_edge_cases():
    m = prf(3, 1, 2)
    assert m["precision"] == 0.75 and m["recall"] == 0.6 and m["f1"] == pytest.approx(2 / 3)
    assert math.isnan(prf(0, 0, 3)["f1"]) and prf(0, 2, 3)["f1"] == 0.0


def test_jaccard_consistency():
    assert jaccard(set(), set()) == 1.0
    assert mean_pairwise_jaccard([{1, 2}, {1, 2}, {1}]) == pytest.approx((1 + 0.5 + 0.5) / 3)
    assert math.isnan(mean_pairwise_jaccard([{1}]))
