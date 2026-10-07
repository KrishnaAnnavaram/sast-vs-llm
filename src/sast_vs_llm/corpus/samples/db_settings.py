import sqlite3

DB_USER = "report_service"
DB_PASSWORD = "change-me-2931"


def connection_string(host):
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{host}:5432/reports"


def open_local(path):
    return sqlite3.connect(path)
