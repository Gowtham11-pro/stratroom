import logging
from app.services.java_bridge import bridge

logger = logging.getLogger("stratroom.migrations")


async def ensure_schema():
    """Ensure all required MySQL tables, columns, indexes, and initial seeds exist.

    Idempotent — runs safely at FastAPI startup.
    """
    try:
        # 1. user_module_permissions table
        await bridge._mysql_write(
            "CREATE TABLE IF NOT EXISTS user_module_permissions ("
            "  id INT AUTO_INCREMENT PRIMARY KEY, "
            "  emp_id INT NOT NULL, "
            "  org_id INT NOT NULL, "
            "  module_name VARCHAR(50) NOT NULL, "
            "  can_view TINYINT(1) NOT NULL DEFAULT 1, "
            "  can_edit TINYINT(1) NOT NULL DEFAULT 0, "
            "  can_delete TINYINT(1) NOT NULL DEFAULT 0, "
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
            "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
            "  UNIQUE KEY uk_emp_module (emp_id, module_name), "
            "  INDEX idx_org_module (org_id, module_name) "
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
        )

        # 2. Add scorecard_id column to scorecard_kpis if not exists
        try:
            cols = await bridge._mysql("SHOW COLUMNS FROM scorecard_kpis LIKE 'scorecard_id'")
            if not cols:
                await bridge._mysql_write(
                    "ALTER TABLE scorecard_kpis ADD COLUMN scorecard_id INT NULL DEFAULT NULL AFTER org_id"
                )
                await bridge._mysql_write(
                    "ALTER TABLE scorecard_kpis ADD INDEX idx_scorecard_id (scorecard_id)"
                )
                logger.info("Added scorecard_id column to scorecard_kpis")
        except Exception as exc:
            logger.warning("Migration check scorecard_kpis: %s", exc)

        # 3. Add source_module and page_name to task_details if not exists
        try:
            cols = await bridge._mysql("SHOW COLUMNS FROM task_details LIKE 'source_module'")
            if not cols:
                await bridge._mysql_write(
                    "ALTER TABLE task_details ADD COLUMN source_module VARCHAR(30) NULL DEFAULT NULL AFTER status"
                )
                await bridge._mysql_write(
                    "ALTER TABLE task_details ADD INDEX idx_source_module (source_module)"
                )
                logger.info("Added source_module column to task_details")
        except Exception as exc:
            logger.warning("Migration check task_details source_module: %s", exc)

        try:
            cols = await bridge._mysql("SHOW COLUMNS FROM task_details LIKE 'page_name'")
            if not cols:
                await bridge._mysql_write(
                    "ALTER TABLE task_details ADD COLUMN page_name VARCHAR(100) NULL DEFAULT NULL AFTER source_module"
                )
                logger.info("Added page_name column to task_details")
        except Exception as exc:
            logger.warning("Migration check task_details page_name: %s", exc)

        # 4. Add page_name to risk_details if not exists
        try:
            cols = await bridge._mysql("SHOW COLUMNS FROM risk_details LIKE 'page_name'")
            if not cols:
                await bridge._mysql_write(
                    "ALTER TABLE risk_details ADD COLUMN page_name VARCHAR(100) NULL DEFAULT NULL AFTER status"
                )
                await bridge._mysql_write(
                    "ALTER TABLE risk_details ADD INDEX idx_risk_page_name (page_name)"
                )
                logger.info("Added page_name column to risk_details")
        except Exception as exc:
            logger.warning("Migration check risk_details page_name: %s", exc)

        # 5. Backfill source_module for risk-linked tasks
        try:
            await bridge._mysql_write(
                "UPDATE task_details SET source_module = 'risk' "
                "WHERE task_value LIKE '%linkedRiskId%' AND (source_module IS NULL OR source_module = '')"
            )
        except Exception as exc:
            logger.warning("Migration backfill source_module: %s", exc)

        # 6. Seed default user_module_permissions if empty
        try:
            cnt = await bridge._mysql("SELECT COUNT(*) as count FROM user_module_permissions", one=True)
            if cnt and cnt.get("count", 0) == 0:
                await bridge._mysql_write(
                    "INSERT IGNORE INTO user_module_permissions (emp_id, org_id, module_name, can_view, can_edit, can_delete) "
                    "SELECT ed.emp_id, ed.org_id, m.module_name, 1, 1, 1 "
                    "FROM employee_details ed "
                    "CROSS JOIN ( "
                    "  SELECT 'risk' AS module_name UNION ALL SELECT 'tasks' UNION ALL SELECT 'scorecard' "
                    "  UNION ALL SELECT 'initiatives' UNION ALL SELECT 'audit' UNION ALL SELECT 'compliance' "
                    "  UNION ALL SELECT 'meetings' UNION ALL SELECT 'budgets' UNION ALL SELECT 'swot' "
                    "  UNION ALL SELECT 'pestel' UNION ALL SELECT 'projects' UNION ALL SELECT 'decisions' "
                    "  UNION ALL SELECT 'incidents' UNION ALL SELECT 'org' UNION ALL SELECT 'documents' "
                    ") m"
                )
                logger.info("Seeded default user_module_permissions")
        except Exception as exc:
            logger.warning("Migration seed permissions: %s", exc)

        logger.info("Schema verification completed successfully")
    except Exception as exc:
        logger.exception("Schema migration check error: %s", exc)
