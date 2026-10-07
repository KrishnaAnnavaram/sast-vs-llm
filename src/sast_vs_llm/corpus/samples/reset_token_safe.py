import secrets


def make_reset_token(nbytes=32):
    """Token for the password-reset link, from the operating system generator."""
    return secrets.token_urlsafe(nbytes)


def token_length(nbytes=32):
    return len(make_reset_token(nbytes))
