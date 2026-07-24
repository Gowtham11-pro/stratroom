-- Phase 3B.3: AI memory system

CREATE TABLE IF NOT EXISTS ai_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    agent_name TEXT NOT NULL,
    insight TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'conversation',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0.0 AND confidence <= 1.0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ai_mem_user ON ai_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_mem_org ON ai_memory(org_id);
CREATE INDEX IF NOT EXISTS idx_ai_mem_agent ON ai_memory(agent_name);
CREATE INDEX IF NOT EXISTS idx_ai_mem_user_agent ON ai_memory(user_id, agent_name);
CREATE INDEX IF NOT EXISTS idx_ai_mem_confidence ON ai_memory(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_ai_mem_accessed ON ai_memory(accessed_at);
