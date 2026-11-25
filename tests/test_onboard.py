import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from onboarding_agent import onboard
from onboarding_agent.db import connect, init_db
from onboarding_agent.onboard import due_date, process_event

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_db(c)
    return c


def count(conn, table):
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def due_dates(conn, candidate_id):
    rows = conn.execute(
        """SELECT t.task, t.due_date FROM onboarding_tasks t
           JOIN employees e ON e.id = t.employee_id
           WHERE e.candidate_id = ?""",
        (candidate_id,),
    )
    return {r["task"]: r["due_date"] for r in rows}


def event_with_department(tmp_path, department):
    event = json.loads((SAMPLES / "cand_1001.json").read_text())
    event["data"]["job"]["department"] = department
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return path


# --- due dates ---------------------------------------------------------------

def test_weekday_is_unchanged():
    assert date(2026, 12, 7).weekday() == 0  # sanity check: Dec 7 2026 is a Monday
    assert due_date("2026-12-07", 3) == "2026-12-10"  # Thursday


def test_saturday_moves_to_next_monday():
    assert due_date("2026-12-07", 5) == "2026-12-14"  # Dec 12 is a Saturday


def test_sunday_moves_to_next_monday():
    assert due_date("2026-12-07", 6) == "2026-12-14"  # Dec 13 is a Sunday


def test_weekend_before_start_moves_back_to_friday():
    assert due_date("2026-12-07", -2) == "2026-12-04"  # Saturday Dec 5 -> Friday Dec 4
    assert due_date("2026-12-07", -1) == "2026-12-04"  # Sunday Dec 6 -> Friday Dec 4


def test_pre_start_tasks_are_never_due_after_day_one():
    for start in ["2026-12-01", "2026-12-07", "2026-12-14", "2026-11-30"]:
        for offset in range(-14, 0):
            assert due_date(start, offset) < start


def test_due_dates_never_land_on_a_weekend():
    for offset in range(-14, 31):
        assert date.fromisoformat(due_date("2026-12-07", offset)).weekday() < 5


def test_zero_offset_on_a_weekend_start_moves_forward():
    assert due_date("2026-12-05", 0) == "2026-12-07"  # a Saturday start -> Monday


def test_negative_offset_on_a_weekday():
    assert due_date("2026-12-07", -3) == "2026-12-04"  # Friday


def test_due_date_crosses_the_year():
    assert due_date("2026-12-07", 30) == "2027-01-06"


# --- tasks per department ----------------------------------------------------

@pytest.mark.parametrize("file, expected", [
    ("cand_1001.json", 10),  # Engineering: 8 + 2
    ("cand_1002.json", 10),  # Sales: 8 + 2
    ("cand_1003.json", 9),   # People: 8 + 1
    ("cand_1004.json", 10),  # Engineering: 8 + 2
])
def test_task_count_per_department(conn, file, expected):
    result = process_event(conn, SAMPLES / file)
    assert result.status == "ok"
    assert result.tasks_created == expected
    assert count(conn, "onboarding_tasks") == expected


def test_each_department_gets_its_own_tasks(conn):
    process_event(conn, SAMPLES / "cand_1001.json")
    process_event(conn, SAMPLES / "cand_1002.json")
    assert "Grant GitHub and cloud access" in due_dates(conn, "cand_1001")
    assert "Grant GitHub and cloud access" not in due_dates(conn, "cand_1002")
    assert "Create CRM seat" in due_dates(conn, "cand_1002")


def test_maya_due_dates(conn):
    process_event(conn, SAMPLES / "cand_1001.json")  # starts Monday 2026-12-07
    assert due_dates(conn, "cand_1001") == {
        "Send offer paperwork and I-9 link": "2026-11-27",
        "Add to payroll": "2026-11-30",
        "Order and ship laptop": "2026-11-30",
        "Create email and Slack accounts": "2026-12-04",  # Sat -> Fri
        "Send first-week plan": "2026-12-04",             # Sat -> Fri
        "Security training": "2026-12-14",                # Sat -> Mon
        "Benefits enrollment": "2026-12-17",
        "30-day check-in": "2027-01-06",
        "Grant GitHub and cloud access": "2026-12-04",    # Sun -> Fri
        "Assign onboarding buddy": "2026-12-04",
    }


def test_unknown_department_gets_shared_tasks_and_a_note_in_the_log(conn, tmp_path):
    result = process_event(conn, event_with_department(tmp_path, "Finance"))
    assert result.status == "ok"
    assert result.tasks_created == 8
    detail = conn.execute("SELECT detail FROM runs_log").fetchone()["detail"]
    assert "no department tasks for 'Finance'" in detail


def test_department_with_odd_case_and_spaces_gets_department_tasks(conn, tmp_path):
    result = process_event(conn, event_with_department(tmp_path, "  engineering "))
    assert result.tasks_created == 10


# --- no duplicates -----------------------------------------------------------

def test_same_event_twice_creates_no_duplicates(conn):
    first = process_event(conn, SAMPLES / "cand_1001.json")
    second = process_event(conn, SAMPLES / "cand_1001.json")
    assert (first.status, first.tasks_created) == ("ok", 10)
    assert (second.status, second.tasks_created) == ("skipped", 0)
    assert second.employee_id == first.employee_id
    assert count(conn, "employees") == 1
    assert count(conn, "onboarding_tasks") == 10


def test_replay_does_not_erase_a_completed_task(conn):
    process_event(conn, SAMPLES / "cand_1001.json")
    conn.execute(
        "UPDATE onboarding_tasks SET completed_date = '2026-11-20' WHERE task = 'Add to payroll'"
    )
    process_event(conn, SAMPLES / "cand_1001.json")
    row = conn.execute(
        "SELECT completed_date FROM onboarding_tasks WHERE task = 'Add to payroll'"
    ).fetchone()
    assert row["completed_date"] == "2026-11-20"


def test_every_sample_twice_still_has_one_set_of_tasks(conn):
    good = sorted(SAMPLES.glob("cand_100[1-4]*.json"))
    for _ in range(2):
        for path in good:
            process_event(conn, path)
    assert count(conn, "employees") == 4
    assert count(conn, "onboarding_tasks") == 10 + 10 + 9 + 10


# --- failures and the log ----------------------------------------------------

def test_missing_start_date_writes_nothing_and_is_logged_as_failed(conn):
    result = process_event(conn, SAMPLES / "cand_1005_missing_start_date.json")
    assert result.status == "failed"
    assert "offer.start_date" in result.detail
    assert count(conn, "employees") == 0
    assert count(conn, "onboarding_tasks") == 0
    log = conn.execute("SELECT step, status, detail FROM runs_log").fetchone()
    assert log["status"] == "failed"
    assert "cand_1005" in log["step"]
    assert "offer.start_date" in log["detail"]


def test_failure_halfway_rolls_back_the_employee(conn, monkeypatch):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk is full")

    monkeypatch.setattr(onboard, "create_tasks", boom)
    result = process_event(conn, SAMPLES / "cand_1001.json")
    assert result.status == "failed"
    assert count(conn, "employees") == 0  # employee insert was undone
    assert conn.execute("SELECT status FROM runs_log").fetchone()["status"] == "failed"


def test_every_event_writes_one_log_row(conn):
    for path in sorted(SAMPLES.glob("*.json")):
        process_event(conn, path)
    statuses = [r["status"] for r in conn.execute("SELECT status FROM runs_log ORDER BY id")]
    assert statuses == ["ok", "ok", "ok", "ok", "failed"]
