import random
import string

ALPHABET = string.ascii_letters + string.digits


def make_reset_token(length=32):
    """Token for the password-reset link."""
    return "".join(random.choice(ALPHABET) for _ in range(length))
