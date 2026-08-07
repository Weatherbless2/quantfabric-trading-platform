import unittest

from vnpy.trader.constant import Exchange

from VnpyMonitor.gateway import map_exchange


class ExchangeMappingTest(unittest.TestCase):
    def test_supported_aliases(self) -> None:
        self.assertEqual(map_exchange("SH"), Exchange.SSE)
        self.assertEqual(map_exchange("SSE"), Exchange.SSE)
        self.assertEqual(map_exchange("SZ"), Exchange.SZSE)
        self.assertEqual(map_exchange("SZSE"), Exchange.SZSE)

    def test_unknown_exchange_is_local(self) -> None:
        self.assertEqual(map_exchange("UNKNOWN"), Exchange.LOCAL)


if __name__ == "__main__":
    unittest.main()
