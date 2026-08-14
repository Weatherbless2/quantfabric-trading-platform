"""API contracts for versioned operating configuration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


ConfigStatus = Literal["DRAFT", "VALIDATED", "PUBLISHED", "RETIRED"]


class VersionCreate(BaseModel):
    description: str = Field(default="", max_length=256)
    source_version: int | None = Field(default=None, ge=1)


class VersionResponse(BaseModel):
    version: int
    status: ConfigStatus
    description: str
    created_by: str
    created_at: datetime | None
    published_by: str | None = None
    published_at: datetime | None = None
    source_version: int | None = None


class ValidationIssue(BaseModel):
    level: Literal["ERROR", "WARNING"]
    resource: str
    entity_key: str
    message: str


class ValidationResponse(BaseModel):
    version: int
    valid: bool
    issues: list[ValidationIssue]


class MarketRequest(BaseModel):
    market_code: str = Field(min_length=1, max_length=8, pattern=r"[A-Za-z0-9_-]+")
    exchange_code: str = Field(min_length=1, max_length=32, pattern=r"[A-Za-z0-9_-]+")
    name: str = Field(min_length=1, max_length=64)
    full_name: str = Field(default="", max_length=128)
    enabled: bool = True
    remark: str = Field(default="", max_length=2048)


class ColocationRequest(BaseModel):
    colo_id: int = Field(ge=1000, le=999999)
    name: str = Field(min_length=1, max_length=32)
    full_name: str = Field(default="", max_length=256)
    enabled: bool = True


class ProductRequest(BaseModel):
    fund_id: int = Field(ge=1)
    fund_code: str = Field(min_length=1, max_length=16, pattern=r"[A-Za-z0-9_-]+")
    name: str = Field(min_length=1, max_length=256)
    full_name: str = Field(default="", max_length=512)
    allowed_security_types: str = Field(default="", max_length=128)
    allowed_directions: str = Field(default="", max_length=512)
    allowed_markets: str = Field(default="", max_length=64, pattern=r"[A-Za-z0-9,_-]*")
    fund_type: str = Field(default="", max_length=4)
    valuation_type: Literal["1", "2", "3"] = "1"
    bond_risk_value: Literal["1", "2"] = "1"
    long_stop_value: Literal["1", "2"] = "1"
    status: Literal["1", "2", "3"] = "1"


class ProjectAccountRequest(BaseModel):
    project_id: int = Field(ge=1, le=999999)
    name: str = Field(min_length=1, max_length=128)
    fund_id: int = Field(ge=1)
    initial_balance: Decimal = Field(ge=0, max_digits=20, decimal_places=4)
    project_type: Literal["0", "1", "2", "3"]
    hedge_flags: Literal["0", "1", "2"] = "0"
    default_flag: bool = False
    enabled: bool = True
    remark: str = Field(default="", max_length=128)


class FundAccountRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=32, pattern=r"[A-Za-z0-9_-]+")
    broker_id: str = Field(min_length=1, max_length=10, pattern=r"[A-Za-z0-9_-]+")
    broker_name: str = Field(default="", max_length=128)
    account_type: Literal["0", "1", "2", "3"]
    initial_balance: Decimal = Field(ge=0, max_digits=20, decimal_places=4)
    colo_id: int = Field(ge=1000)
    open_date: str = Field(default="", pattern=r"^$|\d{8}")
    status: str = Field(default="1", max_length=1)


class FundAccountLinkRequest(BaseModel):
    project_id: int = Field(ge=1)
    account_id: str = Field(min_length=1, max_length=32)
    account_type: Literal["0", "1", "2", "3"] = "0"
    default_flag: bool = False
    external_account_id: str = Field(default="", max_length=32)
    fund_id: int = Field(ge=1)


class SecurityMasterRequest(BaseModel):
    market_code: str = Field(min_length=1, max_length=8, pattern=r"[^:]+")
    symbol: str = Field(min_length=1, max_length=32, pattern=r"[^:]+")
    name: str = Field(min_length=1, max_length=64)
    security_type: str = Field(default="", max_length=8, pattern=r"[A-Za-z0-9_-]*")
    exchange_symbol: str = Field(default="", max_length=32, pattern=r"[A-Za-z0-9_-]*")
    suspended: bool = False
    buy_allowed: bool = True
    sell_allowed: bool = True
    cancel_allowed: bool = True
    price_tick: Decimal = Field(default=Decimal("0.01"), gt=0, max_digits=18, decimal_places=4)
    buy_unit: int = Field(default=100, ge=1)
    sell_unit: int = Field(default=100, ge=1)
    max_quantity: int = Field(default=0, ge=0)
    min_quantity: int = Field(default=0, ge=0)


class SecuritySyncRequest(BaseModel):
    """A complete, validated replacement for one draft version's stock scope."""

    source: str = Field(default="", max_length=128)
    securities: list[SecurityMasterRequest] = Field(min_length=1, max_length=20_000)


class SecurityBuyAllowedPublishRequest(BaseModel):
    """The single security change supported by the fast operational workflow."""

    buy_allowed: bool
    reason: str = Field(default="", max_length=256)


class SecurityBuyAllowedPublishResponse(BaseModel):
    version: int
    source_version: int
    market_code: str
    symbol: str
    buy_allowed: bool


class FuturesProductRequest(BaseModel):
    market_code: str = Field(min_length=1, max_length=8, pattern=r"[^:]+")
    product_code: str = Field(min_length=1, max_length=16, pattern=r"[^:]+")
    name: str = Field(min_length=1, max_length=32)
    trading_unit: int = Field(ge=1)
    price_tick: Decimal = Field(gt=0, max_digits=18, decimal_places=4)
    price_limit: str = Field(default="", max_length=16)
    margin_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=1, max_digits=7, decimal_places=4)
    contract_month_rule: str = Field(default="", max_length=64)
    last_trade_day_rule: str = Field(default="", max_length=128)
    delivery_rule: str = Field(default="", max_length=128)


class FuturesContractRequest(BaseModel):
    market_code: str = Field(min_length=1, max_length=8, pattern=r"[^:]+")
    symbol: str = Field(min_length=1, max_length=32, pattern=r"[^:]+")
    product_code: str = Field(min_length=1, max_length=16, pattern=r"[^:]+")
    exchange_symbol: str = Field(default="", max_length=32)
    multiplier: int = Field(default=1, ge=1)
    expiry_date: str = Field(default="", pattern=r"^$|\d{8}")
    end_trade_time: str = Field(default="", pattern=r"^$|\d{6}")
    main_level: str = Field(default="", max_length=1)


class AssetSnapshotResponse(BaseModel):
    project_id: int
    fund_id: int
    as_of: datetime
    available_balance: Decimal
    frozen_margin: Decimal
    market_value: Decimal
    total_value: Decimal
    total_pnl: Decimal
    risk_degree: Decimal
    source: str


class Page(BaseModel):
    items: list[dict]
    total: int
    offset: int
    limit: int


class MarketDataSummary(BaseModel):
    configured: bool
    table: str
    rows: int | None = None
    first_time: datetime | None = None
    last_time: datetime | None = None
    detail: str = ""
