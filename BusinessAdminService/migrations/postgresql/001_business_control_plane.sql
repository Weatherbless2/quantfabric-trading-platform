-- QuantFabric business control plane.
-- Apply to the dedicated business configuration database, not to the trading
-- runtime's local SQLite files. This migration deliberately does not create
-- databases, users or passwords.

CREATE TABLE IF NOT EXISTS business_config_version (
    id BIGSERIAL PRIMARY KEY,
    version INTEGER NOT NULL UNIQUE CHECK (version > 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('DRAFT', 'VALIDATED', 'PUBLISHED', 'RETIRED')),
    description VARCHAR(256) NOT NULL DEFAULT '',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by VARCHAR(128),
    published_at TIMESTAMPTZ,
    source_version_id BIGINT REFERENCES business_config_version(id),
    CHECK ((status <> 'PUBLISHED') OR (published_by IS NOT NULL AND published_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_business_one_published_version
    ON business_config_version ((status = 'PUBLISHED'))
    WHERE status = 'PUBLISHED';

CREATE TABLE IF NOT EXISTS business_config_audit (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT REFERENCES business_config_version(id),
    actor VARCHAR(128) NOT NULL,
    action VARCHAR(64) NOT NULL,
    resource VARCHAR(128) NOT NULL,
    entity_key VARCHAR(256) NOT NULL DEFAULT '',
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_business_config_audit_version
    ON business_config_audit(version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_business_config_audit_actor
    ON business_config_audit(actor, created_at DESC);

CREATE TABLE IF NOT EXISTS business_market (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    market_code VARCHAR(8) NOT NULL,
    exchange_code VARCHAR(32) NOT NULL,
    name VARCHAR(64) NOT NULL,
    full_name VARCHAR(128) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    remark TEXT NOT NULL DEFAULT '',
    CONSTRAINT uq_business_market UNIQUE(version_id, market_code)
);

CREATE TABLE IF NOT EXISTS business_colocation (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    colo_id INTEGER NOT NULL CHECK (colo_id >= 1000),
    name VARCHAR(32) NOT NULL,
    full_name VARCHAR(256) NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_business_colocation UNIQUE(version_id, colo_id)
);

CREATE TABLE IF NOT EXISTS business_product (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    fund_id INTEGER NOT NULL CHECK (fund_id > 0),
    fund_code VARCHAR(16) NOT NULL,
    name VARCHAR(256) NOT NULL,
    full_name VARCHAR(512) NOT NULL DEFAULT '',
    allowed_security_types VARCHAR(128) NOT NULL DEFAULT '',
    allowed_directions VARCHAR(512) NOT NULL DEFAULT '',
    allowed_markets VARCHAR(64) NOT NULL DEFAULT '',
    fund_type VARCHAR(4) NOT NULL DEFAULT '',
    valuation_type CHAR(1) NOT NULL DEFAULT '1' CHECK (valuation_type IN ('1', '2', '3')),
    bond_risk_value CHAR(1) NOT NULL DEFAULT '1' CHECK (bond_risk_value IN ('1', '2')),
    long_stop_value CHAR(1) NOT NULL DEFAULT '1' CHECK (long_stop_value IN ('1', '2')),
    status CHAR(1) NOT NULL DEFAULT '1' CHECK (status IN ('1', '2', '3')),
    CONSTRAINT uq_business_product_id UNIQUE(version_id, fund_id),
    CONSTRAINT uq_business_product_code UNIQUE(version_id, fund_code)
);

CREATE TABLE IF NOT EXISTS business_project_account (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL CHECK (project_id > 0),
    name VARCHAR(128) NOT NULL,
    fund_id INTEGER NOT NULL,
    initial_balance NUMERIC(20, 4) NOT NULL CHECK (initial_balance >= 0),
    project_type CHAR(1) NOT NULL CHECK (project_type IN ('0', '1', '2', '3')),
    hedge_flags VARCHAR(16) NOT NULL DEFAULT '0' CHECK (hedge_flags IN ('0', '1', '2')),
    default_flag BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    remark VARCHAR(128) NOT NULL DEFAULT '',
    CONSTRAINT uq_business_project UNIQUE(version_id, project_id),
    CONSTRAINT fk_business_project_product FOREIGN KEY(version_id, fund_id)
        REFERENCES business_product(version_id, fund_id)
);

CREATE TABLE IF NOT EXISTS business_fund_account (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    account_id VARCHAR(32) NOT NULL,
    broker_id VARCHAR(10) NOT NULL,
    broker_name VARCHAR(128) NOT NULL DEFAULT '',
    account_type CHAR(1) NOT NULL CHECK (account_type IN ('0', '1', '2', '3')),
    initial_balance NUMERIC(20, 4) NOT NULL CHECK (initial_balance >= 0),
    colo_id INTEGER NOT NULL,
    open_date CHAR(8) NOT NULL DEFAULT '' CHECK (open_date = '' OR open_date ~ '^[0-9]{8}$'),
    status CHAR(1) NOT NULL DEFAULT '1',
    CONSTRAINT uq_business_fund_account UNIQUE(version_id, account_id),
    CONSTRAINT fk_business_account_colocation FOREIGN KEY(version_id, colo_id)
        REFERENCES business_colocation(version_id, colo_id)
);

CREATE TABLE IF NOT EXISTS business_fund_account_link (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL,
    account_id VARCHAR(32) NOT NULL,
    account_type CHAR(1) NOT NULL DEFAULT '0' CHECK (account_type IN ('0', '1', '2', '3')),
    default_flag BOOLEAN NOT NULL DEFAULT FALSE,
    external_account_id VARCHAR(32) NOT NULL DEFAULT '',
    fund_id INTEGER NOT NULL,
    CONSTRAINT uq_business_account_link UNIQUE(version_id, project_id, account_id, account_type),
    CONSTRAINT fk_business_link_project FOREIGN KEY(version_id, project_id)
        REFERENCES business_project_account(version_id, project_id),
    CONSTRAINT fk_business_link_account FOREIGN KEY(version_id, account_id)
        REFERENCES business_fund_account(version_id, account_id),
    CONSTRAINT fk_business_link_product FOREIGN KEY(version_id, fund_id)
        REFERENCES business_product(version_id, fund_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_business_default_account_link
    ON business_fund_account_link(version_id, project_id, account_type)
    WHERE default_flag;

COMMENT ON TABLE business_config_version IS '后台可编辑配置的版本；只有 PUBLISHED 版本可供交易核心消费';
COMMENT ON TABLE business_config_audit IS '后台配置变更、校验和发布审计';
COMMENT ON TABLE business_fund_account IS '柜台资金账户的配置，不存储实时资金事实';
