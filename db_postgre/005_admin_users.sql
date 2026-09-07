BEGIN;

CREATE TABLE IF NOT EXISTS admin_users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(150),
    role VARCHAR(50) NOT NULL DEFAULT 'admin',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    session_version INTEGER NOT NULL DEFAULT 1,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_admin_users_username_not_blank
        CHECK (BTRIM(username) <> ''),
    CONSTRAINT chk_admin_users_password_hash_not_blank
        CHECK (BTRIM(password_hash) <> ''),
    CONSTRAINT chk_admin_users_role_not_blank
        CHECK (BTRIM(role) <> ''),
    CONSTRAINT chk_admin_users_session_version
        CHECK (session_version > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_admin_users_username_lower
ON admin_users(LOWER(username));

CREATE INDEX IF NOT EXISTS idx_admin_users_active
ON admin_users(is_active, role);

INSERT INTO admin_users (
    username,
    password_hash,
    display_name,
    role
)
VALUES (
    'admin',
    'PASSWORD_HASH_O_DAY',
    'Quản trị viên',
    'admin'
)
RETURNING *;

COMMIT;
