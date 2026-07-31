-- Migration 16: AI agent tables in MySQL
-- Creates tables for AI agent observability and memory storage.
--
-- These tables are written by:
--   ai/metrics.py  → log_agent_run()   → ai_agent_runs (via bridge._mysql_write)
--   ai/memory.py   → store_memory()    → ai_memory     (via bridge._mysql_write)
--   ai/memory.py   → retrieve_memory() → ai_memory     (via bridge._mysql)
--   ai/memory.py   → prune_memory()    → ai_memory     (via bridge._mysql_write)
--
-- Created: 2026-07-29
-- Previous PG equivalents (now deprecated):
--   PostgreSQL ai_agent_runs → MySQL ai_agent_runs
--   PostgreSQL ai_memory     → MySQL ai_memory

-- ── ai_agent_runs: per-agent-call observability ──
CREATE TABLE IF NOT EXISTS ai_agent_runs (
    id INT NOT NULL AUTO_INCREMENT,
    org_id INT DEFAULT NULL,
    user_id INT DEFAULT NULL,
    agent_name VARCHAR(100) DEFAULT NULL,
    provider VARCHAR(50) DEFAULT NULL,
    model VARCHAR(200) DEFAULT NULL,
    conversation_id INT DEFAULT NULL,
    status VARCHAR(20) DEFAULT NULL,
    duration_ms INT DEFAULT NULL,
    token_count INT DEFAULT NULL,
    error_message TEXT,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ── ai_memory: agent memory (insights, retrieval, pruning) ──
CREATE TABLE IF NOT EXISTS ai_memory (
    id INT NOT NULL AUTO_INCREMENT,
    user_id INT DEFAULT NULL,
    org_id INT DEFAULT NULL,
    agent_name VARCHAR(100) DEFAULT NULL,
    insight TEXT,
    source VARCHAR(100) DEFAULT NULL,
    confidence FLOAT DEFAULT NULL,
    created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    access_count INT DEFAULT '0',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
