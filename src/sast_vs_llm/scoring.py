"""Score stored results against the labels: precision, recall, F1, clean-control false alarms,
slices by difficulty and style, consistency over repeats and LLM output quality."""

from __future__ import annotations

from dataclasses import dataclass, field

from sast_vs_llm.corpus import Sample
from sast_vs_llm.findings import CATEGORIES
from sast_vs_llm.matching import match
from sast_vs_llm.metrics import mean_pairwise_jaccard, prf, wilson
from sast_vs_llm.runner import Results


@dataclass
class Scoreboard:
    rows: list[dict] = field(default_factory=list)  # analyzer x category
    slices: list[dict] = field(default_factory=list)  # analyzer x (difficulty|style) on algorithm samples
    clean: list[dict] = field(default_factory=list)  # analyzer: false alarms on clean controls
    consistency: list[dict] = field(default_factory=list)  # analyzer: repeats, Jaccard, F1 range
    llm_quality: list[dict] = field(default_factory=list)  # analyzer: ungrounded fields, dropped, latency


def _counts(samples: list[Sample], per_sample: dict[str, list], repeat: int, category: str | None,
            tol: int, strict: bool) -> tuple[int, int, int]:
    tp = fp = fn = 0
    for s in samples:
        runs = per_sample.get(s.id)
        if runs is None or repeat >= len(runs):
            continue
        findings = runs[repeat]
        labels = s.labels
        if category is not None:
            findings = [f for f in findings if f.category == category]
            labels = [lab for lab in labels if lab.category == category]
        m = match(labels, findings, tol=tol, strict=strict)
        tp, fp, fn = tp + len(m.tp), fp + len(m.fp), fn + len(m.fn)
    return tp, fp, fn


def score(results: Results, samples: list[Sample], tol: int = 2, strict: bool = False) -> Scoreboard:
    board = Scoreboard()
    algo = [s for s in samples if s.problem in {"valid_anagram", "majority_element_ii", "word_search_ii"}]
    clean = [s for s in samples if s.kind == "clean"]
    for name in results.analyzers:
        per_sample = results.findings[name]
        scored = [s for s in samples if s.id in per_sample]
        for category in (None, *CATEGORIES):
            row = {"analyzer": name, "category": category or "all"}
            row.update(prf(*_counts(scored, per_sample, 0, category, tol, strict)))
            board.rows.append(row)
        for dim in ("difficulty", "style"):
            for value in sorted({getattr(s, dim) for s in algo}):
                part = [s for s in algo if getattr(s, dim) == value and s.id in per_sample]
                if part:
                    m = prf(*_counts(part, per_sample, 0, None, tol, strict))
                    board.slices.append({"analyzer": name, "slice": f"{dim}={value}", "samples": len(part),
                                         "tp": m["tp"], "fp": m["fp"], "fn": m["fn"], "recall": m["recall"]})
        flagged = sum(1 for s in clean if s.id in per_sample and per_sample[s.id][0])
        n_clean = sum(1 for s in clean if s.id in per_sample)
        lo, hi = wilson(flagged, n_clean)
        board.clean.append({"analyzer": name, "clean_samples": n_clean, "flagged": flagged,
                            "false_alarm_rate": flagged / n_clean if n_clean else float("nan"), "ci": (lo, hi)})
        n_rep = max(len(r) for r in per_sample.values())
        if n_rep > 1:
            jac = [mean_pairwise_jaccard([{f.key() for f in run} for run in runs])
                   for runs in per_sample.values() if len(runs) > 1]
            f1s = [prf(*_counts(scored, per_sample, k, None, tol, strict))["f1"] for k in range(n_rep)]
            board.consistency.append({"analyzer": name, "repeats": n_rep, "mean_jaccard": sum(jac) / len(jac),
                                      "f1_min": min(f1s), "f1_max": max(f1s)})
        metas = [m for runs in results.meta.get(name, {}).values() for m in runs if m]
        if metas:
            lat = [m.get("latency_s", 0.0) for m in metas if "latency_s" in m]
            board.llm_quality.append({
                "analyzer": name, "calls": len(metas),
                "replies_with_ungrounded_fields": sum(1 for m in metas if m.get("ungrounded_fields")),
                "dropped_findings": sum(len(m.get("dropped", [])) for m in metas),
                "parse_errors": sum(1 for m in metas if m.get("parse_error")),
                "mean_latency_s": sum(lat) / len(lat) if lat else float("nan"),
            })
    return board


def _fmt(v) -> str:
    if isinstance(v, float):
        return "n/a" if v != v else f"{v:.2f}"
    if isinstance(v, tuple):
        return "-".join(_fmt(x) for x in v)
    return str(v)


def to_markdown(board: Scoreboard) -> str:
    lines = ["## Detection (repeat 0)", "",
             "| Analyzer | Category | TP | FP | FN | Precision (95% CI) | Recall (95% CI) | F1 |",
             "|---|---|---|---|---|---|---|---|"]
    for r in board.rows:
        lines.append(f"| {r['analyzer']} | {r['category']} | {r['tp']} | {r['fp']} | {r['fn']} | "
                     f"{_fmt(r['precision'])} ({_fmt(r['precision_ci'])}) | {_fmt(r['recall'])} ({_fmt(r['recall_ci'])}) | "
                     f"{_fmt(r['f1'])} |")
    lines += ["", "## False alarms on clean controls", "", "| Analyzer | Clean samples | Flagged | Rate (95% CI) |",
              "|---|---|---|---|"]
    for r in board.clean:
        lines.append(f"| {r['analyzer']} | {r['clean_samples']} | {r['flagged']} | {_fmt(r['false_alarm_rate'])} ({_fmt(r['ci'])}) |")
    lines += ["", "## Algorithm samples by difficulty and style", "", "| Analyzer | Slice | Samples | TP | FP | FN | Recall |",
              "|---|---|---|---|---|---|---|"]
    for r in board.slices:
        lines.append(f"| {r['analyzer']} | {r['slice']} | {r['samples']} | {r['tp']} | {r['fp']} | {r['fn']} | {_fmt(r['recall'])} |")
    if board.consistency:
        lines += ["", "## Consistency over repeats", "", "| Analyzer | Repeats | Mean Jaccard | F1 min | F1 max |",
                  "|---|---|---|---|---|"]
        for r in board.consistency:
            lines.append(f"| {r['analyzer']} | {r['repeats']} | {_fmt(r['mean_jaccard'])} | {_fmt(r['f1_min'])} | {_fmt(r['f1_max'])} |")
    if board.llm_quality:
        lines += ["", "## LLM output quality", "",
                  "| Analyzer | Calls | Replies with ungrounded fields | Dropped findings | Parse errors | Mean latency (s) |",
                  "|---|---|---|---|---|---|"]
        for r in board.llm_quality:
            lines.append(f"| {r['analyzer']} | {r['calls']} | {r['replies_with_ungrounded_fields']} | {r['dropped_findings']} | "
                         f"{r['parse_errors']} | {_fmt(r['mean_latency_s'])} |")
    return "\n".join(lines) + "\n"
