"""Run analysers over the corpus and store each raw result as JSON with full provenance.

Layout of a results folder::

    results/
      manifest.json                     # date, corpus version, analyser versions, repeats, skipped tools
      raw/<analyzer>/<sample>__r<k>.json  # findings + sample SHA-256 + run metadata

``load_results`` refuses a raw file whose sample SHA-256 differs from the current corpus file, so a
report can never mix tool output with code that the tool did not see.
"""

from __future__ import annotations

import json
import platform
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sast_vs_llm.corpus import Sample
from sast_vs_llm.findings import Finding


class StaleResultError(RuntimeError):
    """A stored result belongs to another version of a sample file."""


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


@dataclass
class RunSummary:
    out_dir: Path
    analyzers: dict[str, str] = field(default_factory=dict)  # name -> version
    skipped: dict[str, str] = field(default_factory=dict)  # name -> reason
    files_written: int = 0


def run_benchmark(samples: list[Sample], analyzers: list, out_dir: str | Path, repeats: int = 1,
                  corpus_version: str = "1.0", progress=None) -> RunSummary:
    """Run each analyser on each sample. LLM reviewers run ``repeats`` times, the others once."""
    out = Path(out_dir)
    summary = RunSummary(out)
    for analyzer in analyzers:
        if not analyzer.available():
            summary.skipped[analyzer.name] = "not installed"
            continue
        is_llm = hasattr(analyzer, "client")
        n_rep = max(1, repeats) if is_llm else 1
        folder = out / "raw" / safe_name(analyzer.name)
        folder.mkdir(parents=True, exist_ok=True)
        summary.analyzers[analyzer.name] = str(analyzer.version)
        for sample in samples:
            for rep in range(n_rep):
                findings = analyzer.analyze(sample, repeat=rep) if is_llm else analyzer.analyze(sample)
                record = {
                    "analyzer": analyzer.name,
                    "analyzer_version": str(analyzer.version),
                    "sample_id": sample.id,
                    "sample_sha256": sample.sha256,
                    "repeat": rep,
                    "findings": [f.to_dict() for f in findings],
                    "meta": dict(getattr(analyzer, "last_meta", {}) or {}) if is_llm else {},
                }
                (folder / f"{sample.id}__r{rep}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
                summary.files_written += 1
                if progress:
                    progress(analyzer.name, sample.id, rep)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_version": corpus_version,
        "samples": len(samples),
        "repeats": repeats,
        "python": platform.python_version(),
        "analyzers": summary.analyzers,
        "skipped": summary.skipped,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary


@dataclass
class Results:
    # analyzer -> sample id -> list of repeats -> findings
    findings: dict[str, dict[str, list[list[Finding]]]] = field(default_factory=dict)
    meta: dict[str, dict[str, list[dict]]] = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)

    @property
    def analyzers(self) -> list[str]:
        return sorted(self.findings)


def load_results(out_dir: str | Path, samples: list[Sample], allow_stale: bool = False) -> Results:
    root = Path(out_dir)
    if not (root / "raw").is_dir():
        raise FileNotFoundError(f"{root / 'raw'} does not exist. Run `sast-vs-llm run` first.")
    by_id = {s.id: s for s in samples}
    res = Results(manifest=json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                  if (root / "manifest.json").is_file() else {})
    stale = []
    for path in sorted((root / "raw").glob("*/*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        sample = by_id.get(rec["sample_id"])
        if sample is None:
            continue
        if rec["sample_sha256"] != sample.sha256:
            stale.append(f"{rec['analyzer']}/{rec['sample_id']}")
            if not allow_stale:
                continue
        reps = res.findings.setdefault(rec["analyzer"], {}).setdefault(rec["sample_id"], [])
        metas = res.meta.setdefault(rec["analyzer"], {}).setdefault(rec["sample_id"], [])
        while len(reps) <= rec["repeat"]:
            reps.append([])
            metas.append({})
        reps[rec["repeat"]] = [Finding.from_dict(d) for d in rec["findings"]]
        metas[rec["repeat"]] = rec.get("meta", {})
    if stale and not allow_stale:
        raise StaleResultError(f"{len(stale)} results belong to an older sample file, first {stale[0]}. "
                               "Run the benchmark again or pass --allow-stale.")
    return res
