from datetime import datetime, timezone

import pytest

import seed
from app import service
from app.db import TIME_FORMAT

NOW = datetime(2026, 10, 29, 15, 0, tzinfo=timezone.utc)  # a Thursday
NOW_STR = NOW.strftime(TIME_FORMAT)


def test_seed_creates_employees_entries_and_a_running_timer(conn):
    counts = seed.seed(conn, now=NOW)
    assert counts["employees"] == 5 and counts["entries"] > 20
    people = {e["name"]: e for e in service.list_employees(conn)}
    assert people["Bob Smith"]["running"] is not None
    assert people["Alice Johnson"]["running"] is None


def test_seed_report_has_a_zero_row_and_no_future_entries(conn):
    seed.seed(conn, now=NOW)
    report = service.get_report(conn, now=NOW_STR)
    totals = {e["name"]: e["total_seconds"] for e in report["employees"]}
    assert totals["Emma Clarke"] == 0
    assert totals["Alice Johnson"] > 0
    future = conn.execute("SELECT COUNT(*) FROM time_entries WHERE started_at > ?", (NOW_STR,)).fetchone()[0]
    assert future == 0


def test_seed_night_shift_is_clipped_by_a_single_day(conn):
    seed.seed(conn, now=NOW)
    dmitri = next(e["id"] for e in service.list_employees(conn) if e["name"] == "Dmitri Volkov")
    result = service.get_entries(conn, dmitri, "2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z", now=NOW_STR)
    night = [e for e in result["entries"] if e["task"] == "Overnight server migration"][0]
    assert night["duration_seconds"] == 4 * 3600 and night["counted_seconds"] == 2 * 3600


def test_seed_refuses_to_run_twice_but_reset_works(conn):
    seed.seed(conn, now=NOW)
    with pytest.raises(seed.AlreadySeeded):
        seed.seed(conn, now=NOW)
    assert seed.seed(conn, now=NOW, reset_first=True)["employees"] == 5