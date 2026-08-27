BEGIN;

CREATE TABLE IF NOT EXISTS conversation_sessions (
    id BIGSERIAL PRIMARY KEY,

    channel VARCHAR(30) NOT NULL,
    session_key VARCHAR(255) NOT NULL,
    external_user_id VARCHAR(255),

    customer_name VARCHAR(255),
    customer_phone VARCHAR(30),

    status VARCHAR(30) NOT NULL DEFAULT 'active',

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT uq_conversation_session
        UNIQUE (channel, session_key),

    CONSTRAINT chk_conversation_session_status
        CHECK (
            status IN (
                'active',
                'completed',
                'cancelled'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_updated
ON conversation_sessions(last_message_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_sessions_external_user
ON conversation_sessions(channel, external_user_id);


CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGSERIAL PRIMARY KEY,

    conversation_id BIGINT NOT NULL
        REFERENCES conversation_sessions(id)
        ON DELETE CASCADE,

    channel VARCHAR(30) NOT NULL,
    external_message_id VARCHAR(255),

    role VARCHAR(20) NOT NULL,
    message_type VARCHAR(30) NOT NULL DEFAULT 'text',

    content TEXT,
    media JSONB NOT NULL DEFAULT '[]'::jsonb,

    intent VARCHAR(100),
    product_codes JSONB NOT NULL DEFAULT '[]'::jsonb,
    rag_sources JSONB NOT NULL DEFAULT '[]'::jsonb,

    ai_provider VARCHAR(30),
    ai_model VARCHAR(100),

    planner_ms INTEGER,
    executor_ms INTEGER,
    presenter_ms INTEGER,
    total_ms INTEGER,

    processing_status VARCHAR(30) NOT NULL DEFAULT 'completed',
    delivery_status VARCHAR(30) NOT NULL DEFAULT 'received',

    error_code VARCHAR(100),
    error_message TEXT,

    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_conversation_message_role
        CHECK (
            role IN ('user', 'assistant', 'system')
        ),

    CONSTRAINT chk_conversation_processing_status
        CHECK (
            processing_status IN (
                'pending',
                'completed',
                'failed'
            )
        ),

    CONSTRAINT chk_conversation_delivery_status
        CHECK (
            delivery_status IN (
                'received',
                'generated',
                'sent',
                'send_failed'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_session_time
ON conversation_messages(conversation_id, created_at);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_created
ON conversation_messages(created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_external_message
ON conversation_messages(channel, external_message_id)
WHERE external_message_id IS NOT NULL;

COMMIT;