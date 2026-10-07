"""sast-vs-llm: a reproducible benchmark of static analysers and LLM code reviewers.

Every analyser runs on a labelled corpus (planted vulnerabilities, smells and logic errors plus clean
controls). Findings are matched to the labels by category, line and rule, so precision and recall
are measured, not judged.
"""

__version__ = "0.1.0"
