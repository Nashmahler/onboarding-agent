"""Open the SQLite database and create its tables."""
import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


def connect(path: str = "onboarding.db") -> sqlite3.Connection:
    """Open the database file (or ':memory:' for tests)."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)  # e.g. data/demo/ on a fresh checkout
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row  # rows read like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")  # SQLite ignores foreign keys unless asked
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create the tables from schema.sql. Safe to run more than once."""
    conn.executescript(SCHEMA_PATH.read_text())
