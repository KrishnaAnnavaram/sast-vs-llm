"""``tests``: run the unit tests of each sample in a child process and report each failure.

A failure becomes a ``correctness`` finding that covers the lines of the function under test. This is
how the benchmark finds logic errors (for example a hard-coded special case) that no SAST rule finds.
The child process uses ``-I`` (isolated mode), a fixed hash seed and a time limit.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

from sast_vs_llm.findings import Finding

NAME = "tests"
VERSION = "1.0"

_HARNESS = r'''
import importlib.util, json, sys
path, tests = sys.argv[1], json.loads(sys.stdin.read())
spec = importlib.util.spec_from_file_location("sample_under_test", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = []
for t in tests:
    try:
        target = getattr(getattr(mod, t["cls"])(), t["call"]) if t.get("cls") else getattr(mod, t["call"])
        got = target(*t["args"])
        if isinstance(got, tuple):
            got = list(got)
        out.append({"ok": got == t["expected"], "got": repr(got)[:200]})
    except Exception as exc:
        out.append({"ok": False, "got": type(exc).__name__ + ": " + str(exc)[:200]})
print(json.dumps(out))
'''


def run_tests(sample, timeout: int = 20) -> list[dict]:
    """Return one result dict for each unit test: ``ok``, ``got``, ``call``."""
    if not sample.tests:
        return []
    payload = json.dumps([{"call": t.call, "args": t.args, "expected": t.expected, "cls": t.cls} for t in sample.tests])
    env = {"PYTHONHASHSEED": "0", "PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    proc = subprocess.run([sys.executable, "-I", "-c", _HARNESS, str(sample.path)], input=payload,
                          capture_output=True, text=True, timeout=timeout, env=env, check=False)
    if proc.returncode != 0:
        msg = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "child process failed"
        return [{"ok": False, "got": msg, "call": t.call} for t in sample.tests]
    results = json.loads(proc.stdout)
    for res, t in zip(results, sample.tests):
        res["call"] = t.call
    return results


def _function_span(code: str, call: str, cls: str | None) -> tuple[int, int]:
    tree = ast.parse(code)
    scope = tree.body
    if cls:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == cls:
                scope = node.body
    for node in scope:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == call:
            return node.lineno, node.end_lineno or node.lineno
    return 1, len(code.splitlines()) or 1


class UnitTestAnalyzer:
    name = NAME
    version = VERSION

    def available(self) -> bool:
        return True

    def analyze(self, sample) -> list[Finding]:
        findings = []
        failed_calls = set()
        for res, t in zip(run_tests(sample), sample.tests):
            if res["ok"] or (t.cls, t.call) in failed_calls:
                continue
            failed_calls.add((t.cls, t.call))
            start, end = _function_span(sample.code, t.call, t.cls)
            findings.append(Finding(NAME, "correctness", start, end, "BUG-test-failure", "high",
                                    f"{t.call}{tuple(t.args)!r} returned {res['got']}, expected {t.expected!r}",
                                    "unit-test"))
        return findings
