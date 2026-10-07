"""``builtin``: a small deterministic AST analyser with no dependencies.

It is a reference SAST tool that always runs offline, so the benchmark, the demo and the tests work
without Bandit, Pylint or a server. Each rule is a plain function of the syntax tree.
"""

from __future__ import annotations

import ast
import builtins
import re

from sast_vs_llm.findings import Finding

NAME = "builtin"
VERSION = "1.0"

SECRET_NAME = re.compile(r"(pass(word|wd)?|secret|api_?key|token|credential)", re.I)
SECURITY_CONTEXT = re.compile(r"(token|password|secret|key|salt|otp|nonce)", re.I)
AUTH_CONTEXT = re.compile(r"(admin|auth|permission|login|delete|privilege)", re.I)
SHADOWED = {"list", "dict", "set", "str", "id", "type", "input", "sum", "max", "min", "file", "len", "map", "filter"}
NESTING_NODES = (ast.If, ast.For, ast.While, ast.With, ast.Try, ast.AsyncFor, ast.AsyncWith)
MAX_NESTING = 4


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _is_dynamic_string(node: ast.AST) -> bool:
    """True for an f-string with values, % formatting, + concatenation or .format()."""
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(v, ast.FormattedValue) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return True
    return False


def _kw(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.findings: list[Finding] = []
        self.func_stack: list[str] = []
        self.params_stack: list[set[str]] = []
        self.assigned_names: dict[str, ast.AST] = {}  # module-level name -> value, for dynamic SQL in a variable

    # -- helpers ---------------------------------------------------------------------------
    def add(self, node: ast.AST, category: str, rule: str, message: str, severity: str = "medium", end=None):
        start = node.lineno
        stop = end if end is not None else getattr(node, "end_lineno", start) or start
        self.findings.append(Finding(NAME, category, start, max(start, stop), rule, severity, message, rule))

    def context(self) -> str:
        return " ".join(self.func_stack)

    # -- functions ---------------------------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef):
        for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.add(node, "maintainability", "SMELL-mutable-default",
                         f"mutable default argument in {node.name}", "low", end=node.lineno)
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.arg in SHADOWED:
                self.add(arg, "maintainability", "SMELL-shadow-builtin", f"argument {arg.arg} hides a builtin", "low")
        self._unused_locals(node)
        self._nesting(node.body, 1)
        self.func_stack.append(node.name)
        self.params_stack.append({a.arg for a in node.args.args + node.args.kwonlyargs})
        local_values: dict[str, ast.AST] = {}
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                local_values[sub.targets[0].id] = sub.value
        saved = self.assigned_names
        self.assigned_names = {**saved, **local_values}
        self.generic_visit(node)
        self.assigned_names = saved
        self.func_stack.pop()
        self.params_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _unused_locals(self, node: ast.FunctionDef):
        stored: dict[str, ast.Name] = {}
        loaded: set[str] = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                if isinstance(sub.ctx, ast.Store):
                    stored.setdefault(sub.id, sub)
                else:
                    loaded.add(sub.id)
            elif isinstance(sub, (ast.Global, ast.Nonlocal)):
                loaded.update(sub.names)
        for name, where in stored.items():
            if name not in loaded and not name.startswith("_"):
                self.add(where, "maintainability", "SMELL-unused-variable", f"{name} is assigned and never used", "low")

    def _nesting(self, body: list[ast.stmt], depth: int):
        for stmt in body:
            if isinstance(stmt, NESTING_NODES):
                if depth > MAX_NESTING:
                    self.add(stmt, "maintainability", "SMELL-deep-nesting",
                             f"nesting depth {depth} (maximum {MAX_NESTING})", "low", end=stmt.lineno)
                    continue  # one finding for each deep branch
                self._nesting(stmt.body, depth + 1)
                orelse = getattr(stmt, "orelse", []) or []
                is_elif = isinstance(stmt, ast.If) and len(orelse) == 1 and isinstance(orelse[0], ast.If)
                self._nesting(orelse, depth if is_elif else depth + 1)  # an elif chain is not deeper
                self._nesting(getattr(stmt, "finalbody", []) or [], depth + 1)
                for handler in getattr(stmt, "handlers", []) or []:
                    self._nesting(handler.body, depth + 1)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._nesting(stmt.body, 1)

    # -- statements --------------------------------------------------------------------------
    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id in SHADOWED:
                    self.add(node, "maintainability", "SMELL-shadow-builtin", f"{target.id} hides a builtin", "low")
                if SECRET_NAME.search(target.id) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str) and len(node.value.value) >= 6:
                    self.add(node, "security", "CWE-798", f"hard-coded credential in {target.id}", "high")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self.add(node, "maintainability", "SMELL-bare-except", "bare except", "low", end=node.lineno)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert):
        if AUTH_CONTEXT.search(self.context()):
            self.add(node, "security", "CWE-617", "assert used for an access check", "medium")
        self.generic_visit(node)

    # -- calls -------------------------------------------------------------------------------
    def visit_Call(self, node: ast.Call):
        name = _dotted(node.func)
        short = name.rsplit(".", 1)[-1]
        first = node.args[0] if node.args else None
        if name in ("eval", "exec"):
            self.add(node, "security", "CWE-95", f"{name} of a value", "high")
        elif name in ("os.system", "os.popen"):
            self.add(node, "security", "CWE-78", f"{name} runs a shell", "high")
        elif name.startswith("subprocess.") and isinstance(_kw(node, "shell"), ast.Constant) and _kw(node, "shell").value is True:
            self.add(node, "security", "CWE-78", "subprocess with shell=True", "high")
        elif name in ("pickle.loads", "pickle.load", "marshal.loads", "dill.loads"):
            self.add(node, "security", "CWE-502", f"{name} of untrusted data", "high")
        elif name == "yaml.load" and _kw(node, "Loader") is None and len(node.args) < 2:
            self.add(node, "security", "CWE-502", "yaml.load without a safe loader", "high")
        elif name in ("hashlib.md5", "hashlib.sha1") or (name == "hashlib.new" and isinstance(first, ast.Constant)
                                                          and str(first.value).lower() in ("md5", "sha1")):
            self.add(node, "security", "CWE-328", f"weak hash {name}", "medium")
        elif name.startswith("random.") and SECURITY_CONTEXT.search(self.context()):
            self.add(node, "security", "CWE-330", f"{name} in a security context", "medium")
        elif name == "tempfile.mktemp":
            self.add(node, "security", "CWE-377", "tempfile.mktemp", "medium")
        elif isinstance(_kw(node, "verify"), ast.Constant) and _kw(node, "verify").value is False:
            self.add(node, "security", "CWE-295", "verify=False", "high")
        elif short in ("execute", "executemany") and first is not None:
            value = self.assigned_names.get(first.id) if isinstance(first, ast.Name) else first
            if value is not None and _is_dynamic_string(value):
                self.add(node, "security", "CWE-89", "SQL text built from values", "high")
        elif name == "os.path.join" and self.params_stack and any(
                isinstance(a, ast.Name) and a.id in self.params_stack[-1] for a in node.args[1:]):
            self.add(node, "security", "CWE-22", "a path is built from a function argument", "medium")
        for kw in node.keywords:
            if kw.arg and SECRET_NAME.search(kw.arg) and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str) and len(kw.value.value) >= 6:
                self.add(node, "security", "CWE-798", f"hard-coded credential in {kw.arg}=", "high")
        self.generic_visit(node)


def analyze_code(code: str) -> list[Finding]:
    tree = ast.parse(code)
    visitor = _Visitor()
    visitor.visit(tree)
    unique = {(f.rule, f.line_start, f.line_end): f for f in visitor.findings}
    return sorted(unique.values(), key=lambda f: (f.line_start, f.rule or ""))


class BuiltinAnalyzer:
    name = NAME
    version = VERSION

    def available(self) -> bool:
        return True

    def analyze(self, sample) -> list[Finding]:
        return analyze_code(sample.code)
