import json
from pathlib import Path

import pytest

from onboarding_agent.events import EventError, parse_event

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "sample_events"


def write_event(tmp_path, **changes):
    """Copy a good sample event, apply edits, save it, return the path."""
    event = json.loads((SAMPLES / "cand_1001.json").read_text())
    for dotted, value in changes.items():
        *parents, last = dotted.split("__")
        target = event
        for key in parents:
            target = target[key]
        if value is None:
            del target[last]
        else:
            target[last] = value
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event))
    return path


def test_good_event_is_flattened():
    hire = parse_event(SAMPLES / "cand_1001.json")
    assert hire.candidate_id == "cand_1001"
    assert hire.name == "Maya Chen"
    assert hire.department == "Engineering"
    assert hire.manager_email == "eli.moss@juniperlabs.example"
    assert hire.start_date == "2026-12-07"


def test_missing_start_date_is_rejected():
    with pytest.raises(EventError, match="offer.start_date"):
        parse_event(SAMPLES / "cand_1005_missing_start_date.json")


def test_bad_date_format_is_rejected(tmp_path):
    path = write_event(tmp_path, data__offer__start_date="12/07/2026")
    with pytest.raises(EventError, match="YYYY-MM-DD"):
        parse_event(path)


def test_wrong_event_type_is_rejected(tmp_path):
    path = write_event(tmp_path, event="offer.declined")
    with pytest.raises(EventError, match="unexpected event type"):
        parse_event(path)


def test_invalid_json_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    with pytest.raises(EventError, match="not valid JSON"):
        parse_event(path)
