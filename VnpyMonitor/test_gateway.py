import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from vnpy.event import EventEngine
from vnpy.trader.constant import Direction, Exchange, OrderType, Status
from vnpy.trader.object import CancelRequest, OrderRequest, SubscribeRequest

from VnpyMonitor.gateway import (
    EVENT_QF_CONNECTION,
    GATEWAY_NAME,
    QuantFabricGateway,
    AUTH_SESSION_ID_LENGTH,
    create_auth_session,
    map_exchange,
    order_trace_id,
)


class FakeNativeClient:
    def __init__(self) -> None:
        self.orders: list[tuple] = []
        self.cancels: list[tuple] = []
        self.subscriptions: list[tuple] = []
        self.last_error = ""
        self.connected = False
        self.logged_in = False

    def send_order(self, *args) -> bool:
        self.orders.append(args)
        return True

    def cancel_order(self, *args) -> bool:
        self.cancels.append(args)
        return True

    def subscribe(self, *args) -> bool:
        self.subscriptions.append(args)
        return True

    def is_connected(self) -> bool:
        return self.connected

    def is_logged_in(self) -> bool:
        return self.logged_in


class ConnectingNativeClient(FakeNativeClient):
    def __init__(self, *args) -> None:
        super().__init__()
        self.args = args
        self.started = False

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self) -> None:
        self.started = False


class FakeHttpResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


class ExchangeMappingTest(unittest.TestCase):
    def test_order_trace_uses_token_then_falls_back_to_order_ref(self) -> None:
        self.assertEqual(order_trace_id("610000071840", 7), "QF-610000071840-7")
        self.assertEqual(
            order_trace_id("610000071840", 0, "ATP-1024"),
            "QF-610000071840-REF-ATP-1024",
        )

    def test_supported_aliases(self) -> None:
        self.assertEqual(map_exchange("SH"), Exchange.SSE)
        self.assertEqual(map_exchange("SSE"), Exchange.SSE)
        self.assertEqual(map_exchange("SZ"), Exchange.SZSE)
        self.assertEqual(map_exchange("SZSE"), Exchange.SZSE)

    def test_unknown_exchange_is_local(self) -> None:
        self.assertEqual(map_exchange("UNKNOWN"), Exchange.LOCAL)


class AuthSessionTest(unittest.TestCase):
    @patch("VnpyMonitor.gateway.urlopen")
    def test_development_session_request_uses_login_endpoint(self, mocked_open) -> None:
        mocked_open.return_value = FakeHttpResponse(
            f'{{"session_id":"{"a" * AUTH_SESSION_ID_LENGTH}"}}'.encode()
        )
        session_id = create_auth_session("http://127.0.0.1:18080/", "admin", "123456")
        self.assertEqual(session_id, "a" * AUTH_SESSION_ID_LENGTH)
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18080/v1/sessions/development")
        self.assertIn(b'"username": "admin"', request.data)

    @patch("VnpyMonitor.gateway.urlopen")
    def test_oidc_token_selects_oidc_endpoint(self, mocked_open) -> None:
        mocked_open.return_value = FakeHttpResponse(
            f'{{"session_id":"{"b" * AUTH_SESSION_ID_LENGTH}"}}'.encode()
        )
        create_auth_session("http://127.0.0.1:18080", "admin", "unused", "oidc-token")
        request = mocked_open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:18080/v1/sessions/oidc")
        self.assertIn(b'"access_token": "oidc-token"', request.data)


class NativeTradingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.event_engine = EventEngine()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.token_path = Path(self.temp_dir.name) / "order-token.txt"
        self.token_patch = patch("VnpyMonitor.gateway.ORDER_TOKEN_PATH", self.token_path)
        self.token_patch.start()
        self.gateway = QuantFabricGateway(self.event_engine, GATEWAY_NAME)
        self.native_client = FakeNativeClient()
        self.gateway.native_client = self.native_client
        self.gateway.orders_enabled = True
        self.gateway.received_quotes.add("300007.SZSE")

    def tearDown(self) -> None:
        self.token_patch.stop()
        self.temp_dir.cleanup()

    def test_gateway_defaults_use_atp_counter(self) -> None:
        self.assertEqual(self.gateway.default_setting["交易机房"], "ATPTest")
        self.assertEqual(self.gateway.default_setting["交易产品"], "ATPTest")
        self.assertEqual(self.gateway.default_setting["资金账号"], "610000071840")

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
        self.assertEqual(self.native_client.orders, [])

    def test_invalid_lot_size_prevents_order(self) -> None:
        self.assertEqual(self.gateway.send_order(self.order_request(150)), "")
        self.assertEqual(self.native_client.orders, [])

    def test_missing_quote_prevents_order(self) -> None:
        self.gateway.received_quotes.clear()
        self.assertEqual(self.gateway.send_order(self.order_request()), "")
        self.assertEqual(self.native_client.orders, [])

    def test_order_maps_to_native_request(self) -> None:
        vt_orderid = self.gateway.send_order(self.order_request())
        token = int(vt_orderid.rsplit(".", 1)[1])
        self.assertGreater(token, 0)
        self.assertEqual(self.native_client.orders, [
            ("300007", "SZSE", 1, 18.56, 100, token),
        ])

    def test_order_token_is_durable_across_gateway_restarts(self) -> None:
        first = int(self.gateway.send_order(self.order_request()).rsplit(".", 1)[1])
        restarted = QuantFabricGateway(self.event_engine, GATEWAY_NAME)
        restarted.native_client = self.native_client
        restarted.orders_enabled = True
        restarted.received_quotes.add("300007.SZSE")
        second = int(restarted.send_order(self.order_request()).rsplit(".", 1)[1])
        self.assertGreater(second, first)

    def test_cancel_waits_for_order_reference(self) -> None:
        orderid = self.gateway.send_order(self.order_request()).rsplit(".", 1)[1]
        request = CancelRequest(orderid=orderid, symbol="300007", exchange=Exchange.SZSE)
        self.gateway.cancel_order(request)
        self.assertEqual(self.native_client.cancels, [])

        self.gateway._map_order({
            "ticker": "300007",
            "exchange": "SZSE",
            "order_token": int(orderid),
            "order_ref": "ATP-1024",
            "side": 1,
        })
        self.gateway.cancel_order(request)
        self.assertEqual(self.native_client.cancels, [("ATP-1024", "SZSE")])

    def test_xtrader_initialization_status_is_not_published_as_order(self) -> None:
        orders = []
        self.gateway.on_order = orders.append
        self.gateway._on_trade_message({
            "type": "order_status",
            "ticker": "300007",
            "exchange": "SZSE",
            "order_token": 0,
            "order_ref": "",
            "volume": 0,
            "status": "rejected",
        })
        self.assertEqual(orders, [])

    def test_xserver_rejection_without_counter_reference_is_terminal(self) -> None:
        orders = []
        self.gateway.on_order = orders.append
        self.gateway.pending_order_tokens.add("42")

        self.gateway._on_trade_message({
            "type": "order_status",
            "ticker": "300007",
            "exchange": "SZSE",
            "order_token": 42,
            "order_ref": "",
            "side": 1,
            "price": 18.56,
            "volume": 100,
            "status": "rejected",
            "error_id": -1003,
        })

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].status, Status.REJECTED)
        self.assertNotIn("42", self.gateway.pending_order_tokens)

    def test_session_event_requires_login_before_orders_are_enabled(self) -> None:
        events = []
        self.gateway.on_event = lambda event_type, data: events.append((event_type, data))
        self.gateway.orders_enabled = False
        self.native_client.connected = True
        self.gateway._publish_connection_state()
        connection_events = [data for event_type, data in events if event_type == EVENT_QF_CONNECTION]
        self.assertFalse(connection_events[-1]["connected"])
        self.assertFalse(self.gateway.orders_enabled)

        self.native_client.logged_in = True
        self.gateway._publish_connection_state()
        connection_events = [data for event_type, data in events if event_type == EVENT_QF_CONNECTION]
        self.assertTrue(connection_events[-1]["connected"])
        self.assertTrue(self.gateway.orders_enabled)

    def test_subscription_waits_for_login_and_uses_native_route(self) -> None:
        request = SubscribeRequest(symbol="300007", exchange=Exchange.SZSE)
        self.gateway.subscribe(request)
        self.assertEqual(self.native_client.subscriptions, [])

        self.native_client.connected = True
        self.native_client.logged_in = True
        self.gateway._flush_subscriptions()
        self.assertEqual(self.native_client.subscriptions, [("300007", "SZSE")])
        self.gateway._flush_subscriptions()
        self.assertEqual(len(self.native_client.subscriptions), 1)

    @patch("VnpyMonitor.gateway.QuantFabricClient", ConnectingNativeClient)
    @patch("VnpyMonitor.gateway.create_auth_session", return_value="c" * AUTH_SESSION_ID_LENGTH)
    def test_connect_passes_opaque_session_to_native_client(self, mocked_session) -> None:
        self.gateway.native_client = None
        self.gateway.connect(self.gateway.default_setting.copy())
        self.assertIsInstance(self.gateway.native_client, ConnectingNativeClient)
        self.assertEqual(self.gateway.native_client.args[4], "c" * AUTH_SESSION_ID_LENGTH)
        mocked_session.assert_called_once()
        self.gateway.close()


if __name__ == "__main__":
    unittest.main()
