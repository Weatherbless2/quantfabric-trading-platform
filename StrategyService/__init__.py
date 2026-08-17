"""Shared strategy contracts used by backtest and live execution."""

from .core import MovingAverageCrossStrategy, Signal, StrategyBar

__all__ = ["MovingAverageCrossStrategy", "Signal", "StrategyBar"]
