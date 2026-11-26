"""Metrics, all computed in SQL (queries/*.sql). Python only runs them and prints."""
import sqlite3

from . import overdue


def day_one_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return overdue._query(conn, "days_to_day_one_done.sql", "")  # this query takes no :today


def overdue_by_owner(conn: sqlite3.Connection, today: str) -> list[sqlite3.Row]:
    return overdue._query(conn, "overdue_by_owner.sql", today)


def overdue_tasks(conn: sqlite3.Connection, today: str) -> list[sqlite3.Row]:
    return overdue._query(conn, "overdue_tasks.sql", today)


def build_metrics(conn: sqlite3.Connection, today: str) -> str:
    lines = ["Days from offer accepted to all day-one tasks done:"]
    for r in day_one_rows(conn):
        done = f"{r['days_to_done']} days" if r["days_to_done"] is not None else "not yet"
        lines.append(f"  {r['new_hire']}: {done} ({r['day_one_done']}/{r['day_one_tasks']} day-one tasks done)")
    lines += ["", f"Overdue tasks by owner on {today}:"]
    owners = overdue_by_owner(conn, today)
    lines += [f"  {r['owner_role']}: {r['overdue_tasks']}" for r in owners] or ["  nothing is overdue"]
    return "\n".join(lines)
