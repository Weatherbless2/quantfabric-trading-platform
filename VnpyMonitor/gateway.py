"""将 QuantFabric 本机 JSON 桥映射为 vn.py 标准数据对象。"""

from __future__ import annotations

import json
import socket
import threading
import time
from datetime import datetime
from typing import Callable

from vnpy.trader.constant import Direction, Exchange, OrderType, Product, Status
from vnpy.trader.gateway import BaseGateway
from vnpy.trader.object import (
    AccountData,
    CancelRequest,
    ContractData,
    OrderData,
    OrderRequest,
    PositionData,
    SubscribeRequest,
    TickData,
)


EVENT_QF_CONNECTION = "eQuantFabricConnection"
GATEWAY_NAME = "QUANTFABRIC"


def map_exchange(value: str) -> Exchange:
    """统一桥接层和 vn.py 的交易所代码。"""
    aliases = {
        "SH": Exchange.SSE,
        "SSE": Exchange.SSE,
        "SZ": Exchange.SZSE,
        "SZSE": Exchange.SZSE,
    }
    return aliases.get(str(value).strip().upper(), Exchange.LOCAL)


class JsonLineConnection:
    """带自动重连的本机 JSON 行客户端。"""

    def __init__(
        self,
        name: str,
        host: str,
        port: int,
        on_message: Callable[[dict], None],
        on_state: Callable[[str, bool, str], None],
        on_connected: Callable[["JsonLineConnection"], None] | None = None,
    ) -> None:
        self.name = name
        self.host = host
        self.port = port
        self.on_message = on_message
        self.on_state = on_state
        self.on_connected = on_connected
        self._active = threading.Event()
        self._socket: socket.socket | None = None
        self._socket_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._active.is_set():
            return
        self._active.set()
        self._thread = threading.Thread(
            target=self._run,
            name=f"qf-{self.name}-reader",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._active.clear()
        with self._socket_lock:
            sock = self._socket
            self._socket = None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def send(self, message: dict) -> bool:
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._socket_lock:
            sock = self._socket
            if not sock:
                return False
            try:
                sock.sendall(payload)
                return True
            except OSError:
                return False

    def _run(self) -> None:
        while self._active.is_set():
            try:
                sock = socket.create_connection((self.host, self.port), timeout=3)
                sock.settimeout(1)
                with self._socket_lock:
                    self._socket = sock
                self.on_state(self.name, True, f"{self.host}:{self.port}")
                if self.on_connected:
                    self.on_connected(self)
                self._read(sock)
            except OSError as exc:
                if self._active.is_set():
                    self.on_state(self.name, False, str(exc))
            finally:
                with self._socket_lock:
                    sock = self._socket
                    self._socket = None
                if sock:
                    sock.close()
            # Event.wait() returns immediately while the event is set; use a
            # bounded sleep here so an unavailable bridge cannot cause a busy loop.
            time.sleep(2)

    def _read(self, sock: socket.socket) -> None:
        buffer = b""
        while self._active.is_set():
            try:
                block = sock.recv(65536)
            except socket.timeout:
                continue
            if not block:
                raise ConnectionError("连接已关闭")
            buffer += block
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    self.on_message(json.loads(line.decode("utf-8")))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self.on_state(self.name, False, f"消息格式错误: {exc}")


class QuantFabricGateway(BaseGateway):
    """连接行情、账户查询和经过 C++ 风控的交易控制桥。"""

    default_name = GATEWAY_NAME
    exchanges = [Exchange.SSE, Exchange.SZSE]
    default_setting = {
        "行情地址": "127.0.0.1",
        "行情端口": 19001,
        "交易地址": "127.0.0.1",
        "交易端口": 19002,
        "控制地址": "127.0.0.1",
        "控制端口": 19003,
        "资金账号": "610000071840",
    }

    def __init__(self, event_engine, gateway_name: str) -> None:
        super().__init__(event_engine, gateway_name)
        self.account_id = "610000071840"
        self.market_connection: JsonLineConnection | None = None
        self.trade_connection: JsonLineConnection | None = None
        self.control_connection: JsonLineConnection | None = None
        self.contracts: set[str] = set()
        self.orders_enabled = False
        self.order_token = 0
        self.order_refs: dict[str, str] = {}
        self.pending_order_tokens: set[str] = set()

    def connect(self, setting: dict) -> None:
        if self.market_connection or self.trade_connection:
            return
        self.account_id = str(setting.get("资金账号", self.account_id))
        self.market_connection = JsonLineConnection(
            "行情桥",
            str(setting.get("行情地址", "127.0.0.1")),
            int(setting.get("行情端口", 19001)),
            self._on_market_message,
            self._on_connection_state,
        )
        self.trade_connection = JsonLineConnection(
            "ATP交易桥",
            str(setting.get("交易地址", "127.0.0.1")),
            int(setting.get("交易端口", 19002)),
            self._on_trade_message,
            self._on_connection_state,
            self._on_trade_connected,
        )
        self.control_connection = JsonLineConnection(
            "交易控制",
            str(setting.get("控制地址", "127.0.0.1")),
            int(setting.get("控制端口", 19003)),
            self._on_control_message,
            self._on_connection_state,
            lambda connection: connection.send({"type": "status"}),
        )
        self.market_connection.start()
        self.trade_connection.start()
        self.control_connection.start()
        self.write_log("网关已启动：交易请求固定经过 XServer 和 C++ 风控")

    def close(self) -> None:
        for connection in (self.market_connection, self.trade_connection, self.control_connection):
            if connection:
                connection.stop()
        self.market_connection = None
        self.trade_connection = None
        self.control_connection = None

    def subscribe(self, req: SubscribeRequest) -> None:
        self.write_log(f"行情由 QuantFabric 配置订阅：{req.vt_symbol}")

    def send_order(self, req: OrderRequest) -> str:
        if not self.orders_enabled or not self.control_connection:
            self.write_log("交易控制未就绪，委托未发送")
            return ""
        if req.type is not OrderType.LIMIT or req.direction not in (Direction.LONG, Direction.SHORT):
            self.write_log("当前仅支持普通股票限价买入和卖出")
            return ""
        volume = int(req.volume)
        if req.price <= 0 or volume <= 0 or volume % 100:
            self.write_log("价格必须大于 0，数量必须是 100 股的整数倍")
            return ""

        self.order_token += 1
        orderid = str(self.order_token)
        command = {
            "type": "order",
            "ticker": req.symbol,
            "exchange": req.exchange.value,
            "direction": 1 if req.direction is Direction.LONG else 2,
            "price": req.price,
            "volume": volume,
            "order_token": self.order_token,
        }
        if not self.control_connection.send(command):
            self.write_log("交易控制连接已断开，委托未发送")
            return ""
        self.pending_order_tokens.add(orderid)
        order = req.create_order_data(orderid, self.gateway_name)
        self.on_order(order)
        self.write_log(f"委托已提交 C++ 风控：{req.symbol} {req.price} x {volume}")
        return order.vt_orderid

    def cancel_order(self, req: CancelRequest) -> None:
        if not self.orders_enabled or not self.control_connection:
            self.write_log("交易控制未就绪，撤单未发送")
            return
        if req.orderid in self.pending_order_tokens:
            self.write_log("委托尚未取得 ATP 委托号，请稍后再撤")
            return
        order_ref = self.order_refs.get(req.orderid, req.orderid)
        command = {
            "type": "cancel",
            "order_ref": order_ref,
            "exchange": req.exchange.value,
        }
        if self.control_connection.send(command):
            self.write_log(f"撤单已提交 C++ 风控：{order_ref}")
        else:
            self.write_log("交易控制连接已断开，撤单未发送")

    def query_account(self) -> None:
        self._send_query("fund")

    def query_position(self) -> None:
        self._send_query("position")

    def query_all(self) -> None:
        for name in ("fund", "position", "order", "trade"):
            self._send_query(name)

    def _send_query(self, name: str) -> None:
        if not self.trade_connection or not self.trade_connection.send({"type": "query", "name": name}):
            self.write_log(f"ATP交易桥未连接，无法查询{name}")

    def _on_trade_connected(self, connection: JsonLineConnection) -> None:
        self.query_all()

    def _on_connection_state(self, name: str, connected: bool, detail: str) -> None:
        if name == "交易控制" and not connected:
            self.orders_enabled = False
        self.on_event(EVENT_QF_CONNECTION, {
            "name": name,
            "connected": connected,
            "detail": detail,
            "time": datetime.now(),
        })
        state = "已连接" if connected else "已断开"
        self.write_log(f"{name}{state}：{detail}")

    def _on_control_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "control_status":
            xserver_connected = bool(message.get("xserver_connected"))
            orders_enabled = bool(message.get("orders_enabled"))
            self.orders_enabled = xserver_connected and orders_enabled
            if self.orders_enabled:
                detail = "C++风控已启用"
            elif not orders_enabled:
                detail = "交易开关未开启"
            else:
                detail = "C++中间层尚未登录"
            self.on_event(EVENT_QF_CONNECTION, {
                "name": "交易控制",
                "connected": self.orders_enabled,
                "detail": detail,
                "time": datetime.now(),
            })
            self.write_log(f"交易控制状态：{detail}")
        elif message_type == "command_ack":
            self.write_log(f"C++中间层已接收{message.get('command', '')}请求")
        elif message_type == "command_error":
            self.write_log(f"交易控制拒绝请求：{message.get('error', '未知错误')}")

    def _on_market_message(self, message: dict) -> None:
        if message.get("type") != "stock_quote":
            return
        symbol = str(message.get("ticker", "")).strip()
        exchange = map_exchange(message.get("exchange", ""))
        if not symbol:
            return
        vt_symbol = f"{symbol}.{exchange.value}"
        if vt_symbol not in self.contracts:
            self.contracts.add(vt_symbol)
            self.on_contract(ContractData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange=exchange,
                name=str(message.get("name", symbol)),
                product=Product.EQUITY,
                size=1,
                pricetick=0.01,
                min_volume=100,
                net_position=True,
            ))

        timestamp = str(message.get("update_time", "00:00:00"))
        milliseconds = int(message.get("millisec", 0) or 0)
        try:
            tick_time = datetime.combine(datetime.now().date(), datetime.strptime(timestamp, "%H:%M:%S").time())
            tick_time = tick_time.replace(microsecond=milliseconds * 1000)
        except ValueError:
            tick_time = datetime.now()

        bids = list(message.get("bid_prices", [])) + [0] * 5
        asks = list(message.get("ask_prices", [])) + [0] * 5
        bid_volumes = list(message.get("bid_volumes", [])) + [0] * 5
        ask_volumes = list(message.get("ask_volumes", [])) + [0] * 5
        tick = TickData(
            gateway_name=self.gateway_name,
            symbol=symbol,
            exchange=exchange,
            datetime=tick_time,
            name=str(message.get("name", symbol)),
            last_price=float(message.get("last_price", 0) or 0),
            volume=float(message.get("volume", 0) or 0),
            turnover=float(message.get("turnover", 0) or 0),
            pre_close=float(message.get("pre_close", 0) or 0),
            open_price=float(message.get("open", 0) or 0),
            high_price=float(message.get("high", 0) or 0),
            low_price=float(message.get("low", 0) or 0),
            bid_price_1=float(bids[0] or 0), bid_price_2=float(bids[1] or 0),
            bid_price_3=float(bids[2] or 0), bid_price_4=float(bids[3] or 0),
            bid_price_5=float(bids[4] or 0), ask_price_1=float(asks[0] or 0),
            ask_price_2=float(asks[1] or 0), ask_price_3=float(asks[2] or 0),
            ask_price_4=float(asks[3] or 0), ask_price_5=float(asks[4] or 0),
            bid_volume_1=float(bid_volumes[0] or 0), bid_volume_2=float(bid_volumes[1] or 0),
            bid_volume_3=float(bid_volumes[2] or 0), bid_volume_4=float(bid_volumes[3] or 0),
            bid_volume_5=float(bid_volumes[4] or 0), ask_volume_1=float(ask_volumes[0] or 0),
            ask_volume_2=float(ask_volumes[1] or 0), ask_volume_3=float(ask_volumes[2] or 0),
            ask_volume_4=float(ask_volumes[3] or 0), ask_volume_5=float(ask_volumes[4] or 0),
            localtime=datetime.now(),
        )
        self.on_tick(tick)

    def _on_trade_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "fund":
            balance = float(message.get("balance", 0) or 0)
            available = float(message.get("available", 0) or 0)
            self.on_account(AccountData(
                gateway_name=self.gateway_name,
                accountid=self.account_id,
                balance=balance,
                frozen=max(balance - available, 0),
            ))
        elif message_type == "position":
            total = float(message.get("total", 0) or 0)
            available = float(message.get("available", 0) or 0)
            self.on_position(PositionData(
                gateway_name=self.gateway_name,
                symbol=str(message.get("ticker", "")).strip(),
                exchange=map_exchange(message.get("exchange", "")),
                direction=Direction.NET,
                volume=total,
                frozen=max(total - available, 0),
                yd_volume=float(message.get("yesterday", 0) or 0),
            ))
        elif message_type == "order_status":
            self.on_order(self._map_order(message))
        elif message_type == "command_error":
            self.write_log(f"ATP查询失败：{message.get('error', '未知错误')}")

    def _map_order(self, message: dict) -> OrderData:
        statuses = {
            "submitting": Status.SUBMITTING,
            "accepted": Status.NOTTRADED,
            "partial": Status.PARTTRADED,
            "partial_cancelled": Status.CANCELLED,
            "filled": Status.ALLTRADED,
            "cancelled": Status.CANCELLED,
            "rejected": Status.REJECTED,
        }
        side = int(message.get("side", 0) or 0)
        order_token = str(message.get("order_token") or "").strip()
        order_ref = str(message.get("order_ref") or message.get("order_sys_id") or "-").strip()
        if order_token and order_ref != "-":
            self.order_refs[order_token] = order_ref
            self.pending_order_tokens.discard(order_token)
        return OrderData(
            gateway_name=self.gateway_name,
            symbol=str(message.get("ticker", "")).strip(),
            exchange=map_exchange(message.get("exchange", "")),
            orderid=order_token or order_ref,
            type=OrderType.LIMIT,
            direction=Direction.LONG if side == 1 else Direction.SHORT,
            price=float(message.get("price", 0) or 0),
            volume=float(message.get("volume", 0) or 0),
            traded=float(message.get("traded", 0) or 0),
            status=statuses.get(str(message.get("status", "")), Status.SUBMITTING),
            datetime=datetime.now(),
            reference="QuantFabric/ATP",
        )
