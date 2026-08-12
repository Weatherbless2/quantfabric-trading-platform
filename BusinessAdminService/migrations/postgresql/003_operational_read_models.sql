-- This read model is intentionally separate from editable configuration.
-- The future C++ settlement/account sync writes snapshots; BusinessAdmin only
-- exposes them to operators and never offers a desktop CRUD endpoint.

CREATE TABLE IF NOT EXISTS business_asset_snapshot (
    id BIGSERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL,
    fund_id INTEGER NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    available_balance NUMERIC(20, 4) NOT NULL DEFAULT 0,
    frozen_margin NUMERIC(20, 4) NOT NULL DEFAULT 0,
    market_value NUMERIC(20, 4) NOT NULL DEFAULT 0,
    total_value NUMERIC(20, 4) NOT NULL DEFAULT 0,
    total_pnl NUMERIC(20, 4) NOT NULL DEFAULT 0,
    risk_degree NUMERIC(12, 6) NOT NULL DEFAULT 0,
    source VARCHAR(32) NOT NULL DEFAULT 'XTrader',
    CONSTRAINT uq_business_asset_snapshot UNIQUE(project_id, fund_id, as_of)
);
CREATE INDEX IF NOT EXISTS idx_business_asset_snapshot_as_of
    ON business_asset_snapshot(project_id, as_of DESC);

COMMENT ON TABLE business_asset_snapshot IS '由交易/清算同步写入的资产快照，只读展示';
