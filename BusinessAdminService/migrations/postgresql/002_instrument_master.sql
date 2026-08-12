-- Securities and futures configuration. Historical bars remain in the market
-- data database and are deliberately not copied into the control-plane DB.

CREATE TABLE IF NOT EXISTS business_security_master (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    market_code VARCHAR(8) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    name VARCHAR(64) NOT NULL,
    security_type VARCHAR(8) NOT NULL DEFAULT '',
    exchange_symbol VARCHAR(32) NOT NULL DEFAULT '',
    suspended BOOLEAN NOT NULL DEFAULT FALSE,
    buy_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    sell_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    cancel_allowed BOOLEAN NOT NULL DEFAULT TRUE,
    price_tick NUMERIC(18, 4) NOT NULL CHECK (price_tick > 0),
    buy_unit INTEGER NOT NULL DEFAULT 100 CHECK (buy_unit > 0),
    sell_unit INTEGER NOT NULL DEFAULT 100 CHECK (sell_unit > 0),
    max_quantity INTEGER NOT NULL DEFAULT 0 CHECK (max_quantity >= 0),
    min_quantity INTEGER NOT NULL DEFAULT 0 CHECK (min_quantity >= 0),
    CONSTRAINT uq_business_security UNIQUE(version_id, market_code, symbol),
    CONSTRAINT ck_business_security_quantity CHECK (max_quantity = 0 OR min_quantity <= max_quantity),
    CONSTRAINT fk_business_security_market FOREIGN KEY(version_id, market_code)
        REFERENCES business_market(version_id, market_code)
);

CREATE TABLE IF NOT EXISTS business_futures_product (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    market_code VARCHAR(8) NOT NULL,
    product_code VARCHAR(16) NOT NULL,
    name VARCHAR(32) NOT NULL,
    trading_unit INTEGER NOT NULL CHECK (trading_unit > 0),
    price_tick NUMERIC(18, 4) NOT NULL CHECK (price_tick > 0),
    price_limit VARCHAR(16) NOT NULL DEFAULT '',
    margin_ratio NUMERIC(7, 4) NOT NULL DEFAULT 0 CHECK (margin_ratio >= 0 AND margin_ratio <= 1),
    contract_month_rule VARCHAR(64) NOT NULL DEFAULT '',
    last_trade_day_rule VARCHAR(128) NOT NULL DEFAULT '',
    delivery_rule VARCHAR(128) NOT NULL DEFAULT '',
    CONSTRAINT uq_business_futures_product UNIQUE(version_id, market_code, product_code),
    CONSTRAINT fk_business_futures_product_market FOREIGN KEY(version_id, market_code)
        REFERENCES business_market(version_id, market_code)
);

CREATE TABLE IF NOT EXISTS business_futures_contract (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES business_config_version(id) ON DELETE CASCADE,
    market_code VARCHAR(8) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    product_code VARCHAR(16) NOT NULL,
    exchange_symbol VARCHAR(32) NOT NULL DEFAULT '',
    multiplier INTEGER NOT NULL DEFAULT 1 CHECK (multiplier > 0),
    expiry_date CHAR(8) NOT NULL DEFAULT '' CHECK (expiry_date = '' OR expiry_date ~ '^[0-9]{8}$'),
    end_trade_time CHAR(6) NOT NULL DEFAULT '' CHECK (end_trade_time = '' OR end_trade_time ~ '^[0-9]{6}$'),
    main_level CHAR(1) NOT NULL DEFAULT '',
    CONSTRAINT uq_business_futures_contract UNIQUE(version_id, market_code, symbol),
    CONSTRAINT fk_business_futures_contract_product FOREIGN KEY(version_id, market_code, product_code)
        REFERENCES business_futures_product(version_id, market_code, product_code)
);

CREATE VIEW business_published_config_version AS
SELECT version, published_at
FROM business_config_version
WHERE status = 'PUBLISHED';

COMMENT ON VIEW business_published_config_version IS '交易核心轮询或受控重载时读取的当前已发布版本';
