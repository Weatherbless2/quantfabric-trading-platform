#!/usr/bin/env python3
"""ATP SDK 与 QuantFabric C++ 插件之间的本机 JSON 行桥。"""

import argparse
import json
import socket
import threading
import time
from pathlib import Path

from atp_readonly import (
    ATP_LIB_DIR,
    ROOT_DIR,
    SUCCESS_CODE,
    ATPTradeAPI,
    ATPTradeHandler,
    Sequence,
    account_request,
    load_config,
    require_success,
    wait_for,
)


def scaled(value, precision):
    return float(value or 0) / (10 ** precision)


def order_trace_id(account, order_token=0, order_ref=""):
    token = str(order_token or "").strip()
    if token and token != "0":
        return f"QF-{account}-{token}"
    return f"QF-{account}-REF-{order_ref or 'UNKNOWN'}"


def market_details(config, exchange):
    aliases = {
        "SH": (101, "shanghai_account_id"),
        "SSE": (101, "shanghai_account_id"),
        "SZ": (102, "shenzhen_account_id"),
        "SZSE": (102, "shenzhen_account_id"),
    }
    normalized = str(exchange).strip().upper()
    if normalized not in aliases:
        raise ValueError(f"ATP 不支持的交易所: {exchange}")
    market_id, account_key = aliases[normalized]
    return market_id, config["account"][account_key]


class CommandServer:
    def __init__(self, host, port, orders_enabled, on_command):
        self._orders_enabled = orders_enabled
        self._on_command = on_command
        self._clients = []
        self._lock = threading.Lock()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen(4)

    def publish(self, message):
        payload = (json.dumps(message, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        with self._lock:
            active_clients = []
            for client in self._clients:
                try:
                    client.sendall(payload)
                    active_clients.append(client)
                except OSError:
                    client.close()
            self._clients = active_clients
        print(json.dumps(message, ensure_ascii=False, default=str), flush=True)

    def _handle_client(self, client):
        try:
            stream = client.makefile("r", encoding="utf-8")
            for line in stream:
                try:
                    self._on_command(json.loads(line))
                except Exception as exc:
                    self.publish({"type": "command_error", "error": str(exc)})
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)
            client.close()

    def serve_forever(self):
        while True:
            client, _ = self._server.accept()
            with self._lock:
                self._clients.append(client)
            self.publish({"type": "login", "connected": True, "orders_enabled": self._orders_enabled})
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()


class BridgeHandler(ATPTradeHandler):
    def __init__(self):
        super().__init__()
        self.agw_login = threading.Event()
        self.customer_login = threading.Event()
        self.failed_reason = None
        self.server = None
        self.order_context = {}
        self.order_ref_context = {}
        self.context_lock = threading.Lock()

    def publish(self, message):
        if self.server:
            self.server.publish(message)

    def OnLogin(self, reason):
        self.agw_login.set()

    def OnRecovered(self, reason):
        self.agw_login.set()

    def OnClosed(self, reason):
        self.failed_reason = reason
        self.publish({"type": "login", "connected": False, "reason": reason})

    def OnConnectFailure(self, reason):
        self.failed_reason = reason

    def OnConnectTimeOut(self, reason):
        self.failed_reason = reason

    def OnRspCustLoginResp(self, data):
        if data.get("permisson_error_code", -1) == 0:
            self.customer_login.set()
        else:
            self.failed_reason = data.get("reject_desc", "客户登录失败")

    def OnRspFundQueryResult(self, data):
        self.publish({
            "type": "fund",
            "balance": scaled(data.get("leaves_value"), 4),
            "pre_balance": scaled(data.get("init_leaves_value"), 4),
            "available": scaled(data.get("available_t0"), 4),
        })

    def OnRspShareQueryResult(self, data):
        for position in data.get("order_array", []):
            market_id = position.get("market_id", 0)
            self.publish({
                "type": "position",
                "ticker": position.get("security_id", "").strip(),
                "exchange": "SSE" if market_id == 101 else "SZSE",
                "total": int(scaled(position.get("leaves_qty"), 2)),
                "available": int(scaled(position.get("available_qty"), 2)),
                "yesterday": int(scaled(position.get("init_qty"), 2)),
            })

    def OnRspOrderQueryResult(self, data):
        for order in data.get("order_array", []):
            self.publish(self._normalize_order(order))
        self.publish({"type": "query_complete", "name": "order", "count": data.get("total_num", 0)})

    def OnRspTradeOrderQueryResult(self, data):
        self.publish({"type": "query_complete", "name": "trade", "count": data.get("total_num", 0)})

    def remember_order(self, client_seq_id, context):
        with self.context_lock:
            self.order_context[client_seq_id] = context

    def _normalize_order(self, data, fallback_status="accepted"):
        client_seq_id = int(data.get("client_seq_id", 0) or 0)
        order_ref = str(data.get("cl_ord_no", "") or "")
        with self.context_lock:
            context = self.order_context.get(client_seq_id, {})
            if not context and order_ref:
                context = self.order_ref_context.get(order_ref, {})
            if context and order_ref:
                self.order_ref_context[order_ref] = context

        reject_reason_code = int(data.get("reject_reason_code", 0) or 0)
        rejected = reject_reason_code != 0
        leaves = int(scaled(data.get("leaves_qty"), 2))
        traded = int(scaled(data.get("cum_qty"), 2))
        status_code = int(data.get("order_status", data.get("ord_status", -1)) or -1)
        if rejected:
            status = "rejected"
        elif status_code == 4:
            status = "partial_cancelled" if traded > 0 else "cancelled"
        elif traded > 0 and leaves == 0:
            status = "filled"
        elif traded > 0:
            status = "partial"
        else:
            status = fallback_status

        market_id = int(data.get("market_id", context.get("market_id", 0)) or 0)
        trace_id = context.get("trace_id") or order_trace_id("UNKNOWN", 0, order_ref)
        return {
            "type": "order_status",
            "trace_id": trace_id,
            "status": status,
            "ticker": data.get("security_id", context.get("ticker", "")).strip(),
            "exchange": "SSE" if market_id == 101 else "SZSE",
            "order_ref": order_ref,
            "order_sys_id": str(data.get("order_id", "") or "").strip(),
            "side": int(data.get("side", context.get("side", 0)) or 0),
            "order_type": context.get("order_type", 3),
            "price": scaled(data.get("price", context.get("price", 0)), 4),
            "volume": int(scaled(data.get("order_qty", context.get("quantity", 0)), 2)),
            "traded": traded,
            "traded_price": scaled(data.get("last_px"), 4),
            "cancelled": int(scaled(data.get("canceled_qty"), 2)),
            "engine_id": context.get("engine_id", 0),
            "order_token": context.get("order_token", 0),
            "send_time": context.get("send_time", ""),
            "error_id": reject_reason_code,
            "error_msg": str(data.get("ord_rej_reason", "")).strip(),
        }

    def OnRspOrderStatusInternalAck(self, data):
        self.publish(self._normalize_order(data, "accepted"))

    def OnRspOrderStatusAck(self, data):
        self.publish(self._normalize_order(data, "accepted"))

    def OnRspCashAuctionTradeER(self, data):
        self.publish(self._normalize_order(data, "partial"))

    def OnRspBizRejection(self, data):
        self.publish(self._normalize_order(data, "rejected"))


class ATPBridge:
    def __init__(self, api, handler, config, sequence, orders_enabled):
        self.api = api
        self.handler = handler
        self.config = config
        self.sequence = sequence
        self.orders_enabled = orders_enabled

    def _query(self, name):
        methods = {
            "fund": (self.api.ReqFundQuery, {}),
            "position": (self.api.ReqShareQuery, {"return_num": 0}),
            "order": (self.api.ReqOrderQuery, {"business_abstract_type": 1}),
            "trade": (self.api.ReqTradeOrderQuery, {"business_abstract_type": 1}),
        }
        if name not in methods:
            raise ValueError(f"不支持的查询类型: {name}")
        method, extra = methods[name]
        request = account_request(self.config, self.sequence)
        request.update(extra)
        require_success(name, method(request))

    def _order(self, command):
        if not self.orders_enabled:
            raise PermissionError("ATP 桥处于只读模式，启动时需显式传入 --enable-orders")
        if int(command["order_type"]) != 3:
            raise ValueError("ATP 现金交易桥当前只支持限价单")
        direction = int(command["direction"])
        if direction not in (1, 2):
            raise ValueError("ATP 现金交易桥当前只支持普通买入和卖出")
        market_id, account_id = market_details(self.config, command["exchange"])
        request = account_request(self.config, self.sequence)
        sequence_id = request["client_seq_id"]
        account = self.config["account"]["fund_account_id"]
        trace_id = order_trace_id(account, command.get("order_token", 0))
        request.update({
            "account_id": account_id,
            "security_id": command["ticker"],
            "market_id": market_id,
            # ATP 使用定点整数：数量 2 位小数，价格 4 位小数。
            "order_qty": ATPTradeAPI.DoubleExpandToInt(command["volume"], 2),
            "price": ATPTradeAPI.DoubleExpandToInt(command["price"], 4),
            "side": str(direction),
            "order_way": ord("N"),
            "order_type": "a",
        })
        self.handler.remember_order(sequence_id, {
            "trace_id": trace_id,
            "ticker": command["ticker"],
            "market_id": market_id,
            "side": request["side"],
            "order_type": int(command["order_type"]),
            "price": request["price"],
            "quantity": request["order_qty"],
            "engine_id": command.get("engine_id", 0),
            "order_token": command.get("order_token", 0),
            "send_time": command.get("send_time", ""),
        })
        print(json.dumps({
            "event": "order_request",
            "trace_id": trace_id,
            "ticker": command["ticker"],
            "exchange": command["exchange"],
            "price": command["price"],
            "volume": command["volume"],
        }, ensure_ascii=False), flush=True)
        result = self.api.ReqCashAuctionOrder(request)
        if result.get("err_code") != SUCCESS_CODE:
            self.handler.publish({
                "type": "order_status",
                "trace_id": trace_id,
                "status": "rejected",
                "ticker": command["ticker"],
                "exchange": command["exchange"],
                "order_ref": "",
                "order_sys_id": "",
                "side": direction,
                "order_type": int(command["order_type"]),
                "price": command["price"],
                "volume": command["volume"],
                "traded": 0,
                "traded_price": 0,
                "cancelled": 0,
                "engine_id": command.get("engine_id", 0),
                "order_token": command.get("order_token", 0),
                "send_time": command.get("send_time", ""),
                "error_id": result.get("err_code", -1),
                "error_msg": result.get("err_msg", "ATP 未接受报单请求"),
            })
            return
        require_success("order", result)

    def _cancel(self, command):
        if not self.orders_enabled:
            raise PermissionError("ATP 桥处于只读模式，启动时需显式传入 --enable-orders")
        market_id, account_id = market_details(self.config, command["exchange"])
        request = account_request(self.config, self.sequence)
        request.update({
            "account_id": account_id,
            "orig_cl_ord_no": int(command["order_ref"]),
            "market_id": market_id,
        })
        account = self.config["account"]["fund_account_id"]
        print(json.dumps({
            "event": "cancel_request",
            "trace_id": order_trace_id(account, 0, str(command["order_ref"])),
            "order_ref": str(command["order_ref"]),
            "exchange": command["exchange"],
        }, ensure_ascii=False), flush=True)
        result = self.api.ReqCancelOrder(request)
        if result.get("err_code") != SUCCESS_CODE:
            self.handler.publish({
                "type": "cancel_error",
                "order_ref": str(command["order_ref"]),
                "error_id": result.get("err_code", -1),
                "error_msg": result.get("err_msg", "ATP 未接受撤单请求"),
            })
            return
        require_success("cancel", result)

    def on_command(self, command):
        command_type = command.get("type")
        if command_type == "query":
            self._query(command["name"])
        elif command_type == "order":
            self._order(command)
        elif command_type == "cancel":
            self._cancel(command)
        else:
            raise ValueError(f"不支持的命令类型: {command_type}")


def main():
    parser = argparse.ArgumentParser(description="QuantFabric ATP 本机交易桥")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--enable-orders", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    config = load_config(args.config)
    log_dir = ROOT_DIR / "runtime" / "log" / "atp"
    log_dir.mkdir(parents=True, exist_ok=True)
    encrypt_config = {
        "ENCRYPT_SCHEMA": "0",
        "ATP_ENCRYPT_PASSWORD": "",
        "ATP_LOGIN_ENCRYPT_PASSWORD": "",
        "GM_SM2_PUBLIC_KEY_PATH": "",
        "RSA_PUBLIC_KEY_PATH": "",
    }
    require_success(
        "sdk_init",
        ATPTradeAPI.Init("", str(ATP_LIB_DIR), str(log_dir), True, encrypt_config, 1, False),
    )

    api = ATPTradeAPI()
    handler = BridgeHandler()
    sequence = Sequence()
    agw = config["agw"]
    connect_config = {
        "user": agw["user"],
        "password": agw["password"],
        "locations": agw["locations"],
        "heartbeat_interval_milli": 5000,
        "connect_timeout_milli": int(args.timeout * 1000),
        "reconnect_time": 10,
        "client_name": "quantfabric_atp_bridge",
        "client_version": "v0.1",
        "mode": 1,
        "report_sync": {},
    }

    require_success("agw_connect", api.Connect(connect_config, handler))
    wait_for(handler.agw_login, "AGW 登录", args.timeout, handler)
    login_request = account_request(config, sequence)
    login_request.update({"password": config["account"]["encrypted_password"], "login_mode": 1})
    require_success("customer_login", api.ReqCustLoginOther(login_request))
    wait_for(handler.customer_login, "客户登录", args.timeout, handler)

    listen = config["listen"]
    bridge = ATPBridge(api, handler, config, sequence, args.enable_orders)
    server = CommandServer(listen["host"], listen["port"], args.enable_orders, bridge.on_command)
    handler.server = server
    print(json.dumps({"event": "bridge_listening", "listen": listen, "orders_enabled": args.enable_orders}), flush=True)
    try:
        server.serve_forever()
    finally:
        api.Stop()
        api.Close()


if __name__ == "__main__":
    main()
