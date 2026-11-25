import logging

import pytest

from onboarding_agent.templates import TemplateError, load_templates, tasks_for


def names(tasks):
    return [t.task for t in tasks]


def test_everyone_gets_the_eight_shared_tasks():
    assert len(load_templates()["all"]) == 8


@pytest.mark.parametrize("department, extra", [("Engineering", 2), ("Sales", 2), ("People", 1)])
def test_department_tasks_are_added_on_top(department, extra):
    tasks = tasks_for(department)
    assert len(tasks) == 8 + extra
    assert names(tasks)[:8] == names(load_templates()["all"])  # shared tasks come first


def test_engineering_gets_its_own_tasks():
    assert "Grant GitHub and cloud access" in names(tasks_for("Engineering"))
    assert "Create CRM seat" not in names(tasks_for("Engineering"))


def test_unknown_department_still_gets_the_eight_tasks_and_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        tasks = tasks_for("Finance")
    assert names(tasks) == names(load_templates()["all"])
    assert len(tasks) == 8
    assert "Finance" in caplog.text


def test_known_department_logs_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        tasks_for("Sales")
    assert caplog.text == ""


def test_asking_for_the_all_section_does_not_double_the_tasks():
    assert len(tasks_for("all")) == 8


def test_row_missing_a_field_is_a_template_error(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("all:\n  - {task: X, owner_role: IT}\n")  # no offset_days
    with pytest.raises(TemplateError, match="offset_days"):
        load_templates(bad)


def test_non_numeric_offset_is_a_template_error(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("all:\n  - {task: X, owner_role: IT, offset_days: soon}\n")
    with pytest.raises(TemplateError, match="whole number"):
        load_templates(bad)


def test_file_without_all_section_is_a_template_error(tmp_path):
    bad = tmp_path / "t.yaml"
    bad.write_text("Sales:\n  - {task: X, owner_role: IT, offset_days: 1}\n")
    with pytest.raises(TemplateError, match="'all' section"):
        load_templates(bad)
