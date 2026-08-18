import os
import unittest
from collections import OrderedDict
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.ui import QtCore, QtWidgets

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


class WorkbenchNavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self) -> None:
        self.event_engine = EventEngine()
        self.main_engine = MainEngine(self.event_engine)
        self.window = WorkbenchWindow(self.main_engine, self.event_engine)

    def tearDown(self) -> None:
        self.window.close()

    def test_default_page_is_overview_and_heavy_pages_are_lazy(self) -> None:
        self.assertEqual(self.window.page_stack.currentWidget().page_key, "overview")
        self.assertEqual(self.window.sidebar.width(), 200)
        self.assertEqual(set(self.window.pages), {"overview"})

    def test_sidebar_switches_to_one_reused_page_instance(self) -> None:
        self.window.sidebar.list.setCurrentRow(1)
        market = self.window.page_stack.currentWidget()
        self.assertEqual(market.page_key, "market")
        self.assertEqual(self.window.page_stack.count(), 2)
        self.window.sidebar.list.setCurrentRow(0)
        self.window.sidebar.list.setCurrentRow(1)
        self.assertIs(self.window.page_stack.currentWidget(), market)
        self.assertEqual(self.window.page_stack.count(), 2)

    def test_all_pages_are_navigable_and_keep_sidebar_selection(self) -> None:
        expected = (
            "overview", "market", "trading", "account",
            "orders", "backtest", "strategy", "settings",
        )
        for page_key in expected:
            self.window._show_page(page_key)
            self.assertEqual(self.window.page_stack.currentWidget().page_key, page_key)
            current = self.window.sidebar.list.currentItem()
            self.assertIsNotNone(current)
            self.assertEqual(current.data(QtCore.Qt.ItemDataRole.UserRole), page_key)
        self.assertEqual(self.window.page_stack.count(), len(expected))


if __name__ == "__main__":
    unittest.main()
