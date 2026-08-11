import unittest

from bridges.market.pytdx_bridge import is_a_share, normalize_quote


class SecurityMasterTest(unittest.TestCase):
    def test_a_share_filter(self) -> None:
        self.assertTrue(is_a_share(0, "000001"))
        self.assertTrue(is_a_share(0, "300750"))
        self.assertTrue(is_a_share(1, "600519"))
        self.assertTrue(is_a_share(1, "688001"))
        self.assertFalse(is_a_share(1, "000001"))
        self.assertFalse(is_a_share(0, "159001"))
        self.assertFalse(is_a_share(1, "510300"))

    def test_quote_keeps_master_identity(self) -> None:
        security = {
            "market": 0,
            "ticker": "000002",
            "exchange": "SZSE",
            "name": "万科A",
        }
        quote = normalize_quote({"price": 9.81, "vol": 1200}, security)
        self.assertEqual(quote["ticker"], "000002")
        self.assertEqual(quote["exchange"], "SZSE")
        self.assertEqual(quote["name"], "万科A")
        self.assertEqual(quote["last_price"], 9.81)


if __name__ == "__main__":
    unittest.main()
