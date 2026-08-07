import unittest

from vnpy.event import EventEngine
from vnpy.trader.constant import Direction, Exchange, OrderType
from vnpy.trader.object import CancelRequest, OrderRequest

from VnpyMonitor.gateway import GATEWAY_NAME, QuantFabricGateway, map_exchange


class FakeConnection:
    def __init__(self, send_result: bool = True) -> None:
        self.send_result = send_result
        self.messages: list[dict] = []

    def send(self, message: dict) -> bool:
        self.messages.append(message)
        return self.send_result


class ExchangeMappingTest(unittest.TestCase):
    def test_supported_aliases(self) -> None:
        self.assertEqual(map_exchange("SH"), Exchange.SSE)
        self.assertEqual(map_exchange("SSE"), Exchange.SSE)
        self.assertEqual(map_exchange("SZ"), Exchange.SZSE)
        self.assertEqual(map_exchange("SZSE"), Exchange.SZSE)

    def test_unknown_exchange_is_local(self) -> None:
        self.assertEqual(map_exchange("UNKNOWN"), Exchange.LOCAL)


class TradingControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.event_engine = EventEngine()
        self.gateway = QuantFabricGateway(self.event_engine, GATEWAY_NAME)
        self.connection = FakeConnection()
        self.gateway.control_connection = self.connection
        self.gateway.orders_enabled = True

    @staticmethod
    def order_request(volume: int = 100) -> OrderRequest:
        return OrderRequest(
            symbol="300007",
            exchange=Exchange.SZSE,
            direction=Direction.LONG,
            type=OrderType.LIMIT,
            volume=volume,
            price=18.56,
        )

    def test_disabled_status_prevents_order(self) -> None:
        self.gateway.orders_enabled = False
        self.assertEqual(self.gateway.send_order(self.order_request()), "")
        self.assertEqual(self.connection.messages, [])

    def test_invalid_lot_size_prevents_order(self) -> None:
        self.assertEqual(self.gateway.send_order(self.order_request(150)), "")
        self.assertEqual(self.connection.messages, [])

    def test_order_maps_to_control_command(self) -> None:
        vt_orderid = self.gateway.send_order(self.order_request())
        self.assertEqual(vt_orderid, f"{GATEWAY_NAME}.1")
        self.assertEqual(self.connection.messages, [{
            "type": "order",
            "ticker": "300007",
            "exchange": "SZSE",
            "direction": 1,
            "price": 18.56,
            "volume": 100,
            "order_token": 1,
        }])

    def test_cancel_waits_for_atp_order_reference(self) -> None:
        self.gateway.send_order(self.order_request())
        request = CancelRequest(orderid="1", symbol="300007", exchange=Exchange.SZSE)
        self.gateway.cancel_order(request)
        self.assertEqual(len(self.connection.messages), 1)

        self.gateway._map_order({
            "ticker": "300007",
            "exchange": "SZSE",
            "order_token": 1,
            "order_ref": "ATP-1024",
            "side": 1,
        })
        self.gateway.cancel_order(request)
        self.assertEqual(self.connection.messages[-1], {
            "type": "cancel",
            "order_ref": "ATP-1024",
            "exchange": "SZSE",
        })


if __name__ == "__main__":
    unittest.main()
