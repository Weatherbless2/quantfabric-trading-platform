import unittest
from collections import OrderedDict
from datetime import datetime

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData

from VnpyMonitor.ui import WorkbenchWindow


def _bar(timestamp: datetime, close: float) -> BarData:
    return BarData(
        gateway_name="test",
        symbol="300007",
        exchange=Exchange.SZSE,
        datetime=timestamp,
        interval=Interval.MINUTE,
        open_price=close,
        high_price=close,
        low_price=close,
        close_price=close,
    )


class ChartMergeLogicTest(unittest.TestCase):
    def test_real_time_bar_near_last_history_close_is_compatible(self) -> None:
        history = OrderedDict([(datetime(2026, 8, 11, 15), _bar(datetime(2026, 8, 11, 15), 34.34))])
        live = OrderedDict([(datetime(2026, 8, 12, 9, 31), _bar(datetime(2026, 8, 12, 9, 31), 34.50))])
        self.assertTrue(WorkbenchWindow._live_bars_match_history(history, live))

    def test_simulated_outlier_is_not_overlaid_on_history_chart(self) -> None:
        history = OrderedDict([(datetime(2026, 8, 11, 15), _bar(datetime(2026, 8, 11, 15), 34.34))])
        live = OrderedDict([(datetime(2026, 8, 13, 10, 56), _bar(datetime(2026, 8, 13, 10, 56), 8.08))])
        self.assertFalse(WorkbenchWindow._live_bars_match_history(history, live))


if __name__ == "__main__":
    unittest.main()
