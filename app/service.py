"""Business logic. No HTTP code here: every function takes a database connection.

Functions that depend on the current time accept an optional `now` (a string in
the storage format) so tests can control the clock.
"""
import sqlite3
import unicodedata
from datetime import datetime, timezone

from app.db import TIME_FORMAT, now_utc


# Limits (see LOG.md): years outside this range break the fixed-width time format
# or overflow, ids above the SQLite integer maximum crash the query, and unbounded
# text would break the page layout.
MIN_YEAR, MAX_YEAR = 1970, 2200
MAX_ID = 2**63 - 1
MAX_NAME_LENGTH = 100
MAX_TASK_LENGTH = 500


# --- Errors -----------------------------------------------------------------
# The routes translate these into HTTP status codes.

class ServiceError(Exception):
    """Base class for expected, reportable errors."""


class NotFound(ServiceError):
    """Something does not exist (404)."""


class Conflict(ServiceError):
    """The request clashes with the current state (409)."""


class InvalidInput(ServiceError):
    """The input is not acceptable (422)."""


# --- Time helpers -----------------------------------------------------------

def normalize_time(value: str) -> str:
    """Parse an ISO 8601 datetime and return it in the storage format (UTC).

    A value without a time zone is treated as UTC. Normalising matters: the
    stored strings are compared alphabetically, which only works if every
    string has exactly the same shape.
    """
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InvalidInput(f"Invalid datetime: {value!r} (use ISO 8601, e.g. 2026-10-28T09:00:00Z)")
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        raise InvalidInput(f"Datetime must be between the years {MIN_YEAR} and {MAX_YEAR}")
    return parsed.strftime(TIME_FORMAT)


def _to_datetime(stored: str) -> datetime:
    return datetime.strptime(stored, TIME_FORMAT).replace(tzinfo=timezone.utc)


def _seconds_between(start: str, end: str) -> float:
    """Seconds from start to end (storage-format strings), never negative."""
    return max(0.0, (_to_datetime(end) - _to_datetime(start)).total_seconds())


def _clean(value: str, field: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    # strip() keeps invisible "format" characters (zero-width space etc.), so check without them too.
    visible = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Cf").strip()
    if not visible:
        raise InvalidInput(f"{field} must not be empty")
    if len(cleaned) > max_length:
        raise InvalidInput(f"{field} must be at most {max_length} characters")
    return cleaned


def _check_period(from_: str | None, to: str | None) -> tuple[str | None, str | None]:
    start = normalize_time(from_) if from_ else None
    end = normalize_time(to) if to else None
    if start and end and start > end:
        raise InvalidInput("'from' must not be after 'to'")
    return start, end


def _clipped_seconds(entry: sqlite3.Row, start: str | None, end: str | None, now: str) -> float:
    """Seconds of this entry that lie inside [start, end). A running entry ends at `now`."""
    entry_end = entry["ended_at"] or now
    lo = max(entry["started_at"], start) if start else entry["started_at"]
    hi = min(entry_end, end) if end else entry_end
    return _seconds_between(lo, hi)


def _overlapping_entries(conn, start: str | None, end: str | None, employee_id: int | None = None):
    """Entries that overlap the period: started before `end` and ended after `start` (or still running)."""
    sql = "SELECT * FROM time_entries WHERE 1=1"
    params: list = []
    if employee_id is not None:
        sql += " AND employee_id = ?"
        params.append(employee_id)
    if end:
        sql += " AND started_at < ?"
        params.append(end)
    if start:
        sql += " AND (ended_at IS NULL OR ended_at > ?)"
        params.append(start)
    sql += " ORDER BY started_at, id"
    return conn.execute(sql, params).fetchall()


# --- Employees --------------------------------------------------------------

def _employee_row(conn, employee_id: int) -> sqlite3.Row:
    row = None
    if 1 <= employee_id <= MAX_ID:  # a larger number cannot be bound to an SQLite integer
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise NotFound(f"Employee {employee_id} not found")
    return row


def add_employee(conn, name: str, now: str | None = None) -> dict:
    name = _clean(name, "name", MAX_NAME_LENGTH)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO employees (name, created_at) VALUES (?, ?)",
                (name, now or now_utc()),
            )
    except sqlite3.IntegrityError:
        raise Conflict(f"An employee named {name!r} already exists")
    return _employee_dict(_employee_row(conn, cur.lastrowid), running=None)


def _employee_dict(row: sqlite3.Row, running: sqlite3.Row | None) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "running": None if running is None else {
            "entry_id": running["id"],
            "task": running["task"],
            "started_at": running["started_at"],
        },
    }


def list_employees(conn) -> list[dict]:
    running = {
        r["employee_id"]: r
        for r in conn.execute("SELECT * FROM time_entries WHERE ended_at IS NULL")
    }
    rows = conn.execute("SELECT * FROM employees ORDER BY name COLLATE NOCASE, id").fetchall()
    return [_employee_dict(r, running.get(r["id"])) for r in rows]


# --- Timer ------------------------------------------------------------------

def start_timer(conn, employee_id: int, task: str, now: str | None = None) -> dict:
    task = _clean(task, "task", MAX_TASK_LENGTH)
    _employee_row(conn, employee_id)
    started = now or now_utc()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO time_entries (employee_id, task, started_at) VALUES (?, ?, ?)",
                (employee_id, task, started),
            )
    except sqlite3.IntegrityError:
        # The unique partial index fired: this employee already has a running timer.
        raise Conflict("A timer is already running for this employee")
    return _entry_dict(conn.execute("SELECT * FROM time_entries WHERE id = ?", (cur.lastrowid,)).fetchone(), now=started)


def stop_timer(conn, employee_id: int, now: str | None = None) -> dict:
    _employee_row(conn, employee_id)
    running = conn.execute(
        "SELECT * FROM time_entries WHERE employee_id = ? AND ended_at IS NULL", (employee_id,)
    ).fetchone()
    if running is None:
        raise Conflict("No timer is running for this employee")
    # max() guards the CHECK constraint if the clock ever moves backwards.
    ended = max(now or now_utc(), running["started_at"])
    with conn:
        conn.execute("UPDATE time_entries SET ended_at = ? WHERE id = ?", (ended, running["id"]))
    return _entry_dict(conn.execute("SELECT * FROM time_entries WHERE id = ?", (running["id"],)).fetchone(), now=ended)


def _entry_dict(row: sqlite3.Row, now: str, start: str | None = None, end: str | None = None) -> dict:
    return {
        "id": row["id"],
        "employee_id": row["employee_id"],
        "task": row["task"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "running": row["ended_at"] is None,
        "duration_seconds": _seconds_between(row["started_at"], row["ended_at"] or now),
        "counted_seconds": _clipped_seconds(row, start, end, now),
    }


# --- Reports ----------------------------------------------------------------

def get_entries(conn, employee_id: int, from_: str | None = None, to: str | None = None,
                now: str | None = None) -> dict:
    """Entries overlapping the period for one employee, plus the clipped total.

    `duration_seconds` is the entry's full length; `counted_seconds` is the part
    inside the period. `total_seconds` is the sum of `counted_seconds`.
    """
    now = now or now_utc()
    employee = _employee_row(conn, employee_id)
    start, end = _check_period(from_, to)
    entries = [_entry_dict(r, now, start, end) for r in _overlapping_entries(conn, start, end, employee_id)]
    return {
        "employee": {"id": employee["id"], "name": employee["name"]},
        "from": start,
        "to": end,
        "entries": entries,
        "total_seconds": round(sum(e["counted_seconds"] for e in entries), 6),
    }


def get_report(conn, from_: str | None = None, to: str | None = None, now: str | None = None) -> dict:
    """Total counted seconds per employee. Employees without entries show 0."""
    now = now or now_utc()
    start, end = _check_period(from_, to)
    totals: dict[int, float] = {}
    for entry in _overlapping_entries(conn, start, end):
        totals[entry["employee_id"]] = totals.get(entry["employee_id"], 0.0) + _clipped_seconds(entry, start, end, now)
    employees = conn.execute("SELECT id, name FROM employees ORDER BY name COLLATE NOCASE, id").fetchall()
    return {
        "from": start,
        "to": end,
        "employees": [
            {"id": e["id"], "name": e["name"], "total_seconds": round(totals.get(e["id"], 0.0), 6)}
            for e in employees
        ],
    }