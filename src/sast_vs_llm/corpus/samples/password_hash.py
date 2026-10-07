import hashlib


def hash_password(password):
    """Return the stored form of a password."""
    return hashlib.md5(password.encode("utf-8")).hexdigest()
