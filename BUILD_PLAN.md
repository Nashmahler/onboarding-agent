# Build plan: Onboarding Agent (~6 hours)

**The problem:** a new hire's first week often goes to waiting. Someone copies their details between the recruiting system, the HR system and Slack by hand, and steps slip.

**What it does:** when an offer is accepted, it creates the onboarding checklist with owners and due dates, drafts a first-week plan the manager approves, posts a Slack welcome, and flags anything overdue.

**The rules:** a person approves anything sent to a person; dates and counts are computed in code; every run is logged; failures alert someone.

## Session 1 (~1.5h): data in, checklist out
- [x] Read `data/sample_events/` (fake "offer accepted" webhooks) and `data/task_templates.yaml`
- [x] Create the database from `schema.sql` (SQLite, one file)
- [x] For each event: add the employee, then create their tasks from the templates (due date = start date + offset, computed in Python)
- [x] Running the same event twice must not create duplicate tasks (idempotent)
- [x] Tests: correct tasks per department, correct due dates, no duplicates

## Session 2 (~1.5h): the AI step, with approval
- [x] One Claude call drafts a short first-week plan for the new hire from their role and team
- [x] The draft is saved as `pending` in the `approvals` table; nothing is sent yet
- [x] A simple command lets the manager approve or reject it (`python -m onboarding_agent approve <id>`)
- [x] Only approved drafts can be sent; this is checked in code
- [x] Tests: an unapproved draft can never be sent

## Session 3 (~1.5h): Slack and the overdue report
- [x] Post the welcome and the approved plan to Slack (a free Slack workspace and an incoming webhook), or print to the console if no webhook is set
- [x] Overdue report in SQL: open tasks past their due date, grouped by owner (this is drill 6 from the SQL practice)
- [x] Every run writes a row to `runs_log`; a failed step posts an alert instead of stopping silently
- [x] Tests: overdue math, failure alert

## Session 4 (~1.5h): measure it and ship it
- [x] Repeat alerts: an event file alerts only the first time it fails; later failures are logged as "already alerted"
- [x] Metrics in SQL: days from offer accepted to all day-one tasks done, overdue tasks by owner
- [x] `complete` command and a "Complete task" button (sets completed_date in code, logs it, posts to Slack)
- [x] Dashboard: one static page (`docs/index.html`) built from the demo database, rebuilt and committed by every button
- [x] README with a diagram, the rules and how they're enforced, the buttons, known gaps
- [x] Record what broke and how I fixed it (README, "What broke and how I fixed it")

## Session 5 (follow-up): company holidays
- [x] `data/holidays.yaml`; a due date on a holiday moves to the previous working day (weekend rules otherwise unchanged)
- [x] "Run onboarding" reschedules open tasks, logs old and new dates, posts one Slack summary only when something changed; completed tasks never change
- [x] The welcome checklist is rebuilt from the database when the plan is sent (the pending message says so)

## Known gaps
- **Changed start dates are ignored.** If an "offer accepted" event is replayed for the same candidate with a different start date, the existing employee row and task due dates are kept as they were (the inserts use `ON CONFLICT DO NOTHING`). A changed start date needs its own handling, such as updating the employee and recomputing the due dates of tasks that aren't done yet. Not built yet.
