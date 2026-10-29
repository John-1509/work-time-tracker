"""Database layer: connection, schema and time helpers.

All timestamps are stored as UTC strings in one fixed format
("2026-10-28T14:32:05.123456Z"). Because the format is fixed-width,
comparing the strings alphabetically is the same as comparing the times.
"""
import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.environ.get("TIMETRACK_DB", "data.db")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS time_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    task        TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,  -- NULL means the timer is still running
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- Rule enforced by the database itself: one running timer per employee.
CREATE UNIQUE INDEX IF NOT EXISTS one_running_timer_per_employee
    ON time_entries (employee_id) WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS entries_by_employee_and_start
    ON time_entries (employee_id, started_at);
"""


def now_utc() -> str:
    """Current time as a UTC string in the storage format."""
    return datetime.now(timezone.utc).strftime(TIME_FORMAT)


def get_connection(path: str | None = None) -> sqlite3.Connection:
    """Open a connection. Use ':memory:' as path for throwaway test databases."""
    conn = sqlite3.connect(path or DEFAULT_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not exist yet (safe to call repeatedly)."""
    conn.executescript(SCHEMA)
    conn.commit()
