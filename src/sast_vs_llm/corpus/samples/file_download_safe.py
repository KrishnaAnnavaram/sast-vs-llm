from pathlib import Path

BASE_DIR = Path("/srv/files").resolve()


def safe_path(filename):
    """Return the path in BASE_DIR, or raise ValueError if the name leaves it."""
    path = (BASE_DIR / filename).resolve()
    if not path.is_relative_to(BASE_DIR):
        raise ValueError("path leaves the download folder")
    return path


def read_user_file(filename):
    return safe_path(filename).read_bytes()
