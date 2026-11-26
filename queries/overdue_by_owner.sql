-- Open tasks past their due date, one row per owner. :today is passed in by Python.
SELECT
  t.owner_role,
  COUNT(*)                                       AS overdue_tasks,
  MIN(t.due_date)                                AS oldest_due,
  CAST(julianday(:today) - julianday(MIN(t.due_date)) AS INTEGER) AS days_late
FROM onboarding_tasks AS t
WHERE t.completed_date IS NULL
  AND t.due_date < :today
GROUP BY t.owner_role
ORDER BY overdue_tasks DESC, t.owner_role;
