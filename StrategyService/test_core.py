import unittest
from datetime import datetime, timedelta

from .core import MovingAverageCrossStrategy, StrategyBar


class MovingAverageCrossStrategyTest(unittest.TestCase):
    def test_crosses_are_deterministic_and_resettable(self) -> None:
        strategy = MovingAverageCrossStrategy(fast_window=2, slow_window=3)
        start = datetime(2026, 1, 1, 9, 30)
        closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8]
        signals = []
        for index, close in enumerate(closes):
            signal = strategy.on_bar(StrategyBar(start + timedelta(minutes=index), close, close, close, close))
            if signal:
                signals.append(signal.side)
        self.assertEqual(signals, ["buy", "sell"])
        strategy.reset()
        self.assertIsNone(strategy.on_bar(StrategyBar(start, 10, 10, 10, 10)))


if __name__ == "__main__":
    unittest.main()
