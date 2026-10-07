import pytest

from sast_vs_llm.cli import main
from sast_vs_llm.config import ConfigError, Settings, build_analyzers, build_llm
from sast_vs_llm.llm import OpenAICompatibleClient, SimulatedReviewer


def test_settings_defaults():
    s = Settings.from_env({})
    assert (s.provider, s.repeats, s.temperature, str(s.results_dir)) == ("simulated", 3, 0.0, "results")
    assert isinstance(build_llm(s), SimulatedReviewer)


@pytest.mark.parametrize("env", [{"SAST_LLM_PROVIDER": "bard"}, {"SAST_LLM_REPEATS": "0"},
                                 {"SAST_LLM_TEMPERATURE": "x"}])
def test_bad_settings(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)


def test_openai_provider_with_local_server():
    s = Settings.from_env({"SAST_LLM_PROVIDER": "openai", "SAST_LLM_BASE_URL": "http://localhost:1234/v1",
                           "SAST_LLM_MODEL": "llama-3.2"})
    client = build_llm(s)
    assert isinstance(client, OpenAICompatibleClient) and client.model == "llama-3.2"


def test_build_analyzers_rules():
    with pytest.raises(ConfigError):
        build_analyzers(["sonar"], Settings.from_env({}))
    with pytest.raises(ConfigError):
        build_analyzers(["llm"], Settings.from_env({"SAST_LLM_PROVIDER": "none"}))
    names = [a.name for a in build_analyzers(["builtin", "tests", "llm"], Settings.from_env({}))]
    assert names[:2] == ["builtin", "tests"] and names[2].startswith("llm:")


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SAST_LLM_PROVIDER", raising=False)
    out = tmp_path / "res"
    assert main(["corpus", "--list"]) == 0
    assert "ping_host" in capsys.readouterr().out
    assert main(["run", "--analyzers", "builtin,tests,llm", "--repeats", "2", "--out", str(out)]) == 0
    md = tmp_path / "report.md"
    assert main(["score", "--results", str(out), "--strict", "--markdown", str(md)]) == 0
    assert "| builtin | all |" in md.read_text(encoding="utf-8")
    assert main(["hybrid", "--results", str(out), "--analyzer", "builtin"]) == 0
    sheet, key = tmp_path / "s.csv", tmp_path / "k.json"
    assert main(["blind-sheet", "--results", str(out), "--sheet", str(sheet), "--key", str(key)]) == 0
    assert main(["blind-score", "--sheet", str(sheet), "--key", str(key)]) == 0


def test_cli_analyze_file(tmp_path, capsys):
    f = tmp_path / "x.py"
    f.write_text("def f(x):\n    return eval(x)\n", encoding="utf-8")
    assert main(["analyze", str(f)]) == 0
    assert "CWE-95" in capsys.readouterr().out


def test_cli_errors(tmp_path, capsys):
    assert main(["score", "--results", str(tmp_path / "none")]) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["run", "--analyzers", "sonar", "--out", str(tmp_path)]) == 1


def test_cli_demo(capsys):
    assert main(["demo"]) == 0
    out = capsys.readouterr().out
    assert "not a language model" in out and "hybrid" in out
