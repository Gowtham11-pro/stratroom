-- StratRoom core schema

CREATE TABLE IF NOT EXISTS organizations (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('P1','P2','P3')),
    status TEXT NOT NULL DEFAULT 'open',
    region TEXT,
    mttr_hours NUMERIC,
    sla_hours NUMERIC,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS risks (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    owner TEXT,
    inherent_likelihood INTEGER CHECK (inherent_likelihood BETWEEN 1 AND 5),
    inherent_impact INTEGER CHECK (inherent_impact BETWEEN 1 AND 5),
    residual_likelihood INTEGER CHECK (residual_likelihood BETWEEN 1 AND 5),
    residual_impact INTEGER CHECK (residual_impact BETWEEN 1 AND 5),
    description TEXT,
    mitigation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS initiatives (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    percent_complete NUMERIC DEFAULT 0,
    budget_planned NUMERIC,
    budget_actual NUMERIC,
    status TEXT NOT NULL DEFAULT 'on_track',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_incidents_org ON incidents(org_id);
CREATE INDEX IF NOT EXISTS idx_risks_org ON risks(org_id);
CREATE INDEX IF NOT EXISTS idx_initiatives_org ON initiatives(org_id);

CREATE TABLE IF NOT EXISTS scorecards (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    perspective TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    target NUMERIC,
    actual NUMERIC,
    owner TEXT,
    status TEXT DEFAULT 'on-track',
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS budget_lines (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    month TEXT,
    gl_account TEXT,
    gl_name TEXT,
    budget_type TEXT DEFAULT 'Expense',
    project TEXT,
    total NUMERIC DEFAULT 0,
    department TEXT,
    employee TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    agent TEXT,
    priority TEXT DEFAULT 'Medium',
    owner TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'pending',
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    meeting_date TEXT,
    meeting_time TEXT,
    location TEXT,
    duration TEXT,
    attendees TEXT,
    priority TEXT DEFAULT 'Medium',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_findings (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    severity TEXT DEFAULT 'Medium',
    owner TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'open',
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS compliance_frameworks (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    score NUMERIC DEFAULT 0,
    status TEXT DEFAULT 'PASS',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS org_members (
    id TEXT PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    parent_id TEXT,
    name TEXT NOT NULL,
    title TEXT,
    dept TEXT,
    region TEXT,
    level TEXT,
    headcount INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS swot_items (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    quadrant TEXT NOT NULL,
    content TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pestel_items (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    impact TEXT NOT NULL,
    content TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    owner TEXT,
    budget TEXT DEFAULT '',
    progress INTEGER DEFAULT 0,
    due_date TEXT DEFAULT '',
    status TEXT DEFAULT 'on_track',
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bcp_processes (
    id SERIAL PRIMARY KEY,
    org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    parent_id INTEGER,
    name TEXT NOT NULL,
    owner TEXT,
    rto TEXT,
    rpo TEXT,
    mtd TEXT,
    impact TEXT,
    status TEXT DEFAULT 'active',
    category TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE INDEX IF NOT EXISTS idx_scorecards_org ON scorecards(org_id);
CREATE INDEX IF NOT EXISTS idx_scorecards_user ON scorecards(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_budget_lines_org ON budget_lines(org_id);
CREATE INDEX IF NOT EXISTS idx_tasks_org ON tasks(org_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_meetings_org ON meetings(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_org ON audit_findings(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_findings_user ON audit_findings(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_compliance_frameworks_org ON compliance_frameworks(org_id);
CREATE INDEX IF NOT EXISTS idx_org_members_org ON org_members(org_id);
CREATE INDEX IF NOT EXISTS idx_swot_items_org ON swot_items(org_id);
CREATE INDEX IF NOT EXISTS idx_pestel_items_org ON pestel_items(org_id);
CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(org_id);
CREATE INDEX IF NOT EXISTS idx_bcp_processes_org ON bcp_processes(org_id);
CREATE INDEX IF NOT EXISTS idx_complaints_org ON complaints(org_id);
CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(assigned_user_id);

-- Seed org
INSERT INTO organizations (name) VALUES ('Demo Org') ON CONFLICT DO NOTHING;

-- Seed demo user (password = "changeme")
INSERT INTO users (org_id, email, hashed_password, full_name, role)
VALUES (
    1,
    'admin@stratroom.com',
    '$2b$12$r8IIn0LTYtPnHI6u9GwQZeP/bGhylg5GUoPRcdOPR6pqnP3XgQ7Z.',
    'Sarah Mitchell',
    'CEO'
)
ON CONFLICT (email) DO NOTHING;

-- Seed org_members (hierarchical org chart)
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
('mgr-legal',1, 'ceo-1', 'Sophie Laurent',    'General Counsel',           'Legal',     'Europe',       'Director', 4, 12);

-- Seed risks
INSERT INTO risks (org_id, name, owner, inherent_likelihood, inherent_impact, residual_likelihood, residual_impact, description, mitigation) VALUES
(1, 'Supply Chain Disruption', 'Sarah Mitchell', 4, 5, 3, 4, 'Key supplier dependency with single-source risk for critical components', 'Dual sourcing strategy in progress'),
(1, 'Regulatory Compliance Gap', 'Sarah Mitchell', 3, 4, 2, 3, 'Upcoming GDPR amendments may require system architecture changes', 'Legal review and impact assessment initiated'),
(1, 'Cybersecurity Breach', 'Sarah Mitchell', 5, 5, 3, 4, 'Advanced persistent threat targeting financial data systems', 'SOC monitoring and zero-trust architecture deployment'),
(1, 'Market Volatility', 'Sarah Mitchell', 4, 3, 3, 3, 'Currency fluctuation impacting international revenue streams', 'Hedging strategy and diversification of revenue regions'),
(1, 'Talent Retention Risk', 'Sarah Mitchell', 3, 3, 2, 2, 'Critical engineering roles with high turnover in competitive market', 'Compensation review and career development programs'),
(1, 'Operational Resilience', 'Sarah Mitchell', 3, 4, 2, 3, 'Business continuity plan not tested in 18 months', 'Scheduled tabletop exercises and BCP refresh'),
(1, 'Third-Party Vendor Risk', 'Sarah Mitchell', 4, 4, 3, 3, 'Multiple vendors with access to sensitive data, inconsistent security posture', 'Vendor risk assessment program and continuous monitoring'),
(1, 'Data Quality Governance', 'Sarah Mitchell', 3, 3, 2, 2, 'Inconsistent data definitions across business units affecting reporting accuracy', 'Data governance framework implementation'),
(1, 'Climate & ESG Compliance', 'Sarah Mitchell', 2, 4, 2, 3, 'New sustainability reporting requirements approaching deadline', 'ESG data collection and reporting tool implementation'),
(1, 'Intellectual Property Exposure', 'Sarah Mitchell', 3, 4, 2, 3, 'Risk of trade secret leakage through contractor access controls', 'DLP policies and access review procedures'),
(1, 'Infrastructure Scalability', 'Sarah Mitchell', 3, 3, 2, 2, 'Current cloud infrastructure may not support projected 3x growth', 'Architecture review and capacity planning'),
(1, 'Financial Reporting Risk', 'Sarah Mitchell', 2, 5, 1, 4, 'Complex multi-entity consolidation with manual intervention points', 'ERP automation and controls modernization');

-- Seed incidents
INSERT INTO incidents (org_id, code, title, severity, status, region, mttr_hours, sla_hours) VALUES
(1, 'INC-2026-001', 'Ransomware Detection on File Server', 'P1', 'resolved', 'North America', 18.5, 24),
(1, 'INC-2026-002', 'Customer Data Export Anomaly', 'P1', 'open', 'Europe', NULL, 24),
(1, 'INC-2026-003', 'ERP Batch Processing Failure', 'P2', 'open', 'Global', NULL, 48),
(1, 'INC-2026-004', 'Vendor Portal Authentication Bypass', 'P1', 'in_progress', 'North America', NULL, 24),
(1, 'INC-2026-005', 'Financial Reconciliation Discrepancy', 'P2', 'open', 'North America', NULL, 48),
(1, 'INC-2026-006', 'Cloud Service Degradation', 'P2', 'resolved', 'Asia Pacific', 12.0, 48),
(1, 'INC-2026-007', 'Phishing Campaign Targeting Executives', 'P3', 'resolved', 'Global', 8.0, 72),
(1, 'INC-2026-008', 'Database Replication Lag Alert', 'P3', 'open', 'Europe', NULL, 72);

-- Seed initiatives
INSERT INTO initiatives (org_id, name, percent_complete, budget_planned, budget_actual, status) VALUES
(1, 'Zero Trust Security Rollout', 45, 250000, 118000, 'on_track'),
(1, 'ERP Modernization Program', 28, 1200000, 360000, 'on_track'),
(1, 'ESG Reporting Framework', 62, 150000, 95000, 'ahead'),
(1, 'Cloud Migration Phase 2', 15, 800000, 135000, 'at_risk'),
(1, 'SOC 2 Type II Certification', 70, 200000, 145000, 'on_track');

-- Seed scorecards
INSERT INTO scorecards (org_id, perspective, kpi_name, target, actual, owner, status, assigned_user_id) VALUES
(1, 'Financial', 'Revenue Growth', 85, 82, 'CFO', 'on-track', 1),
(1, 'Financial', 'Cost Efficiency', 90, 91, 'CFO', 'on-track', 1),
(1, 'Financial', 'EBITDA Margin', 80, 74, 'CFO', 'at-risk', 1),
(1, 'Customer', 'Customer Experience', 80, 74, 'CCO', 'at-risk', 1),
(1, 'Customer', 'NPS Score', 70, 74, 'CCO', 'on-track', 1),
(1, 'Customer', 'Market Share', 75, 67, 'CCO', 'at-risk', 1),
(1, 'Internal Processes', 'Digital Transformation', 80, 63, 'CTO', 'critical', 1),
(1, 'Internal Processes', 'Cloud Migration', 70, 67, 'CTO', 'at-risk', 1),
(1, 'Internal Processes', 'Process Efficiency', 80, 71, 'CTO', 'at-risk', 1),
(1, 'Learning & Growth', 'Talent Retention', 80, 58, 'CHRO', 'critical', 1),
(1, 'Learning & Growth', 'Employee Engagement', 80, 71, 'CHRO', 'at-risk', 1),
(1, 'Learning & Growth', 'Innovation Pipeline', 75, 69, 'CHRO', 'at-risk', 1),
(1, 'ESG & Compliance', 'ESG Targets', 85, 91, 'CSO', 'on-track', 1),
(1, 'ESG & Compliance', 'Carbon Reduction', 80, 88, 'CSO', 'on-track', 1),
(1, 'ESG & Compliance', 'Reg. Compliance', 95, 96, 'CSO', 'on-track', 1),
(1, 'Risk & Security', 'Cybersecurity Posture', 85, 78, 'CISO', 'at-risk', 1),
(1, 'Risk & Security', 'Risk Heat Score', 80, 78, 'CISO', 'at-risk', 1),
(1, 'Risk & Security', 'Supply Chain', 80, 81, 'COO', 'on-track', 1);

-- Seed budget lines
INSERT INTO budget_lines (org_id, year, month, gl_account, gl_name, budget_type, project, total, department, employee, notes) VALUES
(1, 2024, 'June', '104', 'Advertisements', 'Expense', 'Manage public affairs', 60000, '1049', 'Nizam Goolam', 'Advertorial'),
(1, 2024, 'April', '104', 'Advertisements', 'Expense', 'Manage public affairs', 386880, '1049', 'Nizam Goolam', 'Radio advert'),
(1, 2024, 'April', '18', 'Board Expenses', 'Expense', 'Uphold good governance', 12600, '1049', 'Nizam Goolam', 'Lunch'),
(1, 2024, 'May', '18', 'Board Expenses', 'Expense', 'Uphold good governance', 34000, '1049', 'Rachel Kim', 'Q2 board travel'),
(1, 2024, 'March', '22', 'IT Infrastructure', 'Capital', 'Digital Transformation', 135000, '1012', 'Aiko Tanaka', 'AWS reserved instances'),
(1, 2024, 'March', '22', 'IT Infrastructure', 'Capital', 'Digital Transformation', 28000, '1012', 'Aiko Tanaka', 'SaaS enterprise licenses'),
(1, 2024, 'July', '31', 'Training & Development', 'Expense', 'Build talent pipeline', 38400, '1033', 'Linh Nguyen', 'Leadership cohort 2024'),
(1, 2024, 'July', '31', 'Training & Development', 'Expense', 'Build talent pipeline', 15000, '1033', 'Linh Nguyen', 'Coursera enterprise'),
(1, 2024, 'August', '55', 'Marketing & Events', 'Expense', 'Grow market presence', 150000, '1055', 'Sarah Mitchell', 'APAC summit Q3'),
(1, 2024, 'August', '55', 'Marketing & Events', 'Expense', 'Grow market presence', 42000, '1055', 'Sarah Mitchell', 'LinkedIn + Meta Q3'),
(1, 2024, 'September', '67', 'Compliance & Legal', 'Expense', 'Regulatory compliance', 55000, '1049', 'Rachel Kim', 'Data protection audit'),
(1, 2024, 'September', '67', 'Compliance & Legal', 'Expense', 'Regulatory compliance', 38000, '1049', 'Priya Sharma', 'Deloitte SOC2 audit'),
(1, 2024, 'October', '104', 'Advertisements', 'Expense', 'Manage public affairs', 92000, '1049', 'Nizam Goolam', 'Year-end campaign'),
(1, 2024, 'October', '78', 'Operations & Facilities', 'Expense', 'Optimise operations', 222000, '1060', 'Marcus Webb', 'HQ lease FY2025'),
(1, 2024, 'November', '89', 'Research & Innovation', 'Capital', 'Innovation lab', 180000, '1012', 'Daniel Reyes', 'AI assistant MVP'),
(1, 2024, 'November', '31', 'Training & Development', 'Expense', 'Build talent pipeline', 22000, '1033', 'Linh Nguyen', 'Q4 retreats'),
(1, 2025, 'January', '22', 'IT Infrastructure', 'Capital', 'Digital Transformation', 95000, '1012', 'Aiko Tanaka', 'Phase 2 kickoff'),
(1, 2025, 'February', '55', 'Marketing & Events', 'Expense', 'Grow market presence', 110000, '1055', 'Sarah Mitchell', 'MEA market launch');

-- Seed tasks
INSERT INTO tasks (org_id, title, agent, priority, owner, due_date, status, assigned_user_id) VALUES
(1, 'Escalate cyber risk review to CISO -- schedule emergency committee meeting', 'Risk Agent', 'Critical', 'CRO, CIO', 'Today', 'pending', 1),
(1, 'Reallocate $2.4M from underperforming program to Digital Transformation initiative', 'Finance Agent', 'High', 'CFO', 'Oct 15', 'pending', 1),
(1, 'Initiate vendor diversification RFP for APAC logistics -- 3 alternatives minimum', 'Risk Agent', 'Medium', 'COO', 'Oct 20', 'pending', 1),
(1, 'Schedule MEA market entry go/no-go decision with executive committee', 'Strategy Agent', 'Medium', 'CEO', 'Oct 18', 'pending', 1),
(1, 'Initiate talent retention program for Product division -- three senior engineers at risk', 'Predictive Layer', 'High', 'CHRO', 'Oct 22', 'pending', 1),
(1, 'Review and approve Q4 security penetration test results', 'Risk Agent', 'High', 'CISO', 'Oct 17', 'in_progress', 1),
(1, 'Update incident response playbook for cloud-native workloads', 'Risk Agent', 'Medium', 'CISO', 'Oct 25', 'in_progress', 1);

-- Seed meetings
INSERT INTO meetings (org_id, title, meeting_date, meeting_time, location, duration, attendees, priority) VALUES
(1, 'Executive Risk Review Committee', 'Oct 15', '10:00 AM', 'Boardroom A', '60 min', 'CEO, CRO, CISO, CFO, COO', 'Critical'),
(1, 'Q4 Budget Planning Session', 'Oct 17', '02:00 PM', 'Virtual', '90 min', 'CFO, Finance Directors, BU Heads', 'High'),
(1, 'MEA Market Entry Go/No-Go Decision', 'Oct 18', '09:00 AM', 'Boardroom B', '2 hrs', 'CEO, Board Members, Strategy Lead, Country Manager', 'Strategic'),
(1, 'SOC2 Compliance & Audit Readiness Review', 'Oct 21', '11:00 AM', 'Virtual', '45 min', 'CISO, Compliance Officer, Audit Lead, Legal', 'Compliance');

-- Seed audit findings
INSERT INTO audit_findings (org_id, title, severity, owner, due_date, status, assigned_user_id) VALUES
(1, 'Access Control Review -- Privileged Accounts', 'Critical', 'CISO', 'Oct 20', 'open', 1),
(1, 'Vendor Due Diligence Documentation Gaps', 'High', 'Procurement', 'Oct 25', 'open', 1),
(1, 'Disaster Recovery Test Evidence Missing', 'Medium', 'IT Ops', 'Oct 22', 'open', 1),
(1, 'Security Awareness Training -- 72% Completion', 'Low', 'HR', 'Nov 1', 'open', 1);

-- Seed compliance frameworks
INSERT INTO compliance_frameworks (org_id, name, description, score, status) VALUES
(1, 'SOC2 Type II', 'All controls passing. Last reviewed Oct 1.', 100, 'PASS'),
(1, 'GDPR', 'Data processing agreements current. Next audit Jun 15.', 96, 'PASS'),
(1, 'Data Retention Policy', 'Minor gap in archival policy for EU data. Must be remediated before GDPR audit Jun 15.', 85, 'GAP');

-- Seed SWOT items
INSERT INTO swot_items (org_id, quadrant, content, sort_order) VALUES
(1, 'strength', 'Revenue Growth at 82% of target - strong financial performance', 1),
(1, 'strength', 'Cost Efficiency exceeding targets at 91%', 2),
(1, 'strength', 'NPS Score above target at 74 - healthy customer sentiment', 3),
(1, 'strength', 'ESG Targets exceeded at 91% - industry-leading sustainability', 4),
(1, 'strength', 'Carbon Reduction on track at 88% - strong environmental position', 5),
(1, 'strength', 'Regulatory Compliance passing at 96% - solid governance', 6),
(1, 'weakness', 'Digital Transformation lagging at 63% - critical gap in tech modernization', 1),
(1, 'weakness', 'Talent Retention at 58% - highest priority HR concern', 2),
(1, 'weakness', 'Customer Experience below target at 74% - satisfaction declining', 3),
(1, 'weakness', 'Market Share losing ground at 67% - competitive pressure mounting', 4),
(1, 'weakness', 'EBITDA Margin underperforming at 74% - profitability concern', 5),
(1, 'opportunity', 'Cloud Migration Phase 2 - expand to multi-cloud for 3x scale', 1),
(1, 'opportunity', 'ERP Modernization - consolidate systems to reduce manual intervention', 2),
(1, 'opportunity', 'MEA Market Entry - new revenue stream with go/no-go decision pending', 3),
(1, 'opportunity', 'AI Assistant MVP - innovation lab driving next-gen capabilities', 4),
(1, 'opportunity', 'SOC 2 Type II Certification - opens enterprise sales channel', 5),
(1, 'threat', 'Cybersecurity Breach - advanced persistent threat targeting financial systems (Score: 25)', 1),
(1, 'threat', 'Supply Chain Disruption - single-source dependency for critical components (Score: 20)', 2),
(1, 'threat', 'Third-Party Vendor Risk - multiple vendors with inconsistent security posture (Score: 16)', 3),
(1, 'threat', 'Operational Resilience - BCP not tested in 18 months', 4),
(1, 'threat', 'Regulatory Compliance Gap - GDPR amendments may require architecture changes', 5);

-- Seed PESTEL items
INSERT INTO pestel_items (org_id, category, impact, content, sort_order) VALUES
(1, 'political', 'High', 'GDPR amendments pending - may require system architecture changes', 1),
(1, 'political', 'Medium', 'Data protection regulations tightening across all operating regions', 2),
(1, 'political', 'Low', 'MEA market entry requires local regulatory compliance alignment', 3),
(1, 'economic', 'High', 'Currency fluctuation impacting international revenue streams', 1),
(1, 'economic', 'Medium', 'Budget reallocation needed - $2.4M shift from underperforming to Digital Transformation', 2),
(1, 'economic', 'Low', 'Cost Efficiency targets being met at 91% - strong expense management', 3),
(1, 'social', 'High', 'Critical engineering talent at risk of attrition in competitive market', 1),
(1, 'social', 'Medium', 'Employee engagement below target at 71% - culture investment needed', 2),
(1, 'social', 'Low', 'Customer NPS at 74 - positive but needs improvement', 3),
(1, 'technology', 'High', 'Advanced persistent threat targeting financial data systems', 1),
(1, 'technology', 'High', 'Cloud infrastructure may not support projected 3x growth', 2),
(1, 'technology', 'Medium', 'ERP batch processing failures disrupting operations', 3),
(1, 'environmental', 'Medium', 'New sustainability reporting requirements approaching deadline', 1),
(1, 'environmental', 'Low', 'Carbon reduction on track at 88% - exceeding targets', 2),
(1, 'environmental', 'Low', 'ESG data collection tools being implemented for compliance', 3),
(1, 'legal', 'High', 'Trade secret leakage risk through contractor access controls', 1),
(1, 'legal', 'Medium', 'Multi-entity financial consolidation has manual intervention points', 2),
(1, 'legal', 'Low', 'SOC 2 Type II audit in progress - all controls currently passing', 3);

-- Seed projects
INSERT INTO projects (org_id, name, owner, budget, progress, due_date, status, sort_order) VALUES
(1, 'Zero Trust Security Rollout', 'CISO', '$250,000', 45, '2026-06-30', 'on_track', 1),
(1, 'ERP Modernization Program', 'CTO', '$1,200,000', 28, '2026-12-31', 'on_track', 2),
(1, 'ESG Reporting Framework', 'CSO', '$150,000', 62, '2026-03-31', 'ahead', 3),
(1, 'Cloud Migration Phase 2', 'CTO', '$800,000', 15, '2026-09-30', 'at_risk', 4),
(1, 'SOC 2 Type II Certification', 'CISO', '$200,000', 70, '2026-04-30', 'on_track', 5),
(1, 'Customer Experience Improvement', 'CCO', '$350,000', 35, '2026-08-31', 'on_track', 6),
(1, 'Talent Retention Program', 'CHRO', '$180,000', 20, '2026-07-31', 'at_risk', 7),
(1, 'MEA Market Expansion', 'CEO', '$500,000', 10, '2026-12-31', 'on_track', 8),
(1, 'Data Governance Framework', 'CTO', '$120,000', 40, '2026-06-30', 'on_track', 9),
(1, 'AI Assistant MVP', 'CTO', '$180,000', 55, '2026-05-31', 'on_track', 10);

-- Seed BCP processes
INSERT INTO bcp_processes (org_id, parent_id, name, owner, rto, rpo, mtd, impact, status, category, sort_order) VALUES
(1, NULL, 'Critical Business Operations', 'COO', '4 hours', '1 hour', '8 hours', 'Critical', 'active', 'Operations', 1),
(1, 1, 'Financial Systems & Reporting', 'CFO', '2 hours', '30 min', '4 hours', 'Critical', 'active', 'Finance', 2),
(1, 1, 'Customer Data & Services', 'CCO', '1 hour', '15 min', '2 hours', 'Critical', 'active', 'Customer', 3),
(1, 1, 'IT Infrastructure & Security', 'CISO', '30 min', '5 min', '1 hour', 'Critical', 'active', 'Technology', 4),
(1, 1, 'Supply Chain Operations', 'COO', '8 hours', '4 hours', '24 hours', 'High', 'active', 'Operations', 5),
(1, NULL, 'Compliance & Governance', 'CRO', '24 hours', '8 hours', '72 hours', 'High', 'active', 'Compliance', 6),
(1, 6, 'Regulatory Reporting', 'CFO', '12 hours', '4 hours', '48 hours', 'High', 'active', 'Finance', 7),
(1, 6, 'Audit & SOX Compliance', 'CISO', '24 hours', '8 hours', '72 hours', 'Medium', 'active', 'Compliance', 8),
(1, NULL, 'HR & Workforce', 'CHRO', '24 hours', '8 hours', '72 hours', 'Medium', 'active', 'People', 9),
(1, 9, 'Payroll Processing', 'CHRO', '4 hours', '1 hour', '8 hours', 'Critical', 'active', 'Finance', 10),
(1, 9, 'Talent Management System', 'CHRO', '48 hours', '24 hours', '96 hours', 'Low', 'active', 'People', 11);

-- Seed complaints
INSERT INTO complaints (org_id, title, description, category, severity, status, assigned_user_id, submitted_by) VALUES
(1, 'Vendor SLA Breach -- Cloud Provider', 'AWS us-east-1 latency spike exceeded 99.9% SLA threshold for 4 consecutive hours', 'vendor', 'High', 'open', 1, 'Priya Sharma'),
(1, 'Employee Data Access Request', 'Former contractor account still has active permissions to production database', 'security', 'Critical', 'in_progress', 1, 'David Kim'),
(1, 'Budget Variance Report Discrepancy', 'Q3 budget report shows $42K variance between finance and ops tracking systems', 'finance', 'Medium', 'open', 1, 'Marcus Webb');
