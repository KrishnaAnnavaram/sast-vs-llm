"""Command line interface: ``sast-vs-llm <command> [options]``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from sast_vs_llm.analyzers.builtin import analyze_code
from sast_vs_llm.blind import make_sheet, score_sheet
from sast_vs_llm.config import ANALYZER_NAMES, ConfigError, Settings, build_analyzers, build_llm, load_dotenv
from sast_vs_llm.corpus import CorpusError, corpus_summary, load_corpus
from sast_vs_llm.hybrid import SimulatedTriage, evaluate_hybrid
from sast_vs_llm.llm import LLMError, SimulatedReviewer
from sast_vs_llm.runner import StaleResultError, load_results, run_benchmark
from sast_vs_llm.scoring import score, to_markdown


def _names(text: str) -> list[str]:
    return [n.strip() for n in text.split(",") if n.strip()]


def cmd_corpus(args, settings: Settings) -> int:
    samples = load_corpus(args.corpus)
    print(json.dumps(corpus_summary(samples), indent=2))
    if args.list:
        for s in samples:
            rules = ",".join(lab.rule for lab in s.labels) or "-"
            print(f"{s.id:22s} {s.kind:10s} {s.difficulty:6s} {s.style:9s} tests={len(s.tests)} labels={rules}")
    return 0


def cmd_analyze(args, settings: Settings) -> int:
    code = Path(args.file).read_text(encoding="utf-8")
    findings = analyze_code(code)
    for f in findings:
        print(f"{args.file}:{f.line_start}-{f.line_end} [{f.category}] {f.rule}: {f.message}")
    print(f"{len(findings)} finding(s) from the builtin analyzer")
    return 0


def cmd_run(args, settings: Settings) -> int:
    samples = load_corpus(args.corpus)
    analyzers = build_analyzers(_names(args.analyzers), settings)
    out = Path(args.out) if args.out else settings.results_dir
    summary = run_benchmark(samples, analyzers, out, repeats=args.repeats or settings.repeats)
    print(f"wrote {summary.files_written} result files to {out}")
    for name, version in summary.analyzers.items():
        print(f"  ran     {name} ({version})")
    for name, reason in summary.skipped.items():
        print(f"  skipped {name}: {reason}")
    return 0


def cmd_score(args, settings: Settings) -> int:
    samples = load_corpus(args.corpus)
    results = load_results(args.results or settings.results_dir, samples, allow_stale=args.allow_stale)
    text = to_markdown(score(results, samples, tol=args.tol, strict=args.strict))
    if args.markdown:
        Path(args.markdown).write_text(text, encoding="utf-8")
        print(f"wrote {args.markdown}")
    else:
        print(text)
    return 0


def cmd_hybrid(args, settings: Settings) -> int:
    samples = load_corpus(args.corpus)
    results = load_results(args.results or settings.results_dir, samples)
    client = SimulatedTriage() if settings.provider in ("simulated", "none") else build_llm(settings)
    res = evaluate_hybrid(results, samples, args.analyzer, client, strict=args.strict)
    print(f"hybrid: {args.analyzer} findings, then triage by {client.model}")
    for label, m in (("before", res.before), ("after", res.after)):
        print(f"  {label:6s} TP={m['tp']} FP={m['fp']} FN={m['fn']} precision={m['precision']:.2f} recall={m['recall']:.2f}")
    return 0


def cmd_blind_sheet(args, settings: Settings) -> int:
    samples = load_corpus(args.corpus)
    results = load_results(args.results or settings.results_dir, samples)
    n = make_sheet(results, samples, args.sheet, args.key, seed=args.seed)
    print(f"wrote {n} reviews to {args.sheet}. Keep {args.key} away from the raters.")
    return 0


def cmd_blind_score(args, settings: Settings) -> int:
    for row in score_sheet(args.sheet, args.key):
        lo, hi = row["ci"]
        print(f"{row['reviewer']:30s} n={row['ratings']:3d} mean={row['mean']:.2f} 95% CI {lo:.2f}-{hi:.2f}")
    return 0


def cmd_demo(args, settings: Settings) -> int:
    samples = load_corpus()
    print(json.dumps(corpus_summary(samples)))
    analyzers = build_analyzers(["builtin", "tests"], settings)
    from sast_vs_llm.review import LLMReviewer

    analyzers.append(LLMReviewer(SimulatedReviewer(), name="simulated-llm"))
    with tempfile.TemporaryDirectory() as tmp:
        run_benchmark(samples, analyzers, tmp, repeats=3)
        results = load_results(tmp, samples)
        print(to_markdown(score(results, samples)))
        res = evaluate_hybrid(results, samples, "simulated-llm", SimulatedTriage())
        print("hybrid (simulated-llm + simulated triage):")
        for label, m in (("before", res.before), ("after", res.after)):
            print(f"  {label:6s} TP={m['tp']} FP={m['fp']} FN={m['fn']} precision={m['precision']:.2f} recall={m['recall']:.2f}")
    print("\nNOTE: simulated-llm is an offline stand-in, not a language model. Its numbers say nothing about LLMs.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sast-vs-llm", description="Benchmark SAST tools and LLM reviewers on a labelled corpus.")
    p.add_argument("--env-file", default=".env")
    sub = p.add_subparsers(dest="command", required=True)

    def with_corpus(sp):
        sp.add_argument("--corpus", help="corpus folder with manifest.json (default: the bundled corpus)")
        return sp

    s = with_corpus(sub.add_parser("corpus", help="validate the corpus and print a summary"))
    s.add_argument("--list", action="store_true")
    s.set_defaults(func=cmd_corpus)

    s = sub.add_parser("analyze", help="run the builtin analyzer on one Python file")
    s.add_argument("file")
    s.set_defaults(func=cmd_analyze)

    s = with_corpus(sub.add_parser("run", help="run analyzers on the corpus and store raw results"))
    s.add_argument("--analyzers", default="builtin,tests,bandit,pylint,ruff,llm", help=f"comma list from {ANALYZER_NAMES}")
    s.add_argument("--repeats", type=int, default=None, help="LLM repeats (default: SAST_LLM_REPEATS)")
    s.add_argument("--out", help="results folder (default: SAST_RESULTS_DIR)")
    s.set_defaults(func=cmd_run)

    s = with_corpus(sub.add_parser("score", help="score stored results against the labels"))
    s.add_argument("--results")
    s.add_argument("--strict", action="store_true", help="also require the same rule family")
    s.add_argument("--tol", type=int, default=2, help="line tolerance (default 2)")
    s.add_argument("--markdown", help="write the report to this file")
    s.add_argument("--allow-stale", action="store_true")
    s.set_defaults(func=cmd_score)

    s = with_corpus(sub.add_parser("hybrid", help="measure an LLM triage step on stored SAST findings"))
    s.add_argument("--analyzer", default="bandit")
    s.add_argument("--results")
    s.add_argument("--strict", action="store_true")
    s.set_defaults(func=cmd_hybrid)

    s = with_corpus(sub.add_parser("blind-sheet", help="write a blinded rating sheet and its key"))
    s.add_argument("--results")
    s.add_argument("--sheet", default="ratings.csv")
    s.add_argument("--key", default="ratings_key.json")
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_blind_sheet)

    s = sub.add_parser("blind-score", help="join a filled rating sheet with its key")
    s.add_argument("--sheet", default="ratings.csv")
    s.add_argument("--key", default="ratings_key.json")
    s.set_defaults(func=cmd_blind_score)

    s = sub.add_parser("demo", help="offline demo: builtin, tests and a simulated reviewer")
    s.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(args.env_file)
    try:
        return int(args.func(args, Settings.from_env()))
    except (ConfigError, CorpusError, StaleResultError, LLMError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
