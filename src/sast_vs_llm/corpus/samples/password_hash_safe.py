import hashlib
import hmac


def hash_password(password, salt_hex, iterations=200_000):
    """PBKDF2-HMAC-SHA256 with a per-user salt."""
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), iterations)
    return digest.hex()


def verify_password(password, salt_hex, expected_hex):
    return hmac.compare_digest(hash_password(password, salt_hex), expected_hex)
