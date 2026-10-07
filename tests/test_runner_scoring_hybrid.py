import csv
import json

import pytest

from sast_vs_llm.analyzers.builtin import BuiltinAnalyzer
from sast_vs_llm.analyzers.unit_tests import UnitTestAnalyzer
from sast_vs_llm.blind import RATING_COLUMNS, make_sheet, score_sheet
from sast_vs_llm.corpus import load_corpus
from sast_vs_llm.hybrid import SimulatedTriage, evaluate_hybrid, parse_keep, triage
from sast_vs_llm.llm import ScriptedLLM, SimulatedReviewer
from sast_vs_llm.review import LLMReviewer
from sast_vs_llm.runner import StaleResultError, load_results, run_benchmark
from sast_vs_llm.scoring import score, to_markdown


@pytest.fixture(scope="module")
def stored(tmp_path_factory, samples):
    out = tmp_path_factory.mktemp("results")
    analyzers = [BuiltinAnalyzer(), UnitTestAnalyzer(), LLMReviewer(SimulatedReviewer(), name="sim")]
    summary = run_benchmark(samples, analyzers, out, repeats=3)
    return out, summary


def test_run_writes_raw_files_and_manifest(stored, samples):
    out, summary = stored
    assert summary.files_written == len(samples) * (1 + 1 + 3)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["analyzers"]) == {"builtin", "tests", "sim"} and manifest["repeats"] == 3
    rec = json.loads((out / "raw" / "sim" / "ping_host__r2.json").read_text(encoding="utf-8"))
    assert rec["repeat"] == 2 and len(rec["sample_sha256"]) == 64 and "prompt_sha" in rec["meta"]


def test_unavailable_analyzer_is_skipped(tmp_path, samples):
    class Missing:
        name, version = "ghost", "0"

        def available(self):
            return False

    summary = run_benchmark(samples[:2], [Missing()], tmp_path)
    assert summary.skipped == {"ghost": "not installed"}


def test_stale_results_are_refused(tmp_path, corpus_copy):
    samples = load_corpus(corpus_copy)
    run_benchmark(samples, [BuiltinAnalyzer()], tmp_path)
    target = samples[10]
    target.path.write_text(target.code + "\nEXTRA = 1\n", encoding="utf-8")
    with pytest.raises(StaleResultError):
        load_results(tmp_path, load_corpus(corpus_copy))
    assert load_results(tmp_path, load_corpus(corpus_copy), allow_stale=True).findings


def test_scoreboard_contents(stored, samples):
    board = score(load_results(stored[0], samples), samples)
    rows = {(r["analyzer"], r["category"]): r for r in board.rows}
    assert rows[("builtin", "security")]["recall"] == 1.0
    assert rows[("tests", "correctness")]["tp"] == 3
    clean = {r["analyzer"]: r for r in board.clean}
    assert clean["builtin"]["flagged"] == 0 and clean["builtin"]["clean_samples"] == 10
    cons = {r["analyzer"]: r for r in board.consistency}
    assert set(cons) == {"sim"} and 0 <= cons["sim"]["mean_jaccard"] <= 1
    quality = board.llm_quality[0]
    assert quality["calls"] == 90 and quality["replies_with_ungrounded_fields"] > 0
    text = to_markdown(board)
    assert "## Consistency over repeats" in text and "| builtin | security |" in text


def test_parse_keep():
    assert parse_keep('{"keep": [0, 2, 9]}', 3) == {0, 2}
    assert parse_keep("no idea", 3) == {0, 1, 2}


def test_triage_removes_dropped_findings(by_id):
    s = by_id["report_formatter"]
    found = BuiltinAnalyzer().analyze(s)
    kept = triage(s, found, ScriptedLLM(['{"keep": [0]}']))
    assert kept == found[:1]


def test_hybrid_with_simulated_triage(stored, samples):
    res = evaluate_hybrid(load_results(stored[0], samples), samples, "sim", SimulatedTriage())
    assert res.after["fp"] <= res.before["fp"] and res.after["tp"] <= res.before["tp"]


def test_blind_sheet_hides_reviewer_names(stored, samples, tmp_path):
    results = load_results(stored[0], samples)
    sheet, key = tmp_path / "r.csv", tmp_path / "k.json"
    n = make_sheet(results, samples, sheet, key, seed=1, analyzers=["builtin", "sim"])
    assert n == 2 * len(samples)
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert list(rows[0].keys()) == RATING_COLUMNS  # no reviewer column
    assert all(row["item_id"].startswith("R") and row["item_id"][1:].isdigit() for row in rows)
    order = [row["sample_id"] for row in rows]
    assert order != sorted(order)  # shuffled, so the position does not show the reviewer
    keymap = json.loads(key.read_text(encoding="utf-8"))
    for row in rows:
        row["usefulness_1_to_5"] = "4" if keymap[row["item_id"]] == "builtin" else "2"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    scores = {r["reviewer"]: r for r in score_sheet(sheet, key)}
    assert scores["builtin"]["mean"] == 4.0 and scores["sim"]["mean"] == 2.0


def test_blind_score_refuses_bad_rating(tmp_path):
    sheet, key = tmp_path / "r.csv", tmp_path / "k.json"
    key.write_text('{"R0001": "x"}', encoding="utf-8")
    sheet.write_text("item_id,sample_id,code_file,review,usefulness_1_to_5,comment\nR0001,a,a.py,t,9,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        score_sheet(sheet, key)
