"""Fill the database with fictional demo data.

Usage (from the project folder):
    python seed.py            # add demo data to an empty database
    python seed.py --reset    # delete everything first, then add demo data

The data is relative to the current time, so "Today" and "Last 7 days" in the
UI always show something. It goes through the same service functions the API
uses, so it follows every business rule. The random generator has a fixed
seed: running it twice produces the same pattern.
"""
import argparse
import random
from datetime import datetime, timedelta, timezone

from app import service
from app.db import TIME_FORMAT, get_connection, init_db

EMPLOYEES = ["Alice Johnson", "Bob Smith", "Carla Mendes", "Dmitri Volkov", "Emma Clarke"]

TASKS = {
    "Alice Johnson": ["Write release notes", "Review pull requests", "Plan sprint"],
    "Bob Smith": ["Answer support tickets", "Update help articles", "Call with client"],
    "Carla Mendes": ["Design landing page", "Prepare brand guide", "User interviews"],
    "Dmitri Volkov": ["Fix login bug", "Database backup check", "Deploy new version"],
}

# Which weekdays each person works (0 = Monday). Emma has no entries on purpose,
# so the report shows a zero row.
WORKDAYS = {
    "Alice Johnson": {0, 1, 2, 3, 4},
    "Bob Smith": {0, 1, 2, 3, 4},
    "Carla Mendes": {0, 2, 4},
    "Dmitri Volkov": {0, 1, 2, 3, 4},
}


class AlreadySeeded(Exception):
    """The database already contains employees."""


def _stamp(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)


def reset(conn) -> None:
    with conn:
        conn.execute("DELETE FROM time_entries")
        conn.execute("DELETE FROM employees")


def seed(conn, now: datetime | None = None, reset_first: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    if reset_first:
        reset(conn)
    if conn.execute("SELECT 1 FROM employees LIMIT 1").fetchone():
        raise AlreadySeeded("The database already has employees. Use --reset to start over.")

    rng = random.Random(42)
    ids = {name: service.add_employee(conn, name, now=_stamp(now))["id"] for name in EMPLOYEES}

    # Bob's timer is still running, started 40 minutes ago.
    running_start = now - timedelta(minutes=40)

    entries = []  # (employee, task, start, end or None)
    today = now.date()
    for days_back in range(6, -1, -1):
        day = today - timedelta(days=days_back)
        midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        for name, workdays in WORKDAYS.items():
            if day.weekday() not in workdays:
                continue
            blocks = [(9 * 60, 12 * 60 + 30), (13 * 60 + 30, 17 * 60 + 30)]
            for start_min, end_min in blocks:
                start = midnight + timedelta(minutes=start_min + rng.randint(0, 20))
                end = midnight + timedelta(minutes=end_min + rng.randint(-30, 30))
                limit = running_start if name == "Bob Smith" else now
                if end > limit:
                    continue  # never invent entries in the future
                entries.append((name, rng.choice(TASKS[name]), start, end))

    # One night shift that crosses midnight, to show that period totals are clipped.
    night_day = today - timedelta(days=2)
    night_start = datetime(night_day.year, night_day.month, night_day.day, 22, tzinfo=timezone.utc)
    entries.append(("Dmitri Volkov", "Overnight server migration", night_start, night_start + timedelta(hours=4)))

    entries.append(("Bob Smith", "Answer support tickets", running_start, None))

    # Per employee the entries must be applied in time order (one running timer at a time).
    for name, task, start, end in sorted(entries, key=lambda e: e[2]):
        service.start_timer(conn, ids[name], task, now=_stamp(start))
        if end is not None:
            service.stop_timer(conn, ids[name], now=_stamp(end))

    return {"employees": len(ids), "entries": len(entries)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill the database with fictional demo data.")
    parser.add_argument("--reset", action="store_true", help="delete all existing data first")
    args = parser.parse_args()
    conn = get_connection()
    init_db(conn)
    try:
        counts = seed(conn, reset_first=args.reset)
    except AlreadySeeded as err:
        raise SystemExit(str(err))
    print(f"Added {counts['employees']} employees and {counts['entries']} entries.")


if __name__ == "__main__":
    main()