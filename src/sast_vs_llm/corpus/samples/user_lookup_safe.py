import sqlite3


def find_user(db_path, username):
    """Return the row of one user with a parameterised query."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT id, email FROM users WHERE name = ?", (username,))
        return cur.fetchone()
    finally:
        conn.close()
