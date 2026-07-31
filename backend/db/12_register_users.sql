-- Register users from user_role_management with password 'changeme'
-- Uses DISTINCT ON to handle duplicate emails in user_role_management
INSERT INTO users (org_id, email, hashed_password, full_name, role)
SELECT DISTINCT ON (LOWER(urm.email_address))
  1, urm.email_address,
  '$2b$12$r8IIn0LTYtPnHI6u9GwQZeP/bGhylg5GUoPRcdOPR6pqnP3XgQ7Z.',
  urm.name, 'member'
FROM user_role_management urm
WHERE urm.email_address LIKE '%@%'
  AND NOT EXISTS (SELECT 1 FROM users u WHERE LOWER(u.email) = LOWER(urm.email_address))
LIMIT 50;

-- Link new users to their employee records via email match
UPDATE users u SET employee_id = ed.emp_id
FROM employee_details ed
WHERE u.employee_id IS NULL
  AND LOWER(u.email) = LOWER(ed.email_address)
  AND ed.org_id = 1;
