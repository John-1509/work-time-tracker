import pytest

from app import service
from app.service import Conflict, InvalidInput, NotFound

T = "2026-10-28T{}Z"


def t(hms, micro="000000"):
    """Storage-format timestamp on a fixed day, e.g. t('09:00:00')."""
    return f"2026-10-28T{hms}.{micro}Z"


# --- employees ---------------------------------------------------------------

def test_add_employee_trims_name_and_lists_it(conn):
    emp = service.add_employee(conn, "  Alice Example  ")
    assert emp["name"] == "Alice Example"
    assert [e["name"] for e in service.list_employees(conn)] == ["Alice Example"]


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_empty_employee_name_rejected(conn, bad):
    with pytest.raises(InvalidInput):
        service.add_employee(conn, bad)


def test_duplicate_name_rejected_in_any_case(conn):
    service.add_employee(conn, "Bob Sample")
    with pytest.raises(Conflict):
        service.add_employee(conn, "bob sample")


# --- timer -------------------------------------------------------------------

def test_start_and_stop_timer(conn):
    emp = service.add_employee(conn, "Alice")
    started = service.start_timer(conn, emp["id"], "  write report ", now=t("09:00:00"))
    assert started["task"] == "write report" and started["running"]
    assert service.list_employees(conn)[0]["running"]["task"] == "write report"

    stopped = service.stop_timer(conn, emp["id"], now=t("10:30:00"))
    assert not stopped["running"]
    assert stopped["duration_seconds"] == 5400
    assert service.list_employees(conn)[0]["running"] is None


def test_second_start_while_running_is_rejected(conn):
    emp = service.add_employee(conn, "Alice")
    service.start_timer(conn, emp["id"], "a", now=t("09:00:00"))
    with pytest.raises(Conflict):
        service.start_timer(conn, emp["id"], "b", now=t("09:05:00"))


def test_stop_without_running_timer_is_rejected(conn):
    emp = service.add_employee(conn, "Alice")
    with pytest.raises(Conflict):
        service.stop_timer(conn, emp["id"])


def test_restart_timer_after_stop(conn):
    emp = service.add_employee(conn, "Alice")
    service.start_timer(conn, emp["id"], "first", now=t("09:00:00"))
    service.stop_timer(conn, emp["id"], now=t("09:30:00"))
    service.start_timer(conn, emp["id"], "second", now=t("09:30:00"))
    service.stop_timer(conn, emp["id"], now=t("10:00:00"))
    result = service.get_entries(conn, emp["id"], now=t("12:00:00"))
    assert [e["task"] for e in result["entries"]] == ["first", "second"]
    assert result["total_seconds"] == 3600


def test_two_employees_can_run_timers_at_once(conn):
    a = service.add_employee(conn, "Alice")
    b = service.add_employee(conn, "Bob")
    service.start_timer(conn, a["id"], "x", now=t("09:00:00"))
    service.start_timer(conn, b["id"], "y", now=t("09:00:00"))


def test_empty_task_rejected(conn):
    emp = service.add_employee(conn, "Alice")
    with pytest.raises(InvalidInput):
        service.start_timer(conn, emp["id"], "   ")


def test_unknown_employee(conn):
    with pytest.raises(NotFound):
        service.start_timer(conn, 999, "x")
    with pytest.raises(NotFound):
        service.stop_timer(conn, 999)
    with pytest.raises(NotFound):
        service.get_entries(conn, 999)


def test_stop_never_ends_before_start_if_clock_goes_backwards(conn):
    emp = service.add_employee(conn, "Alice")
    service.start_timer(conn, emp["id"], "x", now=t("09:00:00"))
    stopped = service.stop_timer(conn, emp["id"], now=t("08:00:00"))
    assert stopped["duration_seconds"] == 0


# --- period totals and clipping ----------------------------------------------

def _employee_with_entry(conn, start, end, task="work"):
    emp = service.add_employee(conn, "Alice")
    service.start_timer(conn, emp["id"], task, now=start)
    if end:
        service.stop_timer(conn, emp["id"], now=end)
    return emp


def test_entry_inside_period_counts_fully(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("10:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z")
    assert r["total_seconds"] == 3600


def test_entry_crossing_period_start_is_clipped(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("11:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T10:00:00Z", "2026-10-28T23:00:00Z")
    entry = r["entries"][0]
    assert entry["duration_seconds"] == 7200 and entry["counted_seconds"] == 3600
    assert r["total_seconds"] == 3600


def test_entry_crossing_period_end_is_clipped(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("11:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T00:00:00Z", "2026-10-28T09:30:00Z")
    assert r["total_seconds"] == 1800


def test_entry_spanning_whole_period_counts_only_the_period(conn):
    emp = _employee_with_entry(conn, t("08:00:00"), t("18:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T12:00:00Z", "2026-10-28T13:00:00Z")
    assert r["total_seconds"] == 3600


def test_entry_outside_period_is_not_listed(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("10:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T11:00:00Z", "2026-10-28T12:00:00Z")
    assert r["entries"] == [] and r["total_seconds"] == 0


def test_period_start_inclusive_end_exclusive(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("10:00:00"))
    # Period starts exactly when the entry ends: nothing overlaps.
    assert service.get_entries(conn, emp["id"], "2026-10-28T10:00:00Z", "2026-10-28T11:00:00Z")["entries"] == []
    # Period ends exactly when the entry starts: nothing overlaps.
    assert service.get_entries(conn, emp["id"], "2026-10-28T08:00:00Z", "2026-10-28T09:00:00Z")["entries"] == []


def test_running_timer_counts_up_to_now(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), None)
    r = service.get_entries(conn, emp["id"], now=t("09:45:00"))
    assert r["entries"][0]["running"] and r["total_seconds"] == 2700


def test_running_timer_clipped_by_period_end(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), None)
    r = service.get_entries(conn, emp["id"], "2026-10-28T00:00:00Z", "2026-10-28T09:10:00Z", now=t("12:00:00"))
    assert r["total_seconds"] == 600


def test_times_without_microseconds_or_with_offset_are_normalised(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("10:00:00"))
    # 14:00+05:00 is 09:00 UTC; written without microseconds on purpose.
    r = service.get_entries(conn, emp["id"], "2026-10-28T14:00:00+05:00", "2026-10-28T10:00:00Z")
    assert r["total_seconds"] == 3600


def test_microsecond_precision_is_kept(conn):
    emp = _employee_with_entry(conn, t("09:00:00", "000000"), t("09:00:01", "500000"))
    assert service.get_entries(conn, emp["id"], now=t("12:00:00"))["total_seconds"] == 1.5


# --- validation of the period ------------------------------------------------

def test_from_after_to_rejected(conn):
    emp = service.add_employee(conn, "Alice")
    with pytest.raises(InvalidInput):
        service.get_entries(conn, emp["id"], "2026-10-29T00:00:00Z", "2026-10-28T00:00:00Z")
    with pytest.raises(InvalidInput):
        service.get_report(conn, "2026-10-29T00:00:00Z", "2026-10-28T00:00:00Z")


def test_invalid_datetime_rejected(conn):
    with pytest.raises(InvalidInput):
        service.get_report(conn, "yesterday", None)


def test_equal_from_and_to_gives_zero_not_an_error(conn):
    emp = _employee_with_entry(conn, t("09:00:00"), t("10:00:00"))
    r = service.get_entries(conn, emp["id"], "2026-10-28T09:30:00Z", "2026-10-28T09:30:00Z")
    assert r["total_seconds"] == 0


# --- report ------------------------------------------------------------------

def test_report_with_no_employees_is_empty(conn):
    assert service.get_report(conn)["employees"] == []


def test_report_lists_employees_without_entries_with_zero(conn):
    service.add_employee(conn, "Alice")
    service.add_employee(conn, "Bob")
    assert [(e["name"], e["total_seconds"]) for e in service.get_report(conn)["employees"]] == [("Alice", 0), ("Bob", 0)]


def test_report_totals_per_employee_with_clipping(conn):
    a = service.add_employee(conn, "Alice")
    b = service.add_employee(conn, "Bob")
    service.add_employee(conn, "Carol")
    service.start_timer(conn, a["id"], "x", now=t("09:00:00"))
    service.stop_timer(conn, a["id"], now=t("11:00:00"))
    service.start_timer(conn, b["id"], "y", now=t("10:30:00"))  # still running
    report = service.get_report(conn, "2026-10-28T10:00:00Z", "2026-10-28T12:00:00Z", now=t("11:30:00"))
    totals = {e["name"]: e["total_seconds"] for e in report["employees"]}
    assert totals == {"Alice": 3600, "Bob": 3600, "Carol": 0}


# --- regression tests for bugs found in the review pass (see LOG.md) ---------

def test_huge_employee_id_is_not_found_not_a_crash(conn):
    for call in (lambda: service.get_entries(conn, 10**20),
                 lambda: service.start_timer(conn, 10**20, "x"),
                 lambda: service.stop_timer(conn, 10**20)):
        with pytest.raises(NotFound):
            call()


@pytest.mark.parametrize("value", [
    "9999-12-31T23:59:59-05:00",   # overflows when converted to UTC
    "0001-01-01T00:00:00+05:00",   # overflows the other way
    "0999-01-01T00:00:00Z",        # year below 1000 loses its zero padding when stored
    "1969-12-31T23:59:59Z",
])
def test_extreme_years_are_rejected(conn, value):
    with pytest.raises(InvalidInput):
        service.get_report(conn, value, None)


def test_name_made_only_of_invisible_characters_is_rejected(conn):
    with pytest.raises(InvalidInput):
        service.add_employee(conn, "\u200b\u200b")


def test_too_long_name_and_task_are_rejected(conn):
    with pytest.raises(InvalidInput):
        service.add_employee(conn, "x" * 101)
    emp = service.add_employee(conn, "Alice")
    with pytest.raises(InvalidInput):
        service.start_timer(conn, emp["id"], "x" * 501)