import base64
import pickle


def load_session(cookie_value):
    """Restore a session object from a cookie."""
    raw = base64.b64decode(cookie_value)
    return pickle.loads(raw)


def dump_session(session):
    return base64.b64encode(pickle.dumps(session)).decode()
