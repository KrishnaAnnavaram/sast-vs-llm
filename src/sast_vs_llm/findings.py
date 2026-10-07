"""The finding record that every analyser returns, and the canonical rule vocabulary."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CATEGORIES = ("security", "maintainability", "correctness")
SEVERITIES = ("low", "medium", "high")

# canonical rule id -> (category, short description)
RULES: dict[str, tuple[str, str]] = {
    "CWE-22": ("security", "path traversal"),
    "CWE-78": ("security", "OS command injection"),
    "CWE-89": ("security", "SQL injection"),
    "CWE-95": ("security", "eval injection"),
    "CWE-259": ("security", "hard-coded password"),
    "CWE-295": ("security", "certificate validation turned off"),
    "CWE-328": ("security", "weak hash"),
    "CWE-330": ("security", "insecure random values"),
    "CWE-377": ("security", "insecure temporary file"),
    "CWE-502": ("security", "unsafe deserialisation"),
    "CWE-617": ("security", "assert used for a security check"),
    "CWE-798": ("security", "hard-coded credentials"),
    "SMELL-bare-except": ("maintainability", "bare except"),
    "SMELL-deep-nesting": ("maintainability", "deep nesting"),
    "SMELL-mutable-default": ("maintainability", "mutable default argument"),
    "SMELL-shadow-builtin": ("maintainability", "name hides a builtin"),
    "SMELL-unused-variable": ("maintainability", "unused variable"),
    "SMELL-other": ("maintainability", "other maintainability finding"),
    "BUG-hardcoded-case": ("correctness", "hard-coded special case"),
    "BUG-wrong-comparison": ("correctness", "wrong comparison"),
    "BUG-off-by-one": ("correctness", "off-by-one"),
    "BUG-test-failure": ("correctness", "a unit test fails"),
    "BUG-other": ("correctness", "other logic error"),
}

# CWE-259 is a child of CWE-798. The matcher treats them as one rule family.
RULE_FAMILY = {"CWE-259": "CWE-798"}


def rule_family(rule: str | None) -> str | None:
    if rule is None:
        return None
    return RULE_FAMILY.get(rule, rule)


@dataclass
class Finding:
    analyzer: str
    category: str
    line_start: int
    line_end: int
    rule: str | None = None  # canonical rule id, or None when the analyser gives no mappable rule
    severity: str = "medium"
    message: str = ""
    raw_rule: str = ""  # the analyser's own rule id, for audit
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category {self.category!r}")
        if self.line_start < 1 or self.line_end < self.line_start:
            raise ValueError(f"bad line range {self.line_start}-{self.line_end}")
        if self.rule is not None and self.rule not in RULES:
            raise ValueError(f"unknown rule {self.rule!r}")
        if self.severity not in SEVERITIES:
            self.severity = "medium"

    def key(self, bucket: int = 3) -> tuple:
        """A coarse identity used for the consistency measure between repeats."""
        return (self.category, rule_family(self.rule), self.line_start // bucket)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        return cls(**d)
