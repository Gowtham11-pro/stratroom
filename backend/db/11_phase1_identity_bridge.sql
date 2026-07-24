-- Phase 1: Identity Bridge
-- Links application users to enterprise employee data via email.
-- Idempotent: safe to run multiple times.

-- 1. Add employee_id FK column to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id BIGINT REFERENCES employee_details(emp_id) ON DELETE SET NULL;

-- 2. Ensure email-based lookups are efficient
CREATE UNIQUE INDEX IF NOT EXISTS idx_employee_details_email ON employee_details(email_address);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_role_mgmt_email ON user_role_management(email_address);

-- 3. Auto-link existing users to their employee_details record via email match
--    Uses LOWER() for case-insensitive matching (enterprise data has mixed case emails).
UPDATE users u
SET employee_id = ed.emp_id
FROM employee_details ed
WHERE u.employee_id IS NULL
  AND LOWER(u.email) = LOWER(ed.email_address)
  AND ed.org_id = u.org_id
  AND (ed.status IS NULL OR ed.status NOT IN ('InActive', 'Inactive'));

-- 4. Create a view that provides the full identity context for any user
--    Joins users <-> employee_details <-> user_role_management via email.
CREATE OR REPLACE VIEW v_user_identity AS
SELECT
    u.id AS user_id,
    u.org_id,
    u.email,
    u.full_name AS app_full_name,
    u.role AS app_role,
    u.employee_id,
    ed.emp_id AS emp_id,
    COALESCE(TRIM(CONCAT(ed.first_name, ' ', ed.last_name)), u.full_name, u.email) AS employee_name,
    ed.title AS employee_title,
    ed.department AS employee_department,
    ed.location AS employee_location,
    ed.email_address AS employee_email,
    ed.status AS employee_status,
    COALESCE(urm.designation, ed.title) AS designation,
    COALESCE(urm.role, 'User') AS enterprise_role,
    urm.department AS urm_department,
    urm.location AS urm_location,
    urm.login_status,
    urm.active AS urm_active
FROM users u
LEFT JOIN employee_details ed ON (
    u.employee_id = ed.emp_id
    OR (u.employee_id IS NULL AND LOWER(u.email) = LOWER(ed.email_address) AND ed.org_id = u.org_id)
)
LEFT JOIN user_role_management urm ON (
    ed.emp_id = urm.emp_id
    OR LOWER(u.email) = LOWER(urm.email_address)
);

-- 5. Index on the FK for fast joins
CREATE INDEX IF NOT EXISTS idx_users_employee_id ON users(employee_id);
