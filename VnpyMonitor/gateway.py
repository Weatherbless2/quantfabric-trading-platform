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
    """vn.py 网关：当前版本只查询和展示，不开放交易动作。"""

    default_name = GATEWAY_NAME
    exchanges = [Exchange.SSE, Exchange.SZSE]
    default_setting = {
        "行情地址": "127.0.0.1",
        "行情端口": 19001,
        "交易地址": "127.0.0.1",
        "交易端口": 19002,
        "资金账号": "610000071840",
    }

    def __init__(self, event_engine, gateway_name: str) -> None:
        super().__init__(event_engine, gateway_name)
        self.account_id = "610000071840"
        self.market_connection: JsonLineConnection | None = None
        self.trade_connection: JsonLineConnection | None = None
        self.contracts: set[str] = set()

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
        self.market_connection.start()
        self.trade_connection.start()
        self.write_log("只读网关已启动：委托和撤单接口保持禁用")

    def close(self) -> None:
        for connection in (self.market_connection, self.trade_connection):
            if connection:
                connection.stop()
        self.market_connection = None
        self.trade_connection = None

    def subscribe(self, req: SubscribeRequest) -> None:
        self.write_log(f"行情由 QuantFabric 配置订阅：{req.vt_symbol}")

    def send_order(self, req: OrderRequest) -> str:
        self.write_log("只读模式禁止发送委托")
        return ""

    def cancel_order(self, req: CancelRequest) -> None:
        self.write_log("只读模式禁止撤单")

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
        self.on_event(EVENT_QF_CONNECTION, {
            "name": name,
            "connected": connected,
            "detail": detail,
            "time": datetime.now(),
        })
        state = "已连接" if connected else "已断开"
        self.write_log(f"{name}{state}：{detail}")

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
                name=symbol,
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
            name=symbol,
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
        return OrderData(
            gateway_name=self.gateway_name,
            symbol=str(message.get("ticker", "")).strip(),
            exchange=map_exchange(message.get("exchange", "")),
            orderid=str(message.get("order_ref") or message.get("order_sys_id") or "-").strip(),
            type=OrderType.LIMIT,
            direction=Direction.LONG if side == 1 else Direction.SHORT,
            price=float(message.get("price", 0) or 0),
            volume=float(message.get("volume", 0) or 0),
            traded=float(message.get("traded", 0) or 0),
            status=statuses.get(str(message.get("status", "")), Status.SUBMITTING),
            datetime=datetime.now(),
            reference="QuantFabric/ATP",
        )
