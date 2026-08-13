"""Small, deterministic equity backtest runner for the QuantFabric data contract.

The runner is intentionally independent from ATP and XServer.  It consumes the
same one-minute ClickHouse source as the chart service and produces a report
that can be reviewed before a strategy is connected to the live order channel.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from HistoryDataService.service import HistorySource, _clickhouse_query


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str
    exchange: str
    start: datetime
    end: datetime
    interval: int = 5
    fast_window: int = 10
    slow_window: int = 30
    capital: float = 1_000_000.0
    lot_size: int = 100
    commission_rate: float = 0.0003
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class BacktestTrade:
    datetime: str
    side: str
    price: float
    volume: int
    turnover: float
    commission: float
    realized_pnl: float


@dataclass
class BacktestResult:
    config: dict[str, Any]
    source: str
    bars: int
    trades: list[BacktestTrade] = field(default_factory=list)
    final_equity: float = 0.0
    pnl: float = 0.0
    return_rate: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0

    def write(self, output_dir: Path) -> tuple[Path, Path]:
        """Write machine-readable summary and a reviewable trade CSV."""
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self.config['symbol']}.{self.config['exchange']}_{self.config['start'][:10]}_{self.config['end'][:10]}"
        report_path = output_dir / f"{stem}.json"
        trades_path = output_dir / f"{stem}.trades.csv"
        report_path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        with trades_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=BacktestTrade.__dataclass_fields__)
            writer.writeheader()
            writer.writerows(asdict(trade) for trade in self.trades)
        return report_path, trades_path


def _raw_bars(source: HistorySource, config: BacktestConfig) -> list[dict[str, Any]]:
    market, stock_code = source.instrument(config.symbol, config.exchange)
    query = f"""
        SELECT trdtime, open, high, low, close, vol, amt
        FROM {source.clickhouse_database}.{source.table}
        WHERE market = {{market:String}}
          AND stkcode = {{stock_code:String}}
          AND trdtime >= toDateTime({{start:String}})
          AND trdtime <= toDateTime({{end:String}})
        ORDER BY trdtime ASC
        FORMAT JSONEachRow
    """
    body = _clickhouse_query(source, query, {
        "market": market,
        "stock_code": stock_code,
        "start": config.start.strftime("%Y-%m-%d %H:%M:%S"),
        "end": config.end.strftime("%Y-%m-%d %H:%M:%S"),
    })
    rows = []
    for line in body.splitlines():
        if line.strip():
            row = json.loads(line)
            timestamp = row["trdtime"]
            row["trdtime"] = datetime.fromisoformat(timestamp.replace("Z", "+00:00")) if isinstance(timestamp, str) else timestamp
            rows.append(row)
    return rows


def _aggregate(rows: list[dict[str, Any]], interval: int) -> list[dict[str, Any]]:
    grouped: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        timestamp = row["trdtime"]
        bucket = timestamp.replace(minute=(timestamp.minute // interval) * interval, second=0, microsecond=0)
        current = grouped.get(bucket)
        values = {key: float(row[key] or 0) for key in ("open", "high", "low", "close", "vol", "amt")}
        if current is None:
            grouped[bucket] = {"datetime": bucket, **values}
        else:
            current["high"] = max(current["high"], values["high"])
            current["low"] = min(current["low"], values["low"])
            current["close"] = values["close"]
            current["vol"] += values["vol"]
            current["amt"] += values["amt"]
    return list(grouped.values())


def run_backtest(config: BacktestConfig, source: HistorySource | None = None) -> BacktestResult:
    """Run a long-only moving-average cross strategy against read-only data."""
    if config.interval < 1 or config.fast_window < 1 or config.fast_window >= config.slow_window:
        raise ValueError("interval and moving-average windows are invalid")
    source = source or HistorySource.from_environment()
    if source.backend != "clickhouse":
        raise ValueError("BacktestService currently requires QF_HISTORY_BACKEND=clickhouse")
    bars = _aggregate(_raw_bars(source, config), config.interval)
    result = BacktestResult(
        config={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(config).items()},
        source=f"{source.clickhouse_database}.{source.table}",
        bars=len(bars),
        final_equity=config.capital,
    )
    if len(bars) < config.slow_window + 2:
        return result

    cash, position, entry_price = config.capital, 0, 0.0
    equity_curve: list[float] = []
    pending: str | None = None
    for index, bar in enumerate(bars):
        if pending and index > 0:
            price = bar["open"] * (1 + (config.slippage_bps / 10000 if pending == "buy" else -config.slippage_bps / 10000))
            # A-share buys must be whole lots.  Do not create a synthetic
            # leveraged trade when available cash cannot pay for one lot.
            volume = int(cash / (price * config.lot_size)) * config.lot_size if pending == "buy" else position
            if volume:
                turnover = price * volume
                commission = turnover * config.commission_rate
                if pending == "buy":
                    cash -= turnover + commission
                    position += volume
                    entry_price = price
                else:
                    cash += turnover - commission
                    realized = (price - entry_price) * volume - commission
                    position = 0
                    result.trades.append(BacktestTrade(bar["datetime"].isoformat(), "sell", price, volume, turnover, commission, realized))
                if pending == "buy":
                    result.trades.append(BacktestTrade(bar["datetime"].isoformat(), "buy", price, volume, turnover, commission, 0.0))
        pending = None
        closes = [item["close"] for item in bars[:index + 1]]
        if len(closes) >= config.slow_window + 1:
            fast_now = sum(closes[-config.fast_window:]) / config.fast_window
            slow_now = sum(closes[-config.slow_window:]) / config.slow_window
            fast_prev = sum(closes[-config.fast_window - 1:-1]) / config.fast_window
            slow_prev = sum(closes[-config.slow_window - 1:-1]) / config.slow_window
            if position == 0 and fast_prev <= slow_prev and fast_now > slow_now:
                pending = "buy"
            elif position > 0 and fast_prev >= slow_prev and fast_now < slow_now:
                pending = "sell"
        equity_curve.append(cash + position * bar["close"])

    if position and bars:
        bar = bars[-1]
        price = bar["close"] * (1 - config.slippage_bps / 10000)
        turnover = price * position
        commission = turnover * config.commission_rate
        cash += turnover - commission
        result.trades.append(BacktestTrade(bar["datetime"].isoformat(), "sell", price, position, turnover, commission, (price - entry_price) * position - commission))
        equity_curve[-1] = cash
    result.final_equity = cash
    result.pnl = cash - config.capital
    result.return_rate = result.pnl / config.capital if config.capital else 0.0
    peak = config.capital
    result.max_drawdown = max((peak := max(peak, equity)) - equity for equity in equity_curve) if equity_curve else 0.0
    sells = [trade for trade in result.trades if trade.side == "sell"]
    result.win_rate = sum(trade.realized_pnl > 0 for trade in sells) / len(sells) if sells else 0.0
    return result
