-- Agent conversation and message tables

CREATE TABLE IF NOT EXISTS agent_conversations (
    id SERIAL PRIMARY KEY,
    agent_name TEXT NOT NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    org_id INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
    title TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK (length(content) <= 50000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_conv_user ON agent_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_conv_agent ON agent_conversations(agent_name);
CREATE INDEX IF NOT EXISTS idx_agent_conv_org ON agent_conversations(org_id);
CREATE INDEX IF NOT EXISTS idx_agent_msg_conv ON agent_messages(conversation_id);
