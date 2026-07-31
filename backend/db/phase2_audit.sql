-- Phase 2: Audit test/garbage data in PostgreSQL
-- Run: psql -U stratroom -d stratroom -f phase2_audit.sql

\echo '=== All tables ==='
SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name;

\echo '=== org_members with test/demo patterns ==='
SELECT id, org_id, email, first_name, last_name, role 
FROM org_members 
WHERE email LIKE '%test%' 
   OR email LIKE '%demo%'
   OR first_name ILIKE '%test%' 
   OR last_name ILIKE '%test%'
   OR first_name ILIKE '%tester%'
ORDER BY id;

\echo '=== risks with test/short patterns ==='
SELECT id, org_id, risk_name, status 
FROM risks 
WHERE risk_name ILIKE '%test%' 
   OR risk_name ILIKE '%demo%'
   OR risk_name ILIKE '%delete%'
   OR risk_name ILIKE '%sample%'
   OR LENGTH(risk_name) < 4
ORDER BY id;

\echo '=== initiatives with test patterns ==='
SELECT id, org_id, name, status 
FROM initiatives 
WHERE name ILIKE '%test%' 
   OR name ILIKE '%demo%'
   OR name ILIKE '%delete%'
   OR LENGTH(name) < 4
ORDER BY id;

\echo '=== incidents with test patterns ==='
SELECT id, org_id, title 
FROM incidents 
WHERE title ILIKE '%test%' 
   OR title ILIKE '%demo%'
   OR title ILIKE '%delete%'
   OR LENGTH(title) < 4
ORDER BY id;

\echo '=== scorecards with test patterns ==='
SELECT id, org_id, title 
FROM scorecards 
WHERE title ILIKE '%test%' 
   OR title ILIKE '%demo%'
   OR title ILIKE '%delete%'
   OR LENGTH(title) < 4
ORDER BY id;

\echo '=== tasks with test patterns ==='
SELECT id, org_id, title 
FROM tasks 
WHERE title ILIKE '%test%' 
   OR title ILIKE '%demo%'
   OR title ILIKE '%delete%'
   OR LENGTH(title) < 4
ORDER BY id;

\echo '=== budgets with test patterns ==='
SELECT id, org_id, gl_name, project
FROM budgets
WHERE gl_name ILIKE '%test%'
   OR project ILIKE '%test%'
   OR gl_name ILIKE '%demo%'
   OR project ILIKE '%demo%'
ORDER BY id;

\echo '=== meetings with test patterns ==='
SELECT id, org_id, title
FROM meetings
WHERE title ILIKE '%test%'
   OR title ILIKE '%demo%'
   OR title ILIKE '%delete%'
ORDER BY id;

\echo '=== complaints with test patterns ==='
SELECT id, org_id, title
FROM complaints
WHERE title ILIKE '%test%'
   OR title ILIKE '%demo%'
   OR title ILIKE '%delete%'
ORDER BY id;

\echo '=== documents with test patterns ==='
SELECT id, org_id, filename
FROM documents
WHERE filename ILIKE '%test%'
   OR filename ILIKE '%demo%'
   OR filename ILIKE '%delete%'
ORDER BY id;
