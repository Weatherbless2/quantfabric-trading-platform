"""HTTP API for QuantFabric's versioned business control plane.

The service owns operating configuration only.  It never writes order, fill,
fund or position facts from a desktop form; those are read-only snapshots that
will later be synchronized by the C++ trading core.
"""

from __future__ import annotations

import json
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Type
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import Select, create_engine, delete, desc, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .database import (
    AssetSnapshot,
    Base,
    Colocation,
    ConfigAuditEvent,
    ConfigVersion,
    FundAccount,
    FundAccountLink,
    FuturesContract,
    FuturesProduct,
    Market,
    Product,
    ProjectAccount,
    SecurityMaster,
    VersionedConfig,
)
from .schemas import (
    AssetSnapshotResponse,
    ColocationRequest,
    FundAccountLinkRequest,
    FundAccountRequest,
    FuturesContractRequest,
    FuturesProductRequest,
    MarketDataSummary,
    MarketRequest,
    Page,
    ProductRequest,
    ProjectAccountRequest,
    SecurityBuyAllowedPublishRequest,
    SecurityBuyAllowedPublishResponse,
    SecurityMasterRequest,
    SecuritySyncRequest,
    ValidationIssue,
    ValidationResponse,
    VersionCreate,
    VersionResponse,
)


UI_PATH = __import__("pathlib").Path(__file__).with_name("ui") / "index.html"


RECONCILIATION_TYPES = {
    "login", "fund", "position", "order_status", "trade", "query_complete",
    "resync_complete", "resync_error", "cancel_error",
}


def _read_reconciliation(path: str, limit: int) -> dict[str, Any]:
    """Read the append-only ATP journal as a bounded, read-only operations view."""
    journal = Path(path)
    if not journal.exists():
        return {
            "available": False,
            "source": str(journal),
            "records": [],
            "counts": {},
            "last_resync": None,
        }
    records: list[dict[str, Any]] = []
    try:
        # Reading the tail keeps the control-plane page bounded even after a
        # long-running trading day. The journal itself remains append-only.
        lines = journal.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError as exc:
        raise HTTPException(status_code=503, detail="ATP reconciliation journal unavailable") from exc
    for line in lines:
        try:
            record = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or record.get("type") not in RECONCILIATION_TYPES:
            continue
        # Credentials must never be exposed by a monitoring endpoint, even if
        # a future SDK callback adds them to its payload.
        safe = {key: value for key, value in record.items()
                if "password" not in str(key).lower() and "secret" not in str(key).lower()}
        records.append(safe)
    counts = dict(Counter(str(item.get("type", "unknown")) for item in records))
    resync = [item for item in records if item.get("type") in {"resync_complete", "resync_error"}]
    return {
        "available": True,
        "source": str(journal),
        "records": list(reversed(records)),
        "counts": counts,
        "last_resync": resync[-1] if resync else None,
    }


@dataclass(frozen=True)
class ResourceDefinition:
    name: str
    model: Type[VersionedConfig]
    schema: Type[BaseModel]
    columns: tuple[str, ...]
    key_columns: tuple[str, ...]

    def key_from_payload(self, payload: dict[str, Any]) -> str:
        return ":".join(str(payload[column]) for column in self.key_columns)

    def parse_key(self, value: str) -> tuple[str, ...]:
        result = tuple(value.split(":"))
        if len(result) != len(self.key_columns) or any(not part for part in result):
            raise HTTPException(status_code=400, detail=f"invalid key for {self.name}")
        return result


RESOURCES: dict[str, ResourceDefinition] = {
    "markets": ResourceDefinition("markets", Market, MarketRequest,
                                  ("market_code", "exchange_code", "name", "full_name", "enabled", "remark"),
                                  ("market_code",)),
    "colocations": ResourceDefinition("colocations", Colocation, ColocationRequest,
                                      ("colo_id", "name", "full_name", "enabled"), ("colo_id",)),
    "products": ResourceDefinition("products", Product, ProductRequest,
                                    ("fund_id", "fund_code", "name", "full_name", "allowed_security_types",
                                     "allowed_directions", "allowed_markets", "fund_type", "valuation_type",
                                     "bond_risk_value", "long_stop_value", "status"), ("fund_id",)),
    "projects": ResourceDefinition("projects", ProjectAccount, ProjectAccountRequest,
                                    ("project_id", "name", "fund_id", "initial_balance", "project_type",
                                     "hedge_flags", "default_flag", "enabled", "remark"), ("project_id",)),
    "accounts": ResourceDefinition("accounts", FundAccount, FundAccountRequest,
                                    ("account_id", "broker_id", "broker_name", "account_type", "initial_balance",
                                     "colo_id", "open_date", "status"), ("account_id",)),
    "account-links": ResourceDefinition("account-links", FundAccountLink, FundAccountLinkRequest,
                                         ("project_id", "account_id", "account_type", "default_flag",
                                          "external_account_id", "fund_id"),
                                         ("project_id", "account_id", "account_type")),
    "securities": ResourceDefinition("securities", SecurityMaster, SecurityMasterRequest,
                                      ("market_code", "symbol", "name", "security_type", "exchange_symbol",
                                       "suspended", "buy_allowed", "sell_allowed", "cancel_allowed", "price_tick",
                                       "buy_unit", "sell_unit", "max_quantity", "min_quantity"),
                                      ("market_code", "symbol")),
    "futures-products": ResourceDefinition("futures-products", FuturesProduct, FuturesProductRequest,
                                             ("market_code", "product_code", "name", "trading_unit", "price_tick",
                                              "price_limit", "margin_ratio", "contract_month_rule",
                                              "last_trade_day_rule", "delivery_rule"),
                                             ("market_code", "product_code")),
    "futures-contracts": ResourceDefinition("futures-contracts", FuturesContract, FuturesContractRequest,
                                              ("market_code", "symbol", "product_code", "exchange_symbol",
                                               "multiplier", "expiry_date", "end_trade_time", "main_level"),
                                              ("market_code", "symbol")),
}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _json_detail(value: Any) -> Any:
    """Preserve audit values while making Decimal and datetime JSON-safe."""
    if isinstance(value, (Decimal, datetime)):
        return _json_value(value)
    if isinstance(value, dict):
        return {str(key): _json_detail(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_detail(item) for item in value]
    return value


def _to_dict(item: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    return {column: _json_value(getattr(item, column)) for column in columns}


def _version_response(item: ConfigVersion) -> VersionResponse:
    return VersionResponse(version=item.version, status=item.status, description=item.description,
                           created_by=item.created_by, created_at=item.created_at,
                           published_by=item.published_by, published_at=item.published_at,
                           source_version=item.source_version.version if item.source_version else None)


def _runtime_policy(db: Session, version: ConfigVersion) -> str:
    """Render the narrow, verified contract consumed by the C++ core.

    The trading path needs deterministic eligibility rules, not the complete
    administration record.  A tab-delimited contract keeps the C++ runtime
    independent from the configuration database and from a JSON parser while
    remaining easy to validate before a controlled reload is accepted.
    """
    version_id = version.id
    lines = ["QF_RUNTIME_POLICY\t1", f"VERSION\t{version.version}"]
    markets = db.scalars(select(Market).where(Market.version_id == version_id)
                         .order_by(Market.market_code)).all()
    for row in markets:
        lines.append(f"MARKET\t{row.market_code}\t{row.exchange_code}\t{int(row.enabled)}")
    products = db.scalars(select(Product).where(Product.version_id == version_id)
                          .order_by(Product.fund_id)).all()
    for row in products:
        lines.append(f"PRODUCT\t{row.fund_id}\t{row.fund_code}\t{row.status}\t{row.allowed_markets}")
    projects = db.scalars(select(ProjectAccount).where(ProjectAccount.version_id == version_id)
                          .order_by(ProjectAccount.project_id)).all()
    for row in projects:
        lines.append(f"PROJECT\t{row.project_id}\t{row.fund_id}\t{int(row.enabled)}")
    accounts = db.scalars(select(FundAccount).where(FundAccount.version_id == version_id)
                          .order_by(FundAccount.account_id)).all()
    for row in accounts:
        lines.append(f"ACCOUNT\t{row.account_id}\t{row.account_type}\t{row.status}")
    links = db.scalars(select(FundAccountLink).where(FundAccountLink.version_id == version_id)
                       .order_by(FundAccountLink.project_id, FundAccountLink.account_id,
                                 FundAccountLink.account_type)).all()
    for row in links:
        lines.append(f"LINK\t{row.project_id}\t{row.account_id}\t{row.account_type}\t"
                     f"{int(row.default_flag)}\t{row.fund_id}")
    securities = db.scalars(select(SecurityMaster).where(SecurityMaster.version_id == version_id)
                            .order_by(SecurityMaster.market_code, SecurityMaster.symbol)).all()
    for row in securities:
        lines.append(
            f"SECURITY\t{row.market_code}\t{row.symbol}\t{int(row.suspended)}\t"
            f"{int(row.buy_allowed)}\t{int(row.sell_allowed)}\t{int(row.cancel_allowed)}\t"
            f"{row.price_tick}\t{row.buy_unit}\t{row.sell_unit}\t"
            f"{row.max_quantity}\t{row.min_quantity}"
        )
    return "\n".join(lines) + "\n"


class AuthorizationClient:
    """Small server-to-server Casbin client; browser clients never see its key."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def request_session(self, username: str, password: str) -> dict[str, Any]:
        return self._request("/v1/sessions/development", {"username": username, "password": password}, False)

    def authorize(self, session_id: str, action: str, resource: str = "business/config") -> str:
        payload = self._request("/v1/internal/authorize", {
            "session_id": session_id,
            "domain": self.settings.domain,
            "resource": resource,
            "action": action,
        }, True)
        if not payload.get("allowed"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=str(payload.get("reason") or "business permission denied"))
        return str(payload.get("actor") or "unknown")

    def _request(self, path: str, payload: dict[str, Any], internal: bool) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if internal:
            headers["X-QF-Internal-Key"] = self.settings.auth_internal_key
        request = Request(self.settings.auth_url + path, data=json.dumps(payload).encode("utf-8"),
                          headers=headers, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HTTPException(status_code=exc.code, detail=detail) from exc
        except (URLError, OSError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="authorization service unavailable") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=503, detail="authorization service returned invalid data")
        return data


class BusinessService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = create_engine(settings.database_url, future=True)
        # SQLite is the disposable local-preview database. PostgreSQL schema is
        # deliberately created only by the reviewed SQL migrations so a missing
        # constraint cannot be hidden by SQLAlchemy's create_all convenience.
        if self.engine.dialect.name == "sqlite":
            Base.metadata.create_all(self.engine)
        elif not inspect(self.engine).has_table(ConfigVersion.__tablename__):
            raise RuntimeError(
                "BusinessAdminService PostgreSQL schema is missing; apply "
                "BusinessAdminService/migrations/postgresql/*.sql first"
            )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def audit(self, db: Session, version: int | None, actor: str, action: str,
              resource: str, entity_key: str = "", detail: dict | None = None) -> None:
        db.add(ConfigAuditEvent(version_id=self._version_id(db, version), actor=actor, action=action,
                                resource=resource, entity_key=entity_key, detail=_json_detail(detail or {})))

    @staticmethod
    def _version_id(db: Session, version: int | None) -> int | None:
        if version is None:
            return None
        item = db.scalar(select(ConfigVersion).where(ConfigVersion.version == version))
        return item.id if item else None

    @staticmethod
    def get_version(db: Session, version: int) -> ConfigVersion:
        item = db.scalar(select(ConfigVersion).where(ConfigVersion.version == version))
        if not item:
            raise HTTPException(status_code=404, detail="configuration version not found")
        return item

    def current_version(self, db: Session) -> ConfigVersion:
        item = db.scalar(select(ConfigVersion).where(ConfigVersion.status == "PUBLISHED")
                         .order_by(desc(ConfigVersion.version)))
        if not item:
            raise HTTPException(status_code=404, detail="no published configuration version")
        return item

    def ensure_draft(self, db: Session, version: int) -> ConfigVersion:
        item = self.get_version(db, version)
        if item.status != "DRAFT":
            raise HTTPException(status_code=409, detail="only draft versions can be edited")
        return item

    def ensure_validated(self, db: Session, version: int) -> ConfigVersion:
        """Publishing is deliberately separate from validating a draft."""
        item = self.get_version(db, version)
        if item.status != "VALIDATED":
            raise HTTPException(status_code=409,
                                detail="configuration must be validated before publishing")
        return item

    def create_version(self, db: Session, request: VersionCreate, actor: str) -> ConfigVersion:
        source: ConfigVersion | None = None
        if request.source_version is not None:
            source = self.get_version(db, request.source_version)
            if source.status not in {"PUBLISHED", "RETIRED"}:
                raise HTTPException(status_code=409,
                                    detail="a draft may only copy a published or retired version")
        else:
            source = db.scalar(select(ConfigVersion).where(ConfigVersion.status == "PUBLISHED")
                               .order_by(desc(ConfigVersion.version)))
        next_version = (db.scalar(select(func.max(ConfigVersion.version))) or 0) + 1
        item = ConfigVersion(version=next_version, status="DRAFT", description=request.description,
                             created_by=actor, source_version_id=source.id if source else None)
        db.add(item)
        db.flush()
        if source:
            self.copy_version(db, source.id, item.id)
        self.audit(db, item.version, actor, "business:write", "config-version", str(item.version),
                   {"source_version": source.version if source else None})
        return item

    @staticmethod
    def copy_version(db: Session, source_id: int, target_id: int) -> None:
        for definition in RESOURCES.values():
            for row in db.scalars(select(definition.model).where(definition.model.version_id == source_id)):
                values = {column.name: getattr(row, column.name)
                          for column in definition.model.__table__.columns
                          if column.name not in {"id", "version_id"}}
                db.add(definition.model(version_id=target_id, **values))

    def list_resource(self, db: Session, definition: ResourceDefinition, version: int,
                      query: str, offset: int, limit: int) -> Page:
        self.get_version(db, version)
        statement: Select = select(definition.model).where(definition.model.version_id == self._version_id(db, version))
        if query:
            lowered = f"%{query.lower()}%"
            columns = [getattr(definition.model, column) for column in definition.columns
                       if isinstance(definition.model.__table__.columns[column].type, (String, Text))]
            if columns:
                from sqlalchemy import or_
                statement = statement.where(or_(*(func.lower(column).like(lowered) for column in columns)))
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.scalars(statement.order_by(*[getattr(definition.model, key) for key in definition.key_columns])
                          .offset(offset).limit(limit)).all()
        return Page(items=[{"key": definition.key_from_payload(_to_dict(row, definition.columns)),
                            **_to_dict(row, definition.columns)} for row in rows],
                    total=total, offset=offset, limit=limit)

    def upsert_resource(self, db: Session, definition: ResourceDefinition, version: int,
                        key: str, raw_payload: dict[str, Any], actor: str) -> dict[str, Any]:
        version_row = self.ensure_draft(db, version)
        try:
            payload = definition.schema.model_validate(raw_payload).model_dump()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        if definition.key_from_payload(payload) != key:
            raise HTTPException(status_code=400, detail="path key and payload key differ")
        filters = [definition.model.version_id == version_row.id]
        filters.extend(getattr(definition.model, column) == payload[column] for column in definition.key_columns)
        row = db.scalar(select(definition.model).where(*filters))
        action = "business:create"
        if row is None:
            row = definition.model(version_id=version_row.id, **payload)
            db.add(row)
        else:
            action = "business:update"
            for column, value in payload.items():
                setattr(row, column, value)
        version_row.status = "DRAFT"
        self.audit(db, version, actor, action, definition.name, key, payload)
        db.flush()
        return {"key": key, **_to_dict(row, definition.columns)}

    def delete_resource(self, db: Session, definition: ResourceDefinition, version: int,
                        key: str, actor: str) -> None:
        version_row = self.ensure_draft(db, version)
        key_values = definition.parse_key(key)
        filters = [definition.model.version_id == version_row.id]
        filters.extend(getattr(definition.model, column) == value
                       for column, value in zip(definition.key_columns, key_values, strict=True))
        row = db.scalar(select(definition.model).where(*filters))
        if row is None:
            raise HTTPException(status_code=404, detail="configuration item not found")
        db.delete(row)
        version_row.status = "DRAFT"
        self.audit(db, version, actor, "business:delete", definition.name, key)

    def replace_securities(self, db: Session, version: int,
                           request: SecuritySyncRequest, actor: str) -> dict[str, int]:
        """Atomically replace the stock rules of a draft configuration version.

        A full source snapshot is safer than a sequence of thousands of HTTP
        upserts: either every source symbol is published together, or the
        previous draft contents remain intact after a validation failure.
        """
        version_row = self.ensure_draft(db, version)
        definition = RESOURCES["securities"]
        rows: list[SecurityMaster] = []
        keys: set[tuple[str, str]] = set()
        for payload in request.securities:
            data = payload.model_dump()
            key = (data["market_code"], data["symbol"])
            if key in keys:
                raise HTTPException(status_code=422,
                                    detail=f"duplicate security in synchronization input: {key[0]}:{key[1]}")
            keys.add(key)
            rows.append(SecurityMaster(version_id=version_row.id, **data))
        previous = db.scalar(select(func.count()).select_from(SecurityMaster).where(
            SecurityMaster.version_id == version_row.id)) or 0
        db.execute(delete(SecurityMaster).where(SecurityMaster.version_id == version_row.id))
        db.add_all(rows)
        version_row.status = "DRAFT"
        self.audit(db, version, actor, "business:sync", definition.name, "*", {
            "source": request.source,
            "replaced": int(previous),
            "inserted": len(rows),
        })
        return {"replaced": int(previous), "inserted": len(rows)}

    def validate_version(self, db: Session, version: int, actor: str | None = None) -> ValidationResponse:
        item = self.get_version(db, version)
        if item.status not in {"DRAFT", "VALIDATED"}:
            raise HTTPException(status_code=409,
                                detail="only draft or validated versions can be checked")
        issues = self.validation_issues(db, item)
        if item.status == "DRAFT" and not any(issue.level == "ERROR" for issue in issues):
            item.status = "VALIDATED"
        if actor:
            self.audit(db, version, actor, "business:validate", "config-version", str(version),
                       {"issue_count": len(issues)})
        return ValidationResponse(version=version, valid=not any(issue.level == "ERROR" for issue in issues), issues=issues)

    def publish_security_buy_allowed(self, db: Session, market_code: str, symbol: str,
                                     request: SecurityBuyAllowedPublishRequest,
                                     actor: str) -> SecurityBuyAllowedPublishResponse:
        """Create, validate and publish one auditable buy-permission change."""
        source = self.current_version(db)
        key = f"{market_code}:{symbol}"
        action = "启用" if request.buy_allowed else "关闭"
        draft = self.create_version(db, VersionCreate(
            description=f"快捷{action}买入 {key}",
            source_version=source.version,
        ), actor)
        security = db.scalar(select(SecurityMaster).where(
            SecurityMaster.version_id == draft.id,
            SecurityMaster.market_code == market_code,
            SecurityMaster.symbol == symbol,
        ))
        if security is None:
            raise HTTPException(status_code=404, detail="security is unavailable in published configuration")
        previous = security.buy_allowed
        security.buy_allowed = request.buy_allowed
        self.audit(db, draft.version, actor, "business:quick-publish", "securities", key, {
            "source_version": source.version,
            "buy_allowed_before": previous,
            "buy_allowed_after": request.buy_allowed,
            "reason": request.reason,
        })
        validation = self.validate_version(db, draft.version, actor)
        if not validation.valid:
            raise HTTPException(status_code=409, detail={
                "message": "configuration validation failed",
                "issues": [issue.model_dump() for issue in validation.issues],
            })
        source.status = "RETIRED"
        draft.status = "PUBLISHED"
        draft.published_by = actor
        draft.published_at = datetime.now().astimezone()
        self.audit(db, draft.version, actor, "business:publish", "config-version", str(draft.version), {
            "mode": "quick-security-buy-allowed",
            "source_version": source.version,
        })
        return SecurityBuyAllowedPublishResponse(
            version=draft.version,
            source_version=source.version,
            market_code=market_code,
            symbol=symbol,
            buy_allowed=security.buy_allowed,
        )

    def validation_issues(self, db: Session, version: ConfigVersion) -> list[ValidationIssue]:
        version_id = version.id
        issues: list[ValidationIssue] = []
        markets = {row.market_code for row in db.scalars(select(Market).where(Market.version_id == version_id))}
        products = {row.fund_id: row for row in db.scalars(select(Product).where(Product.version_id == version_id))}
        colocations = {row.colo_id for row in db.scalars(select(Colocation).where(Colocation.version_id == version_id))}
        projects = {row.project_id: row for row in db.scalars(select(ProjectAccount).where(ProjectAccount.version_id == version_id))}
        accounts = {row.account_id for row in db.scalars(select(FundAccount).where(FundAccount.version_id == version_id))}
        links = db.scalars(select(FundAccountLink).where(FundAccountLink.version_id == version_id)).all()
        securities = db.scalars(select(SecurityMaster).where(SecurityMaster.version_id == version_id)).all()
        futures_products = {(row.market_code, row.product_code)
                            for row in db.scalars(select(FuturesProduct).where(FuturesProduct.version_id == version_id))}
        futures_contracts = db.scalars(select(FuturesContract).where(FuturesContract.version_id == version_id)).all()

        if not markets:
            issues.append(ValidationIssue(level="ERROR", resource="markets", entity_key="*", message="未配置市场主数据"))
        elif not any(row.enabled for row in db.scalars(select(Market).where(Market.version_id == version_id))):
            issues.append(ValidationIssue(level="ERROR", resource="markets", entity_key="*", message="没有启用的市场主数据"))
        for product in products.values():
            for market in filter(None, (part.strip() for part in product.allowed_markets.split(","))):
                if market not in markets:
                    issues.append(ValidationIssue(level="ERROR", resource="products", entity_key=str(product.fund_id),
                                                  message=f"允许市场 {market} 不存在"))
        for project in projects.values():
            if project.fund_id not in products:
                issues.append(ValidationIssue(level="ERROR", resource="projects", entity_key=str(project.project_id),
                                              message=f"产品 {project.fund_id} 不存在"))
        for account in db.scalars(select(FundAccount).where(FundAccount.version_id == version_id)):
            if account.colo_id not in colocations:
                issues.append(ValidationIssue(level="ERROR", resource="accounts", entity_key=account.account_id,
                                              message=f"机房 {account.colo_id} 不存在"))
        default_links: set[tuple[int, str]] = set()
        linked_projects: set[int] = set()
        for link in links:
            key = f"{link.project_id}:{link.account_id}:{link.account_type}"
            project = projects.get(link.project_id)
            if not project:
                issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                              message=f"资产单元 {link.project_id} 不存在"))
            elif project.fund_id != link.fund_id:
                issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                              message="关联产品与资产单元产品不一致"))
            if link.fund_id not in products:
                issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                              message=f"产品 {link.fund_id} 不存在"))
            if link.account_id not in accounts:
                issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                              message=f"资金账户 {link.account_id} 不存在"))
            else:
                account = db.scalar(select(FundAccount).where(
                    FundAccount.version_id == version_id,
                    FundAccount.account_id == link.account_id,
                ))
                if account and account.account_type != link.account_type:
                    issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                                  message="关联账户类型与资金账户类型不一致"))
            if link.default_flag:
                default_key = (link.project_id, link.account_type)
                if default_key in default_links:
                    issues.append(ValidationIssue(level="ERROR", resource="account-links", entity_key=key,
                                                  message="同一资产单元和账户类型只能有一个默认账户"))
                default_links.add(default_key)
                linked_projects.add(link.project_id)
        for project in projects.values():
            if project.enabled and project.project_id not in linked_projects:
                issues.append(ValidationIssue(level="ERROR", resource="projects", entity_key=str(project.project_id),
                                              message="启用的资产单元必须至少关联一个默认资金账户"))
        for security in securities:
            if security.market_code not in markets:
                issues.append(ValidationIssue(level="ERROR", resource="securities",
                                              entity_key=f"{security.market_code}:{security.symbol}",
                                              message=f"市场 {security.market_code} 不存在"))
            if security.min_quantity and security.max_quantity and security.min_quantity > security.max_quantity:
                issues.append(ValidationIssue(level="ERROR", resource="securities",
                                              entity_key=f"{security.market_code}:{security.symbol}",
                                              message="最小数量不能大于最大数量"))
        for contract in futures_contracts:
            key = f"{contract.market_code}:{contract.symbol}"
            if contract.market_code not in markets:
                issues.append(ValidationIssue(level="ERROR", resource="futures-contracts", entity_key=key,
                                              message=f"市场 {contract.market_code} 不存在"))
            if (contract.market_code, contract.product_code) not in futures_products:
                issues.append(ValidationIssue(level="ERROR", resource="futures-contracts", entity_key=key,
                                              message=f"期货品种 {contract.product_code} 不存在"))
        for market_code, product_code in futures_products:
            if market_code not in markets:
                issues.append(ValidationIssue(level="ERROR", resource="futures-products",
                                              entity_key=f"{market_code}:{product_code}",
                                              message=f"市场 {market_code} 不存在"))
        return issues


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    service = BusinessService(settings)
    auth = AuthorizationClient(settings)
    app = FastAPI(title="QuantFabric BusinessAdminService", version="0.1.0")

    def require(session_id: str, action: str, resource: str = "business/config") -> str:
        return auth.authorize(session_id, action, resource)

    def db_session() -> Session:
        return service.session_factory()

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(UI_PATH)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok", "database": settings.database_url.split(":", 1)[0]}

    @app.post("/v1/sessions/development")
    def development_login(request: dict[str, str]) -> dict[str, Any]:
        username = str(request.get("username", ""))
        password = str(request.get("password", ""))
        if not username or not password:
            raise HTTPException(status_code=422, detail="username and password are required")
        return auth.request_session(username, password)

    @app.get("/v1/config/versions", response_model=list[VersionResponse])
    def list_versions(session_id: str = Header(alias="X-QF-Session-ID")) -> list[VersionResponse]:
        require(session_id, "business:read")
        with db_session() as db:
            return [_version_response(item) for item in db.scalars(select(ConfigVersion)
                    .order_by(desc(ConfigVersion.version))).all()]

    @app.post("/v1/config/versions", response_model=VersionResponse, status_code=status.HTTP_201_CREATED)
    def create_version(request: VersionCreate, session_id: str = Header(alias="X-QF-Session-ID")) -> VersionResponse:
        actor = require(session_id, "business:write")
        with service.session_factory.begin() as db:
            return _version_response(service.create_version(db, request, actor))

    @app.get("/v1/config/versions/{version}/validate", response_model=ValidationResponse)
    def validate_version(version: int, session_id: str = Header(alias="X-QF-Session-ID")) -> ValidationResponse:
        actor = require(session_id, "business:publish")
        with service.session_factory.begin() as db:
            return service.validate_version(db, version, actor)

    @app.post("/v1/config/versions/{version}/publish", response_model=VersionResponse)
    def publish_version(version: int, session_id: str = Header(alias="X-QF-Session-ID")) -> VersionResponse:
        actor = require(session_id, "business:publish")
        with service.session_factory.begin() as db:
            item = service.ensure_validated(db, version)
            result = service.validate_version(db, version, actor)
            if not result.valid:
                raise HTTPException(status_code=409, detail={"message": "configuration validation failed",
                                                              "issues": [issue.model_dump() for issue in result.issues]})
            current = db.scalars(select(ConfigVersion).where(ConfigVersion.status == "PUBLISHED")).all()
            for active in current:
                active.status = "RETIRED"
            item.status = "PUBLISHED"
            item.published_by = actor
            item.published_at = datetime.now().astimezone()
            service.audit(db, version, actor, "business:publish", "config-version", str(version))
            return _version_response(item)

    @app.post("/v1/operations/securities/{market_code}/{symbol}/buy-allowed:publish",
              response_model=SecurityBuyAllowedPublishResponse)
    def publish_security_buy_allowed(
            market_code: str, symbol: str, request: SecurityBuyAllowedPublishRequest,
            session_id: str = Header(alias="X-QF-Session-ID"),
    ) -> SecurityBuyAllowedPublishResponse:
        actor = require(session_id, "business:write", "business/securities")
        require(session_id, "business:publish")
        with service.session_factory.begin() as db:
            return service.publish_security_buy_allowed(db, market_code, symbol, request, actor)

    @app.get("/v1/config/{resource}", response_model=Page)
    def list_resource(resource: str, version: int = Query(ge=1), query: str = "",
                      offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200),
                      session_id: str = Header(alias="X-QF-Session-ID")) -> Page:
        require(session_id, "business:read", f"business/{resource}")
        definition = RESOURCES.get(resource)
        if not definition:
            raise HTTPException(status_code=404, detail="unknown configuration resource")
        with db_session() as db:
            return service.list_resource(db, definition, version, query, offset, limit)

    @app.put("/v1/config/{resource}/{key}")
    def upsert_resource(resource: str, key: str, payload: dict[str, Any], version: int = Query(ge=1),
                        session_id: str = Header(alias="X-QF-Session-ID")) -> dict[str, Any]:
        actor = require(session_id, "business:write", f"business/{resource}")
        definition = RESOURCES.get(resource)
        if not definition:
            raise HTTPException(status_code=404, detail="unknown configuration resource")
        with service.session_factory.begin() as db:
            try:
                return service.upsert_resource(db, definition, version, key, payload, actor)
            except IntegrityError as exc:
                raise HTTPException(status_code=409, detail="duplicate or invalid configuration relationship") from exc

    @app.delete("/v1/config/{resource}/{key}")
    def delete_resource(resource: str, key: str, version: int = Query(ge=1),
                        session_id: str = Header(alias="X-QF-Session-ID")) -> None:
        actor = require(session_id, "business:write", f"business/{resource}")
        definition = RESOURCES.get(resource)
        if not definition:
            raise HTTPException(status_code=404, detail="unknown configuration resource")
        with service.session_factory.begin() as db:
            service.delete_resource(db, definition, version, key, actor)

    @app.put("/v1/config/versions/{version}/securities:sync")
    def sync_securities(version: int, request: SecuritySyncRequest,
                        session_id: str = Header(alias="X-QF-Session-ID")) -> dict[str, int]:
        actor = require(session_id, "business:write", "business/securities")
        with service.session_factory.begin() as db:
            return service.replace_securities(db, version, request, actor)

    @app.get("/v1/operations/asset-snapshots", response_model=list[AssetSnapshotResponse])
    def list_asset_snapshots(project_id: int | None = Query(default=None, ge=1),
                             session_id: str = Header(alias="X-QF-Session-ID")) -> list[AssetSnapshotResponse]:
        require(session_id, "asset:read", "business/asset-snapshots")
        with db_session() as db:
            statement = select(AssetSnapshot).order_by(desc(AssetSnapshot.as_of)).limit(200)
            if project_id is not None:
                statement = statement.where(AssetSnapshot.project_id == project_id)
            return [AssetSnapshotResponse(project_id=row.project_id, fund_id=row.fund_id, as_of=row.as_of,
                    available_balance=row.available_balance, frozen_margin=row.frozen_margin,
                    market_value=row.market_value, total_value=row.total_value, total_pnl=row.total_pnl,
                    risk_degree=row.risk_degree, source=row.source) for row in db.scalars(statement)]

    @app.get("/v1/operations/reconciliation")
    def reconciliation(
            limit: int = Query(default=200, ge=1, le=2000),
            session_id: str = Header(alias="X-QF-Session-ID"),
    ) -> dict[str, Any]:
        require(session_id, "business:read", "business/reconciliation")
        return _read_reconciliation(settings.reconciliation_path, limit)

    @app.get("/v1/market-data/summary", response_model=MarketDataSummary)
    def market_data_summary(session_id: str = Header(alias="X-QF-Session-ID")) -> MarketDataSummary:
        require(session_id, "business:read", "business/market-data")
        # The history service owns the data-source adapter and its credentials.
        # The control plane consumes only its internal aggregate status API.
        request = Request(
            f"{settings.history_service_url}/v1/internal/summary",
            headers={"X-QF-Internal-Key": settings.auth_internal_key},
            method="GET",
        )
        try:
            with urlopen(request, timeout=3) as response:
                summary = json.loads(response.read().decode("utf-8"))
            return MarketDataSummary(
                configured=True,
                table=str(summary["source"]),
                rows=int(summary["rows"]),
                first_time=summary.get("first_time"),
                last_time=summary.get("last_time"),
                detail=f"{summary.get('backend', 'history')} 只读历史数据源",
            )
        except (HTTPError, URLError, OSError, KeyError, TypeError, ValueError):
            pass
        table = f"{settings.market_data_schema}.{settings.market_data_table}"
        if not settings.market_data_url:
            return MarketDataSummary(configured=False, table=table,
                                     detail="历史行情服务当前不可用，未配置兼容数据库回退。")
        try:
            import psycopg
            query = f"SELECT count(*), min(trdtime), max(trdtime) FROM {table}"
            with psycopg.connect(settings.market_data_url, connect_timeout=3) as connection:
                count, first_time, last_time = connection.execute(query).fetchone()
            return MarketDataSummary(configured=True, table=table, rows=int(count),
                                     first_time=first_time, last_time=last_time)
        except Exception:
            return MarketDataSummary(configured=True, table=table,
                                     detail="行情数据库当前不可用或调用方未获网络访问权限。")

    @app.get("/v1/audit")
    def audit_log(version: int | None = Query(default=None, ge=1), offset: int = Query(default=0, ge=0),
                  limit: int = Query(default=100, ge=1, le=200),
                  session_id: str = Header(alias="X-QF-Session-ID")) -> Page:
        require(session_id, "business:read", "business/audit")
        with db_session() as db:
            statement = select(ConfigAuditEvent).order_by(desc(ConfigAuditEvent.created_at))
            if version is not None:
                version_id = service._version_id(db, version)
                statement = statement.where(ConfigAuditEvent.version_id == version_id)
            total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
            rows = db.scalars(statement.offset(offset).limit(limit)).all()
            return Page(items=[{"created_at": _json_value(row.created_at), "actor": row.actor,
                                "action": row.action, "resource": row.resource, "entity_key": row.entity_key,
                                "detail": row.detail} for row in rows], total=total, offset=offset, limit=limit)

    @app.get("/v1/internal/config/published")
    def published_config(x_qf_internal_key: str | None = Header(default=None)) -> dict[str, Any]:
        if not x_qf_internal_key or not secrets.compare_digest(x_qf_internal_key, settings.auth_internal_key):
            raise HTTPException(status_code=401, detail="invalid internal service key")
        with db_session() as db:
            version = service.current_version(db)
            return {"version": version.version, "published_at": _json_value(version.published_at),
                    "resources": {name: [_to_dict(item, definition.columns) for item in db.scalars(
                        select(definition.model).where(definition.model.version_id == version.id))]
                                  for name, definition in RESOURCES.items()}}

    @app.get("/v1/internal/config/published/runtime-policy", response_class=PlainTextResponse)
    def published_runtime_policy(x_qf_internal_key: str | None = Header(default=None)) -> str:
        """Return the only configuration form accepted by the C++ runtime."""
        if not x_qf_internal_key or not secrets.compare_digest(x_qf_internal_key, settings.auth_internal_key):
            raise HTTPException(status_code=401, detail="invalid internal service key")
        with db_session() as db:
            return _runtime_policy(db, service.current_version(db))

    return app
