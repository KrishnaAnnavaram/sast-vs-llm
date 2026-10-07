import json

import pytest

from sast_vs_llm.corpus import CorpusError, corpus_summary, load_corpus


def test_bundled_corpus_is_valid(samples):
    summary = corpus_summary(samples)
    assert summary["samples"] == 30
    assert summary["labels"] == 23
    assert summary["labels_by_category"] == {"correctness": 3, "maintainability": 5, "security": 15}
    assert summary["clean_controls"] == 10


def test_anchor_resolves_to_the_planted_line(by_id):
    s = by_id["ping_host"]
    lab = s.labels[0]
    assert "os.system" in s.code.splitlines()[lab.line_start - 1]
    assert lab.rule == "CWE-78"


def test_samples_contain_no_label_hints(samples):
    for s in samples:
        low = s.code.lower()
        assert "cwe" not in low and "vulnerab" not in low and "bug" not in low and "smell" not in low


def test_each_problem_has_three_distinct_styles(samples):
    for problem in ("valid_anagram", "majority_element_ii", "word_search_ii"):
        styles = sorted(s.style for s in samples if s.problem == problem)
        assert styles == ["class", "functions", "optimized"]


def _edit_manifest(root, fn):
    path = root / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_identical_variants_are_refused(corpus_copy):
    # the earlier prototype shipped an "optimized" file equal to another variant
    src = (corpus_copy / "samples" / "wordsearch_class.py").read_text(encoding="utf-8")
    (corpus_copy / "samples" / "wordsearch_optimized.py").write_text("\n\n" + src, encoding="utf-8")
    with pytest.raises(CorpusError, match="variants must differ"):
        load_corpus(corpus_copy)


def test_anchor_that_is_not_unique_is_refused(corpus_copy):
    def change(doc):
        doc["samples"][0]["labels"][0]["anchor"] = "return"
    _edit_manifest(corpus_copy, change)
    with pytest.raises(CorpusError, match="occurs"):
        load_corpus(corpus_copy)


def test_clean_control_with_label_is_refused(corpus_copy):
    def change(doc):
        clean = next(s for s in doc["samples"] if s["kind"] == "clean")
        clean["labels"] = [{"category": "security", "rule": "CWE-78", "anchor": "def ", "span": 1}]
    _edit_manifest(corpus_copy, change)
    with pytest.raises(CorpusError, match="clean control"):
        load_corpus(corpus_copy)


def test_rule_must_belong_to_category(corpus_copy):
    def change(doc):
        doc["samples"][0]["labels"][0]["rule"] = "CWE-78"
    _edit_manifest(corpus_copy, change)
    with pytest.raises(CorpusError, match="does not belong"):
        load_corpus(corpus_copy)


def test_buggy_sample_needs_a_test(corpus_copy):
    def change(doc):
        doc["samples"][0]["tests"] = []
    _edit_manifest(corpus_copy, change)
    with pytest.raises(CorpusError, match="needs a unit test"):
        load_corpus(corpus_copy)


def test_sha256_changes_with_the_file(corpus_copy):
    s = load_corpus(corpus_copy)[0]
    before = s.sha256
    s.path.write_text(s.code + "\n# edit\n", encoding="utf-8")
    assert s.sha256 != before
