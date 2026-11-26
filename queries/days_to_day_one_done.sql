-- Per hire: how many days from "offer accepted" until ALL day-one tasks were done.
-- "Day-one task" = a task due on or before the hire's start date (everything that must be
-- ready before they walk in). No :today parameter: this metric uses only dates in the database.
SELECT
  e.id                                  AS employee_id,
  e.name                                AS new_hire,
  e.offer_accepted_date,
  e.start_date,
  COUNT(t.id)                           AS day_one_tasks,
  COUNT(t.completed_date)               AS day_one_done,
  CASE
    WHEN COUNT(t.id) > 0 AND COUNT(t.completed_date) = COUNT(t.id)
    THEN CAST(julianday(MAX(t.completed_date)) - julianday(e.offer_accepted_date) AS INTEGER)
  END                                   AS days_to_done   -- NULL until every day-one task is done
FROM employees AS e
LEFT JOIN onboarding_tasks AS t
       ON t.employee_id = e.id
      AND t.due_date <= e.start_date
GROUP BY e.id
ORDER BY e.start_date, e.name;
