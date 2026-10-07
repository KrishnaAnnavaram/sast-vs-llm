import re
import subprocess

HOST_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def ping(host):
    """Send one ping. The host is checked and is never passed through a shell."""
    if not HOST_PATTERN.fullmatch(host):
        raise ValueError("invalid host name")
    return subprocess.run(["ping", "-c", "1", host], check=False, capture_output=True).returncode
