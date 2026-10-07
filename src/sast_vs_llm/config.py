"""Settings from environment variables, an optional .env file, and the factory for analysers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PROVIDERS = ("simulated", "openai", "gemini", "none")


class ConfigError(ValueError):
    """A setting has a value that the package cannot use."""


def load_dotenv(path: str | os.PathLike = ".env") -> int:
    p = Path(path)
    if not p.is_file():
        return 0
    added = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (x.strip() for x in line.split("=", 1))
        value = value.strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            added += 1
    return added


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    base_url: str
    temperature: float
    repeats: int
    timeout: float
    results_dir: Path
    openai_api_key: str | None
    gemini_api_key: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        provider = (env.get("SAST_LLM_PROVIDER") or "simulated").strip().lower()
        if provider not in PROVIDERS:
            raise ConfigError(f"SAST_LLM_PROVIDER must be one of {PROVIDERS}, got {provider!r}")
        default_model = {"openai": "gpt-4.1-mini", "gemini": "gemini-2.5-flash"}.get(provider, provider)
        try:
            temperature = float(env.get("SAST_LLM_TEMPERATURE") or 0.0)
            repeats = int(env.get("SAST_LLM_REPEATS") or 3)
            timeout = float(env.get("SAST_LLM_TIMEOUT") or 120)
        except ValueError as exc:
            raise ConfigError(f"bad numeric setting: {exc}") from exc
        if not 0.0 <= temperature <= 2.0:
            raise ConfigError("SAST_LLM_TEMPERATURE must be between 0 and 2")
        if not 1 <= repeats <= 50:
            raise ConfigError("SAST_LLM_REPEATS must be between 1 and 50")
        return cls(
            provider=provider,
            model=(env.get("SAST_LLM_MODEL") or default_model).strip(),
            base_url=(env.get("SAST_LLM_BASE_URL") or "").strip(),
            temperature=temperature,
            repeats=repeats,
            timeout=timeout,
            results_dir=Path((env.get("SAST_RESULTS_DIR") or "results").strip()),
            openai_api_key=env.get("OPENAI_API_KEY") or None,
            gemini_api_key=env.get("GEMINI_API_KEY") or None,
        )


def build_llm(settings: Settings):
    """Return an LLM client for the configured provider, or None for ``none``."""
    from sast_vs_llm.llm import GeminiClient, OpenAICompatibleClient, SimulatedReviewer

    if settings.provider == "none":
        return None
    if settings.provider == "simulated":
        return SimulatedReviewer()
    if settings.provider == "openai":
        return OpenAICompatibleClient(settings.model, settings.base_url or "https://api.openai.com/v1",
                                      settings.openai_api_key, settings.temperature, settings.timeout)
    kwargs = {"base_url": settings.base_url} if settings.base_url else {}
    return GeminiClient(settings.model, settings.gemini_api_key, settings.temperature, timeout=settings.timeout, **kwargs)


ANALYZER_NAMES = ("builtin", "tests", "bandit", "pylint", "ruff", "semgrep", "llm")


def build_analyzers(names: list[str], settings: Settings) -> list:
    from sast_vs_llm.analyzers.builtin import BuiltinAnalyzer
    from sast_vs_llm.analyzers.external import BanditAnalyzer, PylintAnalyzer, RuffAnalyzer, SemgrepAnalyzer
    from sast_vs_llm.analyzers.unit_tests import UnitTestAnalyzer
    from sast_vs_llm.review import LLMReviewer

    factories = {"builtin": BuiltinAnalyzer, "tests": UnitTestAnalyzer, "bandit": BanditAnalyzer,
                 "pylint": PylintAnalyzer, "ruff": RuffAnalyzer, "semgrep": SemgrepAnalyzer}
    out = []
    for name in names:
        if name == "llm":
            client = build_llm(settings)
            if client is None:
                raise ConfigError("analyzer 'llm' needs SAST_LLM_PROVIDER other than 'none'")
            out.append(LLMReviewer(client))
        elif name in factories:
            out.append(factories[name]())
        else:
            raise ConfigError(f"unknown analyzer {name!r}. Known: {ANALYZER_NAMES}")
    return out
