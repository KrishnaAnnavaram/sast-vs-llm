"""Runners for external SAST tools: Bandit, Pylint, Ruff and Semgrep.

Each runner calls the tool as a subprocess with JSON output, then a pure parser changes the JSON into
``Finding`` objects. The parsers have unit tests with small JSON documents, so the mapping is checked
also when the tool is not installed. Install the tools with ``pip install sast-vs-llm[sast]``
(Semgrep separately).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

from sast_vs_llm.findings import Finding


class ToolNotAvailable(RuntimeError):
    """The external tool is not installed."""


# Bandit test id -> canonical rule
BANDIT_RULES = {
    "B102": "CWE-95", "B307": "CWE-95",
    "B301": "CWE-502", "B302": "CWE-502", "B403": None, "B506": "CWE-502",
    "B303": "CWE-328", "B324": "CWE-328",
    "B311": "CWE-330",
    "B105": "CWE-259", "B106": "CWE-259", "B107": "CWE-259",
    "B108": "CWE-377", "B306": "CWE-377",
    "B501": "CWE-295",
    "B101": "CWE-617",
    "B602": "CWE-78", "B603": None, "B604": "CWE-78", "B605": "CWE-78", "B607": None, "B404": None,
    "B608": "CWE-89",
}
# Pylint message symbol -> canonical rule (others become SMELL-other or BUG-other)
PYLINT_RULES = {
    "eval-used": "CWE-95", "exec-used": "CWE-95",
    "dangerous-default-value": "SMELL-mutable-default",
    "bare-except": "SMELL-bare-except",
    "redefined-builtin": "SMELL-shadow-builtin",
    "unused-variable": "SMELL-unused-variable",
    "too-many-nested-blocks": "SMELL-deep-nesting",
}
# Messages that depend on the local environment, not on the code (for example a missing package).
PYLINT_ENVIRONMENT = {"import-error", "no-name-in-module", "import-outside-toplevel"}
# Ruff code -> canonical rule (flake8-bandit codes are S + the Bandit number)
RUFF_RULES = {
    "S102": "CWE-95", "S307": "CWE-95", "S301": "CWE-502", "S506": "CWE-502", "S324": "CWE-328",
    "S311": "CWE-330", "S105": "CWE-259", "S106": "CWE-259", "S107": "CWE-259", "S108": "CWE-377",
    "S306": "CWE-377", "S501": "CWE-295", "S101": "CWE-617", "S602": "CWE-78", "S605": "CWE-78",
    "S608": "CWE-89", "B006": "SMELL-mutable-default", "E722": "SMELL-bare-except", "F841": "SMELL-unused-variable",
    "A001": "SMELL-shadow-builtin", "A002": "SMELL-shadow-builtin",
}
CWE_IN_TEXT = re.compile(r"CWE-(\d+)")
KNOWN_CWES = {"22", "78", "89", "95", "259", "295", "328", "330", "377", "502", "617", "798"}


def _category(rule: str | None, fallback: str) -> str:
    if rule is None:
        return fallback
    if rule.startswith("CWE-"):
        return "security"
    if rule.startswith("SMELL-"):
        return "maintainability"
    return "correctness"


def _sev(value: str) -> str:
    v = (value or "").lower()
    return v if v in ("low", "medium", "high") else ("high" if v in ("error", "fatal") else "medium")


# -- parsers (pure functions) ------------------------------------------------------------------------
def parse_bandit(doc: dict, analyzer: str = "bandit") -> list[Finding]:
    out = []
    for r in doc.get("results", []):
        test_id = r.get("test_id", "")
        rule = BANDIT_RULES.get(test_id)
        if rule is None and test_id not in BANDIT_RULES:
            cwe = str((r.get("issue_cwe") or {}).get("id", ""))
            rule = f"CWE-{cwe}" if cwe in KNOWN_CWES else None
        if rule is None and test_id in BANDIT_RULES:
            continue  # informational import checks (B403, B404, B603, B607) have no label equivalent
        lines = r.get("line_range") or [r.get("line_number", 1)]
        out.append(Finding(analyzer, _category(rule, "security"), int(lines[0]), int(lines[-1]), rule,
                           _sev(r.get("issue_severity")), r.get("issue_text", ""), test_id))
    return out


def parse_pylint(items: list[dict], analyzer: str = "pylint") -> list[Finding]:
    out = []
    for m in items:
        symbol = m.get("symbol", "")
        if symbol in PYLINT_ENVIRONMENT:
            continue
        rule = PYLINT_RULES.get(symbol)
        mtype = m.get("type", "")
        if rule is None:
            if mtype in ("error", "fatal"):
                rule = "BUG-other"
            elif mtype in ("warning", "refactor"):
                rule = "SMELL-other"
            else:
                continue  # convention messages (names, docstrings) have no label equivalent
        start = int(m.get("line", 1) or 1)
        end = int(m.get("endLine") or start)
        out.append(Finding(analyzer, _category(rule, "maintainability"), start, max(start, end), rule,
                           _sev(mtype), m.get("message", ""), symbol))
    return out


def parse_ruff(items: list[dict], analyzer: str = "ruff") -> list[Finding]:
    out = []
    for m in items:
        code = m.get("code") or ""
        rule = RUFF_RULES.get(code)
        if rule is None:
            continue
        start = int((m.get("location") or {}).get("row", 1))
        end = int((m.get("end_location") or {}).get("row", start))
        out.append(Finding(analyzer, _category(rule, "maintainability"), start, max(start, end), rule,
                           "medium", m.get("message", ""), code))
    return out


def parse_semgrep(doc: dict, analyzer: str = "semgrep") -> list[Finding]:
    out = []
    for r in doc.get("results", []):
        meta = (r.get("extra") or {}).get("metadata") or {}
        cwes = meta.get("cwe") or []
        cwes = [cwes] if isinstance(cwes, str) else cwes
        rule = None
        for text in cwes:
            m = CWE_IN_TEXT.search(str(text))
            if m and m.group(1) in KNOWN_CWES:
                rule = f"CWE-{m.group(1)}"
                break
        if rule is None:
            continue
        start = int(r.get("start", {}).get("line", 1))
        end = int(r.get("end", {}).get("line", start))
        sev = (r.get("extra") or {}).get("severity", "")
        out.append(Finding(analyzer, "security", start, max(start, end), rule,
                           {"ERROR": "high", "WARNING": "medium"}.get(sev, "low"),
                           (r.get("extra") or {}).get("message", ""), r.get("check_id", "")))
    return out


# -- runners ---------------------------------------------------------------------------------------
def _module_cmd(module: str) -> list[str]:
    return [sys.executable, "-m", module]


def _run(cmd: list[str], timeout: int = 120) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise ToolNotAvailable(cmd[0]) from exc
    if proc.returncode not in (0, 1, 2, 4, 8, 16, 32) and not proc.stdout:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _has_module(module: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module) is not None


class BanditAnalyzer:
    name = "bandit"

    def available(self) -> bool:
        return _has_module("bandit")

    @property
    def version(self) -> str:
        from importlib.metadata import version
        return version("bandit") if self.available() else "missing"

    def analyze(self, sample) -> list[Finding]:
        if not self.available():
            raise ToolNotAvailable("bandit")
        text = _run(_module_cmd("bandit") + ["-q", "-f", "json", str(sample.path)])
        return parse_bandit(json.loads(text or "{}"))


class PylintAnalyzer:
    name = "pylint"

    def available(self) -> bool:
        return _has_module("pylint")

    @property
    def version(self) -> str:
        from importlib.metadata import version
        return version("pylint") if self.available() else "missing"

    def analyze(self, sample) -> list[Finding]:
        if not self.available():
            raise ToolNotAvailable("pylint")
        text = _run(_module_cmd("pylint") + ["--output-format=json", "--score=n", str(sample.path)])
        return parse_pylint(json.loads(text or "[]"))


class RuffAnalyzer:
    name = "ruff"

    def available(self) -> bool:
        return shutil.which("ruff") is not None

    @property
    def version(self) -> str:
        return _run(["ruff", "--version"]).strip() if self.available() else "missing"

    def analyze(self, sample) -> list[Finding]:
        if not self.available():
            raise ToolNotAvailable("ruff")
        text = _run(["ruff", "check", "--no-cache", "--select", "S,B,E722,F841,A", "--output-format", "json",
                     str(sample.path)])
        return parse_ruff(json.loads(text or "[]"))


class SemgrepAnalyzer:
    name = "semgrep"

    def available(self) -> bool:
        return shutil.which("semgrep") is not None

    @property
    def version(self) -> str:
        return _run(["semgrep", "--version"]).strip() if self.available() else "missing"

    def analyze(self, sample) -> list[Finding]:
        if not self.available():
            raise ToolNotAvailable("semgrep")
        text = _run(["semgrep", "--config", "p/python", "--json", "--metrics=off", "--quiet", str(sample.path)], 300)
        return parse_semgrep(json.loads(text or "{}"))
