"""HTTP boundary for read-only historical strategy backtests."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, time as clock_time
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from HistoryDataService.service import HistorySource, _auth_session, _source_ready

from .engine import BacktestConfig, run_backtest


class BacktestRequest(BaseModel):
    """Public backtest contract; credentials remain inside the service."""

    symbol: str = Field(pattern=r"\d{6}")
    exchange: Literal["SSE", "SZSE"]
    start: date
    end: date
    interval: int = Field(default=5, ge=1, le=60)
    fast_window: int = Field(default=10, ge=1, le=500)
    slow_window: int = Field(default=30, ge=2, le=1000)
    capital: float = Field(default=1_000_000, gt=0)
    commission_rate: float = Field(default=0.0003, ge=0, le=0.1)
    stamp_duty_rate: float = Field(default=0.001, ge=0, le=0.1)
    slippage_bps: float = Field(default=2.0, ge=0, le=1000)


def _run_config(request: BacktestRequest) -> BacktestConfig:
    """Translate a date-based HTTP request into the engine's timestamp range."""
    if request.exchange not in {"SSE", "SZSE"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="unsupported exchange")
    if request.interval not in {1, 5, 15, 30, 60}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="unsupported interval")
    if request.end < request.start:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="end date must not be earlier than start date")
    if request.fast_window >= request.slow_window:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="fast window must be smaller than slow window")
    return BacktestConfig(
        symbol=request.symbol,
        exchange=request.exchange,
        start=datetime.combine(request.start, clock_time.min),
        end=datetime.combine(request.end, clock_time.max),
        interval=request.interval,
        fast_window=request.fast_window,
        slow_window=request.slow_window,
        capital=request.capital,
        commission_rate=request.commission_rate,
        stamp_duty_rate=request.stamp_duty_rate,
        slippage_bps=request.slippage_bps,
    )


def _result_payload(result) -> dict[str, Any]:
    """Expose only the report and trades, never source credentials or SQL."""
    return asdict(result)


def create_app(source: HistorySource | None = None) -> FastAPI:
    source = source or HistorySource.from_environment()
    app = FastAPI(title="QuantFabric BacktestService", version="0.1.0")

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "source": f"{source.clickhouse_database}.{source.table}",
        }

    @app.get("/readyz")
    def ready() -> dict[str, str]:
        try:
            _source_ready(source)
        except Exception as exc:
            raise HTTPException(status_code=503,
                                detail="backtest data source unavailable") from exc
        return {"status": "ready", "backend": source.backend}

    @app.post("/v1/backtests")
    def backtest(request: BacktestRequest,
                 session_id: str = Header(alias="X-QF-Session-ID")) -> dict[str, Any]:
        config = _run_config(request)
        # Backtesting uses the same historical-data permission as K-line
        # display. The desktop never receives ClickHouse credentials.
        _auth_session(session_id, config.symbol, config.exchange)
        try:
            return _result_payload(run_backtest(config, source))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                detail="backtest data source unavailable") from exc

    return app
