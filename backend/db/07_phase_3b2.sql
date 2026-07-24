-- Phase 3B.2: AI agent run metrics

CREATE TABLE IF NOT EXISTS ai_agent_runs (
    id SERIAL PRIMARY KEY,
    org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    agent_name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    conversation_id INTEGER REFERENCES agent_conversations(id) ON DELETE SET NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'error')),
    duration_ms INTEGER,
    token_count INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_runs_org ON ai_agent_runs(org_id);
CREATE INDEX IF NOT EXISTS idx_ai_runs_agent ON ai_agent_runs(agent_name);
CREATE INDEX IF NOT EXISTS idx_ai_runs_user ON ai_agent_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_runs_created ON ai_agent_runs(created_at);
