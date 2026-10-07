import json

import pytest

import sast_vs_llm.llm as llm_mod
from sast_vs_llm.llm import GeminiClient, LLMError, OpenAICompatibleClient, ScriptedLLM, SimulatedReviewer
from sast_vs_llm.review import (LLMReviewer, extract_code, load_prompt, parse_review, prompt_hash,
                                render_user_prompt)


def test_render_and_extract_round_trip():
    code = "def f(x):\n    return x | 1\n\n# end"
    assert extract_code(render_user_prompt(code)) == code


def test_prompt_forbids_invented_metrics():
    text = load_prompt()
    assert "coverage" in text.lower() and "json" in text.lower()
    assert len(prompt_hash()) == 16


def test_parse_fenced_json_and_ungrounded_fields():
    reply = "Here you go:\n```json\n" + json.dumps({
        "findings": [{"category": "security", "rule": "CWE-78", "line_start": 3, "line_end": 3,
                      "severity": "high", "explanation": "shell", "confidence": "92%"}],
        "coverage": "85%", "maintainability_grade": "B"}) + "\n```"
    parsed = parse_review(reply, n_lines=10, analyzer="llm:x")
    assert [f.rule for f in parsed.findings] == ["CWE-78"]
    assert set(parsed.ungrounded_fields) == {"coverage", "maintainability_grade", "findings.confidence"}


def test_parse_drops_bad_items():
    items = [{"category": "style", "line_start": 1},
             {"category": "security", "line_start": 99},
             {"category": "security", "line_start": "x"},
             {"category": "Correctness", "rule": "off by one", "line_start": 2, "line_end": 2}]
    parsed = parse_review(json.dumps({"findings": items}), n_lines=5, analyzer="a")
    assert len(parsed.dropped) == 3
    assert parsed.findings[0].category == "correctness" and parsed.findings[0].rule is None


def test_parse_normalises_cwe_text():
    parsed = parse_review('[{"category": "security", "rule": "cwe 89 (SQL)", "line_start": 1}]', 3, "a")
    assert parsed.findings[0].rule == "CWE-89"


def test_parse_error_is_recorded():
    parsed = parse_review("I think this code is fine.", 3, "a")
    assert parsed.parse_error and parsed.findings == []


def test_reviewer_records_provenance(by_id):
    client = ScriptedLLM(['{"findings": [{"category": "security", "rule": "CWE-78", "line_start": 6}]}'], model="m-1")
    reviewer = LLMReviewer(client)
    found = reviewer.analyze(by_id["ping_host"], repeat=2)
    assert found[0].rule == "CWE-78" and found[0].analyzer == "llm:m-1"
    meta = reviewer.last_meta
    assert meta["model"] == "m-1" and meta["temperature"] == 0.0 and meta["prompt_sha"] == prompt_hash()
    assert client.calls[0][2] == 2  # the repeat number is the seed


def test_reviewer_survives_llm_error(by_id):
    class Broken:
        model, temperature, name = "b", 0.0, "b"

        def complete(self, *a, **k):
            raise LLMError("down")

    reviewer = LLMReviewer(Broken())
    assert reviewer.analyze(by_id["calculator"]) == []
    assert "down" in reviewer.last_meta["error"]


def test_openai_client_needs_key_for_hosted_api():
    with pytest.raises(LLMError):
        OpenAICompatibleClient("gpt-x", "https://api.openai.com/v1", None)
    OpenAICompatibleClient("llama3", "http://localhost:11434/v1", None)  # local server, no key


def test_openai_client_payload_and_reply(monkeypatch):
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": "{}"}}], "model": "gpt-x-2", "usage": {"total_tokens": 9}}

    monkeypatch.setattr(llm_mod, "_post_json", fake_post)
    reply = OpenAICompatibleClient("gpt-x", "http://h/v1", "k").complete("s", "u", seed=4)
    assert seen["url"] == "http://h/v1/chat/completions" and seen["payload"]["temperature"] == 0.0
    assert seen["payload"]["seed"] == 4 and seen["headers"]["Authorization"] == "Bearer k"
    assert reply.model == "gpt-x-2" and reply.usage["total_tokens"] == 9


def test_gemini_client(monkeypatch):
    with pytest.raises(LLMError):
        GeminiClient(api_key=None)
    monkeypatch.setattr(llm_mod, "_post_json",
                        lambda *a: {"candidates": [{"content": {"parts": [{"text": "{\"findings\": []}"}]}}]})
    assert GeminiClient(api_key="k").complete("s", "u").text == '{"findings": []}'


def test_simulated_reviewer_is_seeded(by_id):
    sim = SimulatedReviewer()
    prompt = render_user_prompt(by_id["order_search"].code)
    assert sim.complete("s", prompt, seed=1).text == sim.complete("s", prompt, seed=1).text
    texts = {sim.complete("s", prompt, seed=k).text for k in range(6)}
    assert len(texts) > 1
