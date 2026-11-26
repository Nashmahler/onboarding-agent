-- One SQLite file. Dates are ISO strings (YYYY-MM-DD).
CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY,
  candidate_id TEXT UNIQUE NOT NULL,   -- from the "offer accepted" event; prevents duplicates
  name TEXT NOT NULL,
  email TEXT NOT NULL,
  title TEXT NOT NULL,
  department TEXT NOT NULL,
  manager_name TEXT NOT NULL,
  manager_email TEXT NOT NULL,
  location TEXT NOT NULL,
  offer_accepted_date TEXT NOT NULL,
  start_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS onboarding_tasks (
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  task TEXT NOT NULL,
  owner_role TEXT NOT NULL,            -- IT, Manager, People Ops, Payroll, New hire
  due_date TEXT NOT NULL,
  completed_date TEXT,                 -- NULL until done
  UNIQUE (employee_id, task)
);

CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL REFERENCES employees(id),
  kind TEXT NOT NULL,                  -- e.g. first_week_plan
  draft TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'sent')),
  decided_by TEXT,
  decided_at TEXT
);

CREATE TABLE IF NOT EXISTS runs_log (
  id INTEGER PRIMARY KEY,
  ran_at TEXT NOT NULL,
  step TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'skipped')),
  detail TEXT
);

-- Database-level guard. Even a direct edit with the sqlite3 tool can't skip approval.
-- (CREATE TRIGGER IF NOT EXISTS, so init_db also adds these to an older database file.)
CREATE TRIGGER IF NOT EXISTS approvals_only_approved_can_be_sent
BEFORE UPDATE OF status ON approvals
WHEN NEW.status = 'sent' AND OLD.status IS NOT 'approved'
BEGIN
  SELECT RAISE(ABORT, 'only an approved draft can be sent');
END;

-- A row also can't be created already 'sent', which would skip the UPDATE check.
CREATE TRIGGER IF NOT EXISTS approvals_cannot_start_sent
BEFORE INSERT ON approvals
WHEN NEW.status = 'sent'
BEGIN
  SELECT RAISE(ABORT, 'a new draft cannot start as sent');
END;
