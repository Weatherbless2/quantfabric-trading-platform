"""Small transport-neutral strategy primitives.

The strategy never knows about ATP, XServer, vn.py, or ClickHouse.  Both the
backtest engine and the optional vn.py live runner adapt their own bar and
order objects to this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StrategyBar:
    datetime: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float = 0.0
    turnover: float = 0.0


@dataclass(frozen=True)
class Signal:
    side: str
    reason: str


class MovingAverageCrossStrategy:
    """Long-only moving-average cross strategy with deterministic state."""

    def __init__(self, fast_window: int = 10, slow_window: int = 30) -> None:
        if fast_window < 1 or slow_window <= fast_window:
            raise ValueError("fast_window must be smaller than slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window
        self._closes: list[float] = []

    def reset(self) -> None:
        self._closes.clear()

    def on_bar(self, bar: StrategyBar) -> Signal | None:
        if bar.close_price <= 0:
            return None
        self._closes.append(float(bar.close_price))
        if len(self._closes) < self.slow_window + 1:
            return None

        fast_now = sum(self._closes[-self.fast_window:]) / self.fast_window
        slow_now = sum(self._closes[-self.slow_window:]) / self.slow_window
        fast_prev = sum(self._closes[-self.fast_window - 1:-1]) / self.fast_window
        slow_prev = sum(self._closes[-self.slow_window - 1:-1]) / self.slow_window
        if fast_prev <= slow_prev and fast_now > slow_now:
            return Signal("buy", "fast average crossed above slow average")
        if fast_prev >= slow_prev and fast_now < slow_now:
            return Signal("sell", "fast average crossed below slow average")
        return None
