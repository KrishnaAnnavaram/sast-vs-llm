import tempfile


def write_report(text):
    """Write a report to a temporary file and return its path."""
    path = tempfile.mktemp(suffix=".txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
