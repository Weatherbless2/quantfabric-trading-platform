-- QuantFabric authentication and authorization control plane.
-- Apply with a PostgreSQL migration runner after the business-base migrations.

CREATE TABLE IF NOT EXISTS auth_identity (
    id BIGSERIAL PRIMARY KEY,
    subject VARCHAR(128) NOT NULL UNIQUE,
    username VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL DEFAULT '',
    password_hash VARCHAR(512),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_service_principal (
    id BIGSERIAL PRIMARY KEY,
    subject VARCHAR(128) NOT NULL UNIQUE,
    display_name VARCHAR(128) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS auth_session (
    -- The C++ fixed packet accepts 31 non-NUL bytes. Sessions deliberately use
    -- 30 hexadecimal characters so every component can NUL-terminate safely.
    id VARCHAR(30) PRIMARY KEY CHECK (length(id) = 30),
    identity_id BIGINT NOT NULL REFERENCES auth_identity(id),
    auth_method VARCHAR(16) NOT NULL CHECK (auth_method IN ('oidc', 'development')),
    oidc_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_auth_session_active
    ON auth_session (identity_id, expires_at) WHERE revoked_at IS NULL;

-- Standard table used by casbin-sqlalchemy-adapter.  p rows are permissions;
-- g rows bind a user or service principal to a role within a business domain.
CREATE TABLE IF NOT EXISTS casbin_rule (
    id BIGSERIAL PRIMARY KEY,
    ptype VARCHAR(255),
    v0 VARCHAR(255),
    v1 VARCHAR(255),
    v2 VARCHAR(255),
    v3 VARCHAR(255),
    v4 VARCHAR(255),
    v5 VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_casbin_rule_lookup
    ON casbin_rule (ptype, v0, v1, v2, v3);

CREATE TABLE IF NOT EXISTS audit_event (
    id BIGSERIAL PRIMARY KEY,
    actor VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource VARCHAR(256) NOT NULL,
    domain VARCHAR(128) NOT NULL,
    result VARCHAR(16) NOT NULL CHECK (result IN ('ALLOW', 'DENY')),
    trace_id VARCHAR(128),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_event_trace ON audit_event (trace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_actor ON audit_event (actor, created_at DESC);

COMMENT ON TABLE auth_identity IS 'OIDC subject to QuantFabric operator mapping';
COMMENT ON TABLE auth_service_principal IS 'Strategy and internal-service identities';
COMMENT ON TABLE auth_session IS 'Short-lived opaque desktop/API sessions';
COMMENT ON TABLE casbin_rule IS 'Casbin RBAC-with-domains policy rows';
COMMENT ON TABLE audit_event IS 'Authorization decision audit trail';
