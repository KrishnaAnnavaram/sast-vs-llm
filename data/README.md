# Data

sast-vs-llm needs no download. The labelled corpus is part of the package:

| Path | Contents |
|---|---|
| `src/sast_vs_llm/corpus/manifest.json` | One entry for each sample: id, file, problem, difficulty, style, kind, labels, unit tests |
| `src/sast_vs_llm/corpus/samples/*.py` | 30 Python samples written for this benchmark (MIT, like the rest of the repository) |

The samples contain planted vulnerabilities on purpose. Do not copy them into production code.

## Manifest format

```json
{
  "id": "ping_host",
  "file": "samples/ping_host.py",
  "problem": "network_check",
  "difficulty": "easy",
  "style": "functions",
  "kind": "vulnerable",
  "labels": [{"category": "security", "rule": "CWE-78", "anchor": "return os.system(", "span": 1, "note": "..."}],
  "tests": [{"call": "ping", "args": ["127.0.0.1"], "expected": 0, "class": null}]
}
```

- `kind` is `vulnerable`, `smelly`, `buggy` or `clean`. A `clean` sample is a control with no labels.
- `anchor` is a text that occurs exactly once in the file. The loader finds its line.
- `span` is the number of lines from the anchor line.
- `rule` is a canonical id from `src/sast_vs_llm/findings.py` (CWE ids, `SMELL-*`, `BUG-*`).

## Your own corpus

Make a folder with the same layout and pass `--corpus <folder>` to `corpus`, `run`, `score`, `hybrid` and `blind-sheet`.
CWE-annotated public sets (for example the OWASP Benchmark for Python or SARD test cases) can be changed into this format. Read their licenses first.

## Results (not committed)

`sast-vs-llm run` writes raw tool and LLM output to `results/` (or `SAST_RESULTS_DIR`). Git ignores this folder.
