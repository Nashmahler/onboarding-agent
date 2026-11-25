"""Load the task templates and pick the ones that apply to a department."""
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parent.parent / "data" / "task_templates.yaml"


class TemplateError(Exception):
    """The templates file is malformed. This is our bug, not a bad event."""


@dataclass(frozen=True)
class TaskTemplate:
    task: str
    owner_role: str
    offset_days: int  # days relative to start date; negative = before day one


def _to_template(row: dict, section: str) -> TaskTemplate:
    """Check one YAML row has what we need and turn it into a TaskTemplate."""
    try:
        offset = row["offset_days"]
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise TemplateError(f"{section}: offset_days must be a whole number: {row}")
        return TaskTemplate(task=row["task"], owner_role=row["owner_role"], offset_days=offset)
    except KeyError as exc:
        raise TemplateError(f"{section}: row is missing {exc}: {row}")


def load_templates(path: Path = TEMPLATES_PATH) -> dict[str, list[TaskTemplate]]:
    """Read the YAML into {section name: [TaskTemplate, ...]}."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict) or "all" not in raw:
        raise TemplateError("templates file must have an 'all' section")
    return {s: [_to_template(row, s) for row in rows] for s, rows in raw.items()}


def tasks_for(department: str, path: Path = TEMPLATES_PATH) -> list[TaskTemplate]:
    """Everyone's tasks, plus the department's. An unknown department still
    gets the everyone tasks, with a warning, so onboarding is never blocked."""
    templates = load_templates(path)
    if department not in templates:
        log.warning("no task templates for department %r; using the 'all' tasks only", department)
    return templates["all"] + (templates.get(department, []) if department != "all" else [])
