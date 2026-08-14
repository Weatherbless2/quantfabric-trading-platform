#!/usr/bin/env python3
"""Publish the current PyTdx/ClickHouse A-share intersection as stock rules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from HistoryDataService.service import HistorySource, _clickhouse_query


ROOT = Path(__file__).resolve().parents[1]
MASTER_PATH = ROOT / "runtime" / "data" / "security_master.json"
BUSINESS_URL = os.getenv("QF_BUSINESS_POLICY_URL", "http://127.0.0.1:19080").rstrip("/")
POLICY_MARKETS = {"SSE": "S", "SZSE": "Z"}


def load_environment(path: Path) -> None:
    """Read the local runtime env files without printing credentials."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key and key not in os.environ:
            os.environ[key] = value


def request(path: str, method: str = "GET", payload: dict | None = None,
            session_id: str = "") -> dict | list:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if session_id:
        headers["X-QF-Session-ID"] = session_id
    try:
        with urlopen(Request(BUSINESS_URL + path, data=body, headers=headers, method=method), timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"BusinessAdmin API {method} {path} failed: {exc.code} {detail}") from exc


def eligible_securities(source: HistorySource) -> list[dict]:
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    query = f"SELECT market, stkcode FROM {source.clickhouse_database}.{source.table} GROUP BY market, stkcode FORMAT JSONEachRow"
    history_keys = {
        (row["market"], row["stkcode"])
        for line in _clickhouse_query(source, query, {}).splitlines() if line.strip()
        for row in [json.loads(line)]
    }
    securities: list[dict] = []
    for item in master:
        exchange = str(item.get("exchange", "")).upper()
        symbol = str(item.get("ticker", "")).strip()
        if exchange not in POLICY_MARKETS or len(symbol) != 6 or not symbol.isdigit():
            continue
        history_key = (
            source.market_codes[exchange],
            source.symbol_template.format(symbol=symbol, exchange=exchange),
        )
        if history_key not in history_keys:
            continue
        securities.append({
            "market_code": POLICY_MARKETS[exchange],
            "symbol": symbol,
            "name": str(item.get("name", symbol)).strip() or symbol,
            "security_type": "stock",
            "exchange_symbol": symbol,
            "suspended": False,
            "buy_allowed": True,
            "sell_allowed": True,
            "cancel_allowed": True,
            "price_tick": "0.01",
            "buy_unit": int(item.get("lot_size", 100) or 100),
            "sell_unit": int(item.get("lot_size", 100) or 100),
            "max_quantity": 0,
            "min_quantity": 0,
        })
    if not securities:
        raise RuntimeError("no current PyTdx securities have matching ClickHouse history")
    return sorted(securities, key=lambda item: (item["market_code"], item["symbol"]))


def main() -> int:
    load_environment(ROOT / "runtime" / "config" / "AuthAdmin.env")
    load_environment(ROOT / "runtime" / "config" / "BusinessAdmin.env")
    load_environment(ROOT / "runtime" / "config" / "HistoryData.env")
    source = HistorySource.from_environment()
    if source.backend != "clickhouse":
        raise RuntimeError("security synchronization requires QF_HISTORY_BACKEND=clickhouse")
    if not MASTER_PATH.exists():
        raise RuntimeError("PyTdx security master is missing; start PyTdxBridge first")

    username = os.getenv("QF_AUTH_DEV_ADMIN_USERNAME", "admin")
    password = os.getenv("QF_AUTH_DEV_ADMIN_PASSWORD", "")
    login = request("/v1/sessions/development", "POST", {"username": username, "password": password})
    session_id = str(login["session_id"])
    versions = request("/v1/config/versions", session_id=session_id)
    published = next((item for item in versions if item.get("status") == "PUBLISHED"), None)
    if not published:
        raise RuntimeError("a published ATP business policy is required before synchronization")

    securities = eligible_securities(source)
    description = f"PyTdx current A-share and ClickHouse history intersection ({len(securities)} securities)"
    draft = next((item for item in versions if item.get("status") == "DRAFT"
                  and item.get("source_version") == published["version"]
                  and item.get("description") == description), None)
    if draft is None:
        draft = request("/v1/config/versions", "POST", {
            "description": description,
            "source_version": published["version"],
        }, session_id)
    version = int(draft["version"])
    request(f"/v1/config/versions/{version}/securities:sync", "PUT", {
        "source": "PyTdx security master intersect ClickHouse tdxdata.stkprice_1min",
        "securities": securities,
    }, session_id)
    validation = request(f"/v1/config/versions/{version}/validate", session_id=session_id)
    if not validation.get("valid"):
        raise RuntimeError(f"security synchronization validation failed: {validation.get('issues')}")
    published = request(f"/v1/config/versions/{version}/publish", "POST", session_id=session_id)
    print(json.dumps({
        "version": published["version"],
        "status": published["status"],
        "securities": len(securities),
        "source_version": draft.get("source_version"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
