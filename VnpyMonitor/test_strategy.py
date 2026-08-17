import unittest
from datetime import datetime, timedelta

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

from VnpyMonitor.strategy import VnpyStrategyRunner


class FakeMainEngine:
    def __init__(self) -> None:
        self.requests = []

    def send_order(self, request, gateway_name):
        self.requests.append((request, gateway_name))
        return "QUANTFABRIC.1"


class VnpyStrategyRunnerTest(unittest.TestCase):
    def test_live_adapter_uses_shared_signal_and_standard_order(self) -> None:
        engine = FakeMainEngine()
        runner = VnpyStrategyRunner(engine, volume=100, fast_window=2, slow_window=3)
        runner.set_symbol("300007.SZSE")
        start = datetime(2026, 1, 1, 9, 30)
        closes = [10, 9, 8, 9, 10, 11]
        for index, close in enumerate(closes):
            runner.on_bar(BarData(
                gateway_name="test", symbol="300007", exchange=Exchange.SZSE,
                datetime=start + timedelta(minutes=index), interval=Interval.MINUTE,
                open_price=close, high_price=close, low_price=close, close_price=close,
                volume=100,
            ))
        self.assertEqual(len(engine.requests), 1)
        request, gateway = engine.requests[0]
        self.assertEqual(gateway, "QUANTFABRIC")
        self.assertEqual(request.direction.value, "多")
        self.assertEqual(request.volume, 100)

    def test_prime_warms_up_without_creating_orders(self) -> None:
        engine = FakeMainEngine()
        runner = VnpyStrategyRunner(engine, volume=100, fast_window=2, slow_window=3)
        runner.set_symbol("300007.SZSE")
        start = datetime(2026, 1, 1, 9, 30)
        runner.prime([BarData(
            gateway_name="test", symbol="300007", exchange=Exchange.SZSE,
            datetime=start + timedelta(minutes=index), interval=Interval.MINUTE,
            open_price=close, high_price=close, low_price=close, close_price=close,
            volume=100,
        ) for index, close in enumerate([10, 9, 8, 9])])
        self.assertEqual(engine.requests, [])

    def test_disabled_runner_keeps_signal_but_does_not_send_order(self) -> None:
        engine = FakeMainEngine()
        runner = VnpyStrategyRunner(engine, volume=100, fast_window=2, slow_window=3)
        runner.set_symbol("300007.SZSE")
        runner.set_enabled(False)
        start = datetime(2026, 1, 1, 9, 30)
        for index, close in enumerate([10, 9, 8, 9, 10, 11]):
            runner.on_bar(BarData(
                gateway_name="test", symbol="300007", exchange=Exchange.SZSE,
                datetime=start + timedelta(minutes=index), interval=Interval.MINUTE,
                open_price=close, high_price=close, low_price=close, close_price=close,
                volume=100,
            ))
        self.assertTrue(runner.last_signal.startswith("buy:"))
        self.assertEqual(engine.requests, [])


if __name__ == "__main__":
    unittest.main()
