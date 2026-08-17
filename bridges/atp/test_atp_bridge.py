"""ATP bridge recovery and idempotency tests without contacting AGW."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atp_bridge import (
    ATPBridge,
    BridgeHandler,
    OrderIntentJournal,
    ReconciliationJournal,
)
from atp_session import SUCCESS_CODE, Sequence


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def publish(self, message: dict) -> None:
        self.events.append(message)


class RecoveryAPI:
    def __init__(self, handler: BridgeHandler) -> None:
        self.handler = handler
        self.calls: list[str] = []

    def ReqCustLoginOther(self, request: dict) -> dict:
        self.calls.append("customer_login")
        self.handler.OnRspCustLoginResp({"permisson_error_code": 0})
        return {"err_code": SUCCESS_CODE}

    def ReqFundQuery(self, request: dict) -> dict:
        self.calls.append("fund")
        return {"err_code": SUCCESS_CODE}

    def ReqShareQuery(self, request: dict) -> dict:
        self.calls.append("position")
        return {"err_code": SUCCESS_CODE}

    def ReqOrderQuery(self, request: dict) -> dict:
        self.calls.append("order")
        return {"err_code": SUCCESS_CODE}

    def ReqTradeOrderQuery(self, request: dict) -> dict:
        self.calls.append("trade")
        return {"err_code": SUCCESS_CODE}


class ATPBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "atp-order-intents.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def context() -> dict:
        return {
            "account": "610000071840",
            "trace_id": "QF-610000071840-42",
            "ticker": "300007",
            "exchange": "SZSE",
            "market_id": 102,
            "side": "1",
            "order_type": 3,
            "price": 123450,
            "quantity": 10000,
            "engine_id": 9,
            "order_token": 42,
            "send_time": "2026-08-17 10:00:00.000000",
        }

    def test_order_reference_survives_bridge_restart(self) -> None:
        journal = OrderIntentJournal(self.path)
        self.assertTrue(journal.reserve("610000071840", 42, self.context()))
        journal.bind_order_ref("ATP-1001", self.context())

        restarted = OrderIntentJournal(self.path)
        self.assertFalse(restarted.reserve("610000071840", 42, self.context()))
        handler = BridgeHandler()
        handler.order_journal = restarted
        status = handler._normalize_order({
            "cl_ord_no": "ATP-1001",
            "security_id": "300007",
            "market_id": 102,
            "order_status": 3,
            "price": 123450,
            "order_qty": 10000,
            "leaves_qty": 10000,
            "cum_qty": 0,
        })

        self.assertEqual(status["order_token"], 42)
        self.assertEqual(status["trace_id"], "QF-610000071840-42")
        self.assertEqual(status["price"], 12.345)
        self.assertEqual(status["volume"], 100)

    def test_recovery_relogs_and_queries_complete_counter_state(self) -> None:
        reconciliation_path = Path(self.temp_dir.name) / "atp-reconciliation.jsonl"
        handler = BridgeHandler()
        recorder = EventRecorder()
        handler.server = recorder
        api = RecoveryAPI(handler)
        handler.bind_session(
            api,
            {"account": {
                "customer_id": "610000071840",
                "fund_account_id": "610000071840",
                "shenzhen_account_id": "0233005158",
                "branch_id": "6100",
                "encrypted_password": "test",
            }},
            Sequence(),
            OrderIntentJournal(self.path),
            ReconciliationJournal(reconciliation_path),
        )

        handler._resync()

        self.assertEqual(api.calls, ["customer_login", "fund", "position", "order", "trade"])
        self.assertIn(
            {"type": "resync_complete", "name": "atp", "recovered": True},
            recorder.events,
        )
        journal_text = reconciliation_path.read_text(encoding="utf-8")
        self.assertIn('"type": "resync_complete"', journal_text)
        self.assertNotIn('"password"', journal_text)

    def test_bad_cancel_command_returns_order_scoped_error(self) -> None:
        handler = BridgeHandler()
        recorder = EventRecorder()
        handler.server = recorder
        bridge = ATPBridge(
            api=None,
            handler=handler,
            config={"account": {"fund_account_id": "610000071840"}},
            sequence=Sequence(),
            orders_enabled=True,
            order_journal=OrderIntentJournal(self.path),
        )

        bridge.on_command({"type": "cancel", "order_ref": "ATP-1001", "exchange": "INVALID"})

        self.assertEqual(recorder.events[-1]["type"], "cancel_error")
        self.assertEqual(recorder.events[-1]["order_ref"], "ATP-1001")
        self.assertEqual(recorder.events[-1]["error_id"], -2007)


if __name__ == "__main__":
    unittest.main()
