import sqlite3

import pytest

from onboarding_agent.db import connect, init_db


def table_names(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r["name"] for r in rows}


def test_init_db_creates_all_tables():
    conn = connect(":memory:")
    init_db(conn)
    assert {"employees", "onboarding_tasks", "approvals", "runs_log"} <= table_names(conn)


def test_init_db_twice_is_safe():
    conn = connect(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise


def test_foreign_keys_are_enforced():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO onboarding_tasks (employee_id, task, owner_role, due_date) "
            "VALUES (999, 't', 'IT', '2026-01-01')"
        )
