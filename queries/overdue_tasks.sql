-- The same open, past-due tasks one per line, so each owner can see what to do.
SELECT
  t.owner_role,
  e.name AS new_hire,
  t.task,
  t.due_date,
  CAST(julianday(:today) - julianday(t.due_date) AS INTEGER) AS days_late
FROM onboarding_tasks AS t
JOIN employees AS e ON e.id = t.employee_id
WHERE t.completed_date IS NULL
  AND t.due_date < :today
ORDER BY t.owner_role, t.due_date, e.name, t.task;
