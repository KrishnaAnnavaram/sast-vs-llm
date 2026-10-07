"""Blinded human rating of review usefulness, kept apart from the accuracy scores.

``make_sheet`` writes one CSV row for each (sample, reviewer) review in a shuffled order with an
opaque item id, and a separate key file that maps each item id to the reviewer. Raters see only the
code path and the review text. ``score_sheet`` joins the filled sheet with the key.
"""

from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path

from sast_vs_llm.corpus import Sample
from sast_vs_llm.runner import Results

RATING_COLUMNS = ["item_id", "sample_id", "code_file", "review", "usefulness_1_to_5", "comment"]


def render_review(findings) -> str:
    if not findings:
        return "No problems reported."
    return "\n".join(f"Lines {f.line_start}-{f.line_end} ({f.category}): {f.message or f.rule or 'no text'}"
                     for f in sorted(findings, key=lambda f: f.line_start))


def make_sheet(results: Results, samples: list[Sample], sheet_path: str | Path, key_path: str | Path,
               seed: int = 0, analyzers: list[str] | None = None) -> int:
    names = analyzers or results.analyzers
    items = []
    for s in samples:
        for name in names:
            runs = results.findings.get(name, {}).get(s.id)
            if runs:
                items.append((s, name, render_review(runs[0])))
    rng = random.Random(seed)
    rng.shuffle(items)
    key = {}
    with open(sheet_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(RATING_COLUMNS)
        for i, (s, name, text) in enumerate(items, 1):
            item_id = f"R{i:04d}"
            key[item_id] = name
            w.writerow([item_id, s.id, s.path.name, text, "", ""])
    Path(key_path).write_text(json.dumps(key, indent=1), encoding="utf-8")
    return len(items)


def score_sheet(sheet_path: str | Path, key_path: str | Path) -> list[dict]:
    """Mean usefulness for each reviewer with a normal-approximation 95 % interval."""
    key = json.loads(Path(key_path).read_text(encoding="utf-8"))
    ratings: dict[str, list[float]] = {}
    with open(sheet_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = (row.get("usefulness_1_to_5") or "").strip()
            if not raw:
                continue
            value = float(raw)
            if not 1 <= value <= 5:
                raise ValueError(f"{row['item_id']}: rating {value} is not between 1 and 5")
            if row["item_id"] not in key:
                raise KeyError(f"{row['item_id']} is not in the key file")
            ratings.setdefault(key[row["item_id"]], []).append(value)
    out = []
    for name, vals in sorted(ratings.items()):
        n = len(vals)
        mean = sum(vals) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else float("nan")
        half = 1.96 * sd / math.sqrt(n) if n > 1 else float("nan")
        out.append({"reviewer": name, "ratings": n, "mean": mean, "ci": (mean - half, mean + half)})
    return out
