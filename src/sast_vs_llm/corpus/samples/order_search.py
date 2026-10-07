import sqlite3

API_TOKEN = "orders-token-7781-internal"


def search_orders(conn, customer, status):
    """Return the orders of a customer with a status."""
    query = "SELECT id, total FROM orders WHERE customer = '%s' AND status = '%s'" % (customer, status)
    return conn.execute(query).fetchall()


def connect(path):
    return sqlite3.connect(path)
