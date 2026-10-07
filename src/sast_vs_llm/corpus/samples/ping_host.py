import os


def ping(host):
    """Send one ping to a host and return the exit status."""
    return os.system(f"ping -c 1 {host}")
