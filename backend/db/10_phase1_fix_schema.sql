-- Phase 1: Add assigned_user_id columns + complaints table
-- Idempotent: safe to run multiple times

-- 1. Add assigned_user_id to existing tables
ALTER TABLE scorecards ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

-- 2. Create complaints table
CREATE TABLE IF NOT EXISTS complaints (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT 'general',
    severity TEXT DEFAULT 'Medium',
    status TEXT DEFAULT 'open',
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    submitted_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

-- 3. Create indexes
CREATE INDEX IF NOT EXISTS idx_scorecards_user ON scorecards(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_user ON audit_findings(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_complaints_org ON complaints(org_id);
CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(assigned_user_id);

-- 4. Seed: assign existing data to user id=1 (admin@stratroom.com)
UPDATE scorecards SET assigned_user_id = 1 WHERE org_id = 1 AND assigned_user_id IS NULL;
UPDATE tasks SET assigned_user_id = 1 WHERE org_id = 1 AND assigned_user_id IS NULL;
UPDATE audit_findings SET assigned_user_id = 1 WHERE org_id = 1 AND assigned_user_id IS NULL;

-- 5. Seed: sample complaints (idempotent via ON CONFLICT)
INSERT INTO complaints (org_id, title, description, category, severity, status, assigned_user_id, submitted_by) VALUES
(1, 'Vendor SLA Breach -- Cloud Provider', 'AWS us-east-1 latency spike exceeded 99.9% SLA threshold for 4 consecutive hours', 'vendor', 'High', 'open', 1, 'Priya Sharma'),
(1, 'Employee Data Access Request', 'Former contractor account still has active permissions to production database', 'security', 'Critical', 'in_progress', 1, 'David Kim'),
(1, 'Budget Variance Report Discrepancy', 'Q3 budget report shows $42K variance between finance and ops tracking systems', 'finance', 'Medium', 'open', 1, 'Marcus Webb')
ON CONFLICT DO NOTHING;
