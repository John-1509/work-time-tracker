from fastapi.testclient import TestClient

from app.main import create_app


def add(client, name="Alice Example"):
    r = client.post("/employees", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


def test_add_and_list_employees(client):
    emp_id = add(client)
    r = client.get("/employees")
    assert r.status_code == 200
    assert r.json()[0]["id"] == emp_id and r.json()[0]["running"] is None


def test_duplicate_employee_is_409(client):
    add(client, "Bob")
    assert client.post("/employees", json={"name": "BOB"}).status_code == 409


def test_empty_name_or_task_is_422(client):
    assert client.post("/employees", json={"name": "   "}).status_code == 422
    assert client.post("/employees", json={}).status_code == 422
    emp_id = add(client)
    assert client.post(f"/employees/{emp_id}/timer/start", json={"task": " "}).status_code == 422


def test_timer_lifecycle_and_error_statuses(client):
    emp_id = add(client)
    start = f"/employees/{emp_id}/timer/start"
    stop = f"/employees/{emp_id}/timer/stop"

    assert client.post(stop).status_code == 409                       # nothing running
    assert client.post(start, json={"task": "design"}).status_code == 201
    assert client.get("/employees").json()[0]["running"]["task"] == "design"
    assert client.post(start, json={"task": "again"}).status_code == 409  # already running
    assert client.post(stop).status_code == 200
    assert client.post(start, json={"task": "again"}).status_code == 201  # restart works


def test_unknown_employee_is_404(client):
    assert client.post("/employees/99/timer/start", json={"task": "x"}).status_code == 404
    assert client.post("/employees/99/timer/stop").status_code == 404
    assert client.get("/employees/99/entries").status_code == 404


def test_entries_and_report_for_a_period(client):
    emp_id = add(client)
    client.post(f"/employees/{emp_id}/timer/start", json={"task": "x"})
    client.post(f"/employees/{emp_id}/timer/stop")
    r = client.get(f"/employees/{emp_id}/entries", params={"from": "2000-01-01T00:00:00Z", "to": "2100-01-01T00:00:00Z"})
    assert r.status_code == 200 and len(r.json()["entries"]) == 1
    report = client.get("/report", params={"from": "2000-01-01T00:00:00Z"}).json()
    assert report["employees"][0]["name"] == "Alice Example"


def test_period_far_in_the_past_gives_zero_totals(client):
    add(client)
    report = client.get("/report", params={"from": "2000-01-01T00:00:00Z", "to": "2000-01-02T00:00:00Z"})
    assert report.status_code == 200
    assert report.json()["employees"][0]["total_seconds"] == 0


def test_empty_report_is_not_an_error(client):
    r = client.get("/report")
    assert r.status_code == 200 and r.json()["employees"] == []


def test_bad_period_is_422(client):
    emp_id = add(client)
    swapped = {"from": "2026-10-29T00:00:00Z", "to": "2026-10-28T00:00:00Z"}
    assert client.get("/report", params=swapped).status_code == 422
    assert client.get(f"/employees/{emp_id}/entries", params=swapped).status_code == 422
    assert client.get("/report", params={"from": "not-a-date"}).status_code == 422


def test_data_survives_restart(db_path):
    first = TestClient(create_app(db_path))
    emp_id = add(first)
    first.post(f"/employees/{emp_id}/timer/start", json={"task": "long task"})

    second = TestClient(create_app(db_path))  # a fresh app on the same file = server restart
    employees = second.get("/employees").json()
    assert employees[0]["name"] == "Alice Example"
    assert employees[0]["running"]["task"] == "long task"
    # ...and the still-running timer can be stopped after the restart.
    assert second.post(f"/employees/{emp_id}/timer/stop").status_code == 200


def test_home_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Work time tracker" in r.text


def test_huge_employee_id_in_url_is_404(client):
    assert client.get("/employees/99999999999999999999/entries").status_code == 404
    assert client.post("/employees/99999999999999999999/timer/stop").status_code == 404


def test_extreme_year_in_url_is_422(client):
    assert client.get("/report", params={"to": "9999-12-31T23:59:59-05:00"}).status_code == 422