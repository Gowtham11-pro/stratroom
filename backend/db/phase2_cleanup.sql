-- Phase 2: Cleanup test/garbage rows in PostgreSQL
-- Run: docker exec stratroom_db psql -U stratroom -d stratroom -f /tmp/phase2_cleanup.sql

BEGIN;

-- ============================================================
-- DELETE garbage initiatives (7 rows)
-- ============================================================
DELETE FROM initiatives WHERE id IN (20,21,22,23,30,45,59);

-- ============================================================
-- DELETE garbage risks (7 rows)
-- ============================================================
DELETE FROM risks WHERE id IN (13,27,28,29,30,52,53);

-- ============================================================
-- DELETE garbage scorecards (31 rows)
-- ============================================================
DELETE FROM scorecards WHERE id IN (
  362, 369, 370, 371, 373, 374, 376, 377, 378, 380, 381, 382, 383, 384, 385, 386,
  397, 408, 409, 410, 413, 415, 417, 419, 422, 423, 425, 426, 427, 428, 433
);

-- ============================================================
-- VERIFY
-- ============================================================
SELECT 'initiatives' AS tbl, COUNT(*) AS cnt FROM initiatives
UNION ALL SELECT 'risks', COUNT(*) FROM risks
UNION ALL SELECT 'scorecards', COUNT(*) FROM scorecards;

COMMIT;
