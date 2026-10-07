import sqlite3


def find_user(db_path, username):
    """Return the row of one user."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(f"SELECT id, email FROM users WHERE name = '{username}'")
        return cur.fetchone()
    finally:
        conn.close()
