"""Versioned business configuration and read-only operational snapshots.

The source SQL supplied by the trading platform is a domain dictionary, not a
safe migration.  These models preserve its meaning while adding explicit
version ownership, referential checks and auditability for a control plane.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ConfigVersion(Base):
    __tablename__ = "business_config_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    description: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_by: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_version_id: Mapped[int | None] = mapped_column(ForeignKey("business_config_version.id"))
    # A draft can be traced back to the immutable published/retired version it
    # was copied from. This is the safe rollback path: copy, validate, publish.
    source_version: Mapped["ConfigVersion | None"] = relationship(
        remote_side="ConfigVersion.id", foreign_keys=[source_version_id]
    )


class ConfigAuditEvent(Base):
    __tablename__ = "business_config_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("business_config_version.id"))
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VersionedConfig:
    """Shared shape for configuration that is only active after publishing."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("business_config_version.id"), nullable=False, index=True)


class Market(VersionedConfig, Base):
    __tablename__ = "business_market"
    __table_args__ = (UniqueConstraint("version_id", "market_code"),)

    market_code: Mapped[str] = mapped_column(String(8), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Colocation(VersionedConfig, Base):
    __tablename__ = "business_colocation"
    __table_args__ = (UniqueConstraint("version_id", "colo_id"),)

    colo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Product(VersionedConfig, Base):
    __tablename__ = "business_product"
    __table_args__ = (UniqueConstraint("version_id", "fund_id"), UniqueConstraint("version_id", "fund_code"))

    fund_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    allowed_security_types: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    allowed_directions: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    allowed_markets: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    fund_type: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    valuation_type: Mapped[str] = mapped_column(String(1), default="1", nullable=False)
    bond_risk_value: Mapped[str] = mapped_column(String(1), default="1", nullable=False)
    long_stop_value: Mapped[str] = mapped_column(String(1), default="1", nullable=False)
    status: Mapped[str] = mapped_column(String(1), default="1", nullable=False)


class ProjectAccount(VersionedConfig, Base):
    __tablename__ = "business_project_account"
    __table_args__ = (UniqueConstraint("version_id", "project_id"),)

    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    fund_id: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    project_type: Mapped[str] = mapped_column(String(1), nullable=False)
    hedge_flags: Mapped[str] = mapped_column(String(16), nullable=False, default="0")
    default_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remark: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class FundAccount(VersionedConfig, Base):
    __tablename__ = "business_fund_account"
    __table_args__ = (UniqueConstraint("version_id", "account_id"),)

    account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    broker_id: Mapped[str] = mapped_column(String(10), nullable=False)
    broker_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    account_type: Mapped[str] = mapped_column(String(1), nullable=False)
    initial_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    colo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    open_date: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(1), default="1", nullable=False)


class FundAccountLink(VersionedConfig, Base):
    __tablename__ = "business_fund_account_link"
    __table_args__ = (UniqueConstraint("version_id", "project_id", "account_id", "account_type"),)

    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[str] = mapped_column(String(32), nullable=False)
    account_type: Mapped[str] = mapped_column(String(1), nullable=False, default="0")
    default_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    fund_id: Mapped[int] = mapped_column(Integer, nullable=False)


class SecurityMaster(VersionedConfig, Base):
    __tablename__ = "business_security_master"
    __table_args__ = (UniqueConstraint("version_id", "market_code", "symbol"),)

    market_code: Mapped[str] = mapped_column(String(8), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    security_type: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    exchange_symbol: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    buy_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sell_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cancel_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_tick: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    buy_unit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    sell_unit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class FuturesProduct(VersionedConfig, Base):
    __tablename__ = "business_futures_product"
    __table_args__ = (UniqueConstraint("version_id", "market_code", "product_code"),)

    market_code: Mapped[str] = mapped_column(String(8), nullable=False)
    product_code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_unit: Mapped[int] = mapped_column(Integer, nullable=False)
    price_tick: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    price_limit: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    margin_ratio: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"), nullable=False)
    contract_month_rule: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    last_trade_day_rule: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    delivery_rule: Mapped[str] = mapped_column(String(128), default="", nullable=False)


class FuturesContract(VersionedConfig, Base):
    __tablename__ = "business_futures_contract"
    __table_args__ = (UniqueConstraint("version_id", "market_code", "symbol"),)

    market_code: Mapped[str] = mapped_column(String(8), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    product_code: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange_symbol: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    multiplier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    expiry_date: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    end_trade_time: Mapped[str] = mapped_column(String(6), default="", nullable=False)
    main_level: Mapped[str] = mapped_column(String(1), default="", nullable=False)


class AssetSnapshot(Base):
    """Read-only operational data to be written by the C++ settlement sync."""

    __tablename__ = "business_asset_snapshot"
    __table_args__ = (UniqueConstraint("project_id", "fund_id", "as_of"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_id: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), nullable=False)
    frozen_margin: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), nullable=False)
    total_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"), nullable=False)
    risk_degree: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="XTrader", nullable=False)
