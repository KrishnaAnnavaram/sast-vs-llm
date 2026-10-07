import os

BASE_DIR = "/srv/files"


def read_user_file(filename):
    """Return the bytes of a file that the user asks for."""
    path = os.path.join(BASE_DIR, filename)
    with open(path, "rb") as handle:
        return handle.read()
