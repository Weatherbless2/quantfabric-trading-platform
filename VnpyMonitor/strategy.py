"""Optional live adapter for the shared transport-neutral strategy."""

from __future__ import annotations

from StrategyService import MovingAverageCrossStrategy, StrategyBar
from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
from vnpy.trader.object import BarData, OrderRequest


class VnpyStrategyRunner:
    """Turn shared strategy signals into ordinary vn.py order requests."""

    def __init__(self, main_engine, volume: int = 100,
                 fast_window: int = 10, slow_window: int = 30) -> None:
        self.main_engine = main_engine
        self.volume = volume
        self.strategy = MovingAverageCrossStrategy(fast_window, slow_window)
        self.vt_symbol = ""
        # The runner only exists when the operator explicitly selects a
        # strategy.  WorkbenchWindow toggles this flag with the C++ session
        # state so a disconnect can never create a new order.
        self.enabled = True
        self.last_signal = ""
        self.last_orderid = ""

    def set_symbol(self, vt_symbol: str) -> None:
        if vt_symbol != self.vt_symbol:
            self.vt_symbol = vt_symbol
            self.strategy.reset()
            self.last_signal = ""
            self.last_orderid = ""

    def set_enabled(self, enabled: bool) -> None:
        """Pause order emission while retaining deterministic strategy state."""
        self.enabled = bool(enabled)

    def reset(self) -> None:
        """Forget warm-up bars when the workbench changes its data context."""
        self.strategy.reset()
        self.last_signal = ""
        self.last_orderid = ""

    def prime(self, bars: list[BarData]) -> None:
        """Warm up from historical bars without emitting historical orders."""
        self.reset()
        for bar in bars:
            self.strategy.on_bar(StrategyBar(
                datetime=bar.datetime,
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                turnover=bar.turnover,
            ))

    def on_bar(self, bar: BarData) -> str:
        if not self.vt_symbol or bar.vt_symbol != self.vt_symbol:
            return ""
        signal = self.strategy.on_bar(StrategyBar(
            datetime=bar.datetime,
            open_price=bar.open_price,
            high_price=bar.high_price,
            low_price=bar.low_price,
            close_price=bar.close_price,
            volume=bar.volume,
            turnover=bar.turnover,
        ))
        if not signal:
            return ""
        self.last_signal = f"{signal.side}:{signal.reason}"
        if not self.enabled:
            return ""
        symbol, exchange_value = self.vt_symbol.rsplit(".", 1)
        request = OrderRequest(
            symbol=symbol,
            exchange=Exchange(exchange_value),
            direction=Direction.LONG if signal.side == "buy" else Direction.SHORT,
            type=OrderType.LIMIT,
            volume=self.volume,
            price=bar.close_price,
            offset=Offset.NONE,
            reference="QuantFabric共享策略",
        )
        self.last_orderid = self.main_engine.send_order(request, "QUANTFABRIC") or ""
        return self.last_orderid
