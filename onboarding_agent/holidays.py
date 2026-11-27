"""Load Juniper Labs' company holidays from data/holidays.yaml."""
from datetime import date
from pathlib import Path

import yaml

HOLIDAYS_PATH = Path(__file__).resolve().parent.parent / "data" / "holidays.yaml"


class HolidayError(Exception):
    """The holidays file is missing or malformed. Failing loudly beats silently ignoring holidays."""


def load_holidays(path: Path = HOLIDAYS_PATH) -> frozenset[str]:
    """Return the holiday dates as ISO strings (YYYY-MM-DD)."""
    try:
        raw = yaml.safe_load(Path(path).read_text())
    except (OSError, ValueError, yaml.YAMLError) as exc:  # YAML itself rejects e.g. month 13
        raise HolidayError(f"cannot read holidays file {path}: {type(exc).__name__}") from None
    if not isinstance(raw, list):
        raise HolidayError("holidays file must be a list of {date: YYYY-MM-DD, name: ...} rows")
    days = set()
    for row in raw:
        value = row.get("date") if isinstance(row, dict) else None
        try:  # YAML turns an unquoted 2026-12-24 into a date already; accept a quoted string too
            days.add((value if isinstance(value, date) else date.fromisoformat(str(value))).isoformat())
        except ValueError:
            raise HolidayError(f"holidays file: not a valid date: {row!r}") from None
    return frozenset(days)
