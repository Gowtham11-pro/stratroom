-- Migration: Add assigned_user_id for per-user dashboard filtering
-- Run after 01_init.sql

-- Add assigned_user_id to existing tables
ALTER TABLE scorecards ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE audit_findings ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

-- Create complaints table
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

CREATE INDEX IF NOT EXISTS idx_scorecards_user ON scorecards(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_user ON audit_findings(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_complaints_org ON complaints(org_id);
CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(assigned_user_id);

-- Seed: assign existing scorecards to user id=1 (admin@stratroom.com / Sarah Mitchell)
UPDATE scorecards SET assigned_user_id = 1 WHERE org_id = 1;

-- Seed: assign existing tasks to user id=1
UPDATE tasks SET assigned_user_id = 1 WHERE org_id = 1;

-- Seed: assign existing audit findings to user id=1
UPDATE audit_findings SET assigned_user_id = 1 WHERE org_id = 1;

-- Seed: create sample complaints for user id=1
INSERT INTO complaints (org_id, title, description, category, severity, status, assigned_user_id, submitted_by) VALUES
(1, 'Vendor SLA Breach -- Cloud Provider', 'AWS us-east-1 latency spike exceeded 99.9% SLA threshold for 4 consecutive hours', 'vendor', 'High', 'open', 1, 'Priya Sharma'),
(1, 'Employee Data Access Request', 'Former contractor account still has active permissions to production database', 'security', 'Critical', 'in_progress', 1, 'David Kim'),
(1, 'Budget Variance Report Discrepancy', 'Q3 budget report shows $42K variance between finance and ops tracking systems', 'finance', 'Medium', 'open', 1, 'Marcus Webb');

-- Seed: org_members hierarchy — clear old data first, then insert
DELETE FROM org_members WHERE org_id = 1;
INSERT INTO org_members (id, org_id, parent_id, name, title, dept, region, level, headcount, sort_order) VALUES
('ceo-1',    1, NULL,     'Sarah Mitchell',  'Chief Executive Officer',    'Executive', 'Global',     'C-Suite',  120, 1),
('vp-tech',  1, 'ceo-1',  'James Chen',      'VP Engineering',            'Technology','North America','VP',      45,  2),
('vp-risk',  1, 'ceo-1',  'Maria Santos',    'VP Risk & Compliance',      'Risk',      'North America','VP',      18,  3),
('vp-fin',   1, 'ceo-1',  'Robert Kim',      'VP Finance',                'Finance',   'North America','VP',      22,  4),
('vp-ops',   1, 'ceo-1',  'Aisha Patel',     'VP Operations',             'Operations','Europe',      'VP',      35,  5),
('dir-fe',   1, 'vp-tech','Tom Bradley',      'Director, Frontend',        'Technology','North America','Director',12,  6),
('dir-be',   1, 'vp-tech','Lin Wei',          'Director, Backend',         'Technology','Asia Pacific', 'Director',15,  7),
('dir-sec',  1, 'vp-risk','David Okafor',     'Director, Security',        'Risk',      'Europe',       'Director', 8,  8),
('mgr-audit',1, 'vp-risk','Elena Volkov',     'Audit Manager',             'Risk',      'Europe',       'Manager',  5,  9),
('mgr-fin',  1, 'vp-fin','Priya Sharma',      'Financial Controller',      'Finance',   'Asia Pacific', 'Manager', 10, 10),
('mgr-hr',   1, 'vp-ops','Carlos Reyes',      'HR Director',               'Operations','North America','Director', 6, 11),
('mgr-legal',1, 'ceo-1', 'Sophie Laurent',    'General Counsel',           'Legal',     'Europe',       'Director', 4, 12)
ON CONFLICT (id) DO NOTHING;
