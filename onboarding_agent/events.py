"""Read an "offer accepted" event file and turn it into a flat NewHire record."""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class EventError(Exception):
    """The event file is unusable (bad JSON, wrong type, or a missing field)."""


@dataclass(frozen=True)
class NewHire:
    candidate_id: str
    name: str
    email: str
    title: str
    department: str
    location: str
    manager_name: str
    manager_email: str
    offer_accepted_date: str  # ISO string, YYYY-MM-DD
    start_date: str           # ISO string, YYYY-MM-DD


def _get(data: dict, *path: str) -> str:
    """Walk into nested dicts, e.g. _get(data, "offer", "start_date").
    Raise EventError if any step is missing or the value is empty."""
    value = data
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise EventError(f"missing field: {'.'.join(path)}")
        value = value[key]
    if not isinstance(value, str) or not value.strip():
        raise EventError(f"empty field: {'.'.join(path)}")
    return value.strip()


def _check_date(text: str, field: str) -> str:
    """Make sure a date really is YYYY-MM-DD (so later date math can't blow up)."""
    try:
        date.fromisoformat(text)
    except ValueError:
        raise EventError(f"{field} is not a YYYY-MM-DD date: {text!r}")
    return text


def parse_event(path: str | Path) -> NewHire:
    """Read one event file. Raises EventError if it can't be trusted."""
    try:
        event = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise EventError(f"not valid JSON: {exc}")
    if event.get("event") != "offer.accepted":
        raise EventError(f"unexpected event type: {event.get('event')!r}")
    data = event.get("data", {})
    return NewHire(
        candidate_id=_get(data, "candidate", "id"),
        name=_get(data, "candidate", "name"),
        email=_get(data, "candidate", "email"),
        title=_get(data, "job", "title"),
        department=_get(data, "job", "department"),
        location=_get(data, "job", "location"),
        manager_name=_get(data, "hiring_manager", "name"),
        manager_email=_get(data, "hiring_manager", "email"),
        offer_accepted_date=_check_date(_get(data, "offer", "accepted_at"), "offer.accepted_at"),
        start_date=_check_date(_get(data, "offer", "start_date"), "offer.start_date"),
    )
