# Build plan: Onboarding Agent (~6 hours)

**The problem:** a new hire's first week often goes to waiting. Someone copies their details between the recruiting system, the HR system and Slack by hand, and steps slip.

**What it does:** when an offer is accepted, it creates the onboarding checklist with owners and due dates, drafts a first-week plan the manager approves, posts a Slack welcome, and flags anything overdue.

**The rules:** a person approves anything sent to a person; dates and counts are computed in code; every run is logged; failures alert someone.

## Session 1 (~1.5h): data in, checklist out
- [ ] Read `data/sample_events/` (fake "offer accepted" webhooks) and `data/task_templates.yaml`
- [ ] Create the database from `schema.sql` (SQLite, one file)
- [ ] For each event: add the employee, then create their tasks from the templates (due date = start date + offset, computed in Python)
- [ ] Running the same event twice must not create duplicate tasks (idempotent)
- [ ] Tests: correct tasks per department, correct due dates, no duplicates

## Session 2 (~1.5h): the AI step, with approval
- [ ] One Claude call drafts a short first-week plan for the new hire from their role and team
- [ ] The draft is saved as `pending` in the `approvals` table; nothing is sent yet
- [ ] A simple command lets the manager approve or reject it (`python -m onboarding_agent approve <id>`)
- [ ] Only approved drafts can be sent; this is checked in code
- [ ] Tests: an unapproved draft can never be sent

## Session 3 (~1.5h): Slack and the overdue report
- [ ] Post the welcome and the approved plan to Slack (a free Slack workspace and an incoming webhook), or print to the console if no webhook is set
- [ ] Overdue report in SQL: open tasks past their due date, grouped by owner (this is drill 6 from the SQL practice)
- [ ] Every run writes a row to `runs_log`; a failed step posts an alert instead of stopping silently
- [ ] Tests: overdue math, failure alert

## Session 4 (~1.5h): measure it and ship it
- [ ] Metrics in SQL: days from offer accepted to all day-one tasks done, overdue tasks by owner
- [ ] README with a diagram, the rules above, how to run it, and what I'd build next
- [ ] Record what broke and how I fixed it (for Friday's post)
