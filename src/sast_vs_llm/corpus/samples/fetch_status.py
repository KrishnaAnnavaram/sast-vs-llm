def fetch_status(url):
    """Return the HTTP status of a partner endpoint."""
    import requests

    response = requests.get(url, timeout=10, verify=False)
    return response.status_code
