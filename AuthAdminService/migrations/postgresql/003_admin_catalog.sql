-- Catalogs managed by QtAdmin. Casbin remains the enforcement source for
-- account actions; auth_account_grant keeps the operator-facing grant data.

CREATE TABLE IF NOT EXISTS auth_menu (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    parent_id VARCHAR(64) REFERENCES auth_menu(id),
    resource VARCHAR(256) NOT NULL,
    action VARCHAR(64) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS auth_account_grant (
    id BIGSERIAL PRIMARY KEY,
    subject VARCHAR(128) NOT NULL,
    domain VARCHAR(128) NOT NULL,
    account VARCHAR(64) NOT NULL,
    action VARCHAR(64) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_auth_account_grant UNIQUE (subject, domain, account, action)
);
CREATE INDEX IF NOT EXISTS idx_auth_account_grant_subject
    ON auth_account_grant (subject, domain, active);
