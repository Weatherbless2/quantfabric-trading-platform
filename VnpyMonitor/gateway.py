"""QuantFabric 的 vn.py 网关。

界面只负责 vn.py 标准对象和事件分发；网络会话由 quantfabric_native
直接调用 XServer 的 PackMessage 二进制协议，订单仍经过 C++ 风控链路。
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from vnpy.event import EVENT_TIMER
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


def _load_native_client():
    """优先加载构建目录中的本机模块，避免复制或启动额外的桥进程。"""
    try:
        from quantfabric_native import QuantFabricClient
        return QuantFabricClient
    except ImportError:
        build_dir = Path(__file__).resolve().parents[1] / "build"
        if str(build_dir) not in sys.path:
            sys.path.insert(0, str(build_dir))
        from quantfabric_native import QuantFabricClient
        return QuantFabricClient


QuantFabricClient = _load_native_client()
EVENT_QF_CONNECTION = "eQuantFabricConnection"
GATEWAY_NAME = "QUANTFABRIC"
REPO_ROOT = Path(__file__).resolve().parents[1]
SECURITY_MASTER_PATH = REPO_ROOT / "runtime" / "data" / "security_master.json"
AUTH_SESSION_ID_LENGTH = 30


def create_auth_session(service_url: str, username: str, password: str,
                        oidc_access_token: str = "") -> str:
    """用桌面凭据或现有 OIDC access token 换取 XServer 可承载的短会话。"""
    base_url = service_url.rstrip("/")
    if not base_url:
        raise RuntimeError("认证服务地址不能为空")
    if oidc_access_token.strip():
        endpoint = "/v1/sessions/oidc"
        payload = {"access_token": oidc_access_token.strip()}
    else:
        endpoint = "/v1/sessions/development"
        payload = {"username": username, "password": password}
    request = Request(
        base_url + endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"认证服务拒绝登录（HTTP {exc.code}）：{detail}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"认证服务不可用：{exc}") from exc
    session_id = data.get("session_id") if isinstance(data, dict) else None
    if not isinstance(session_id, str) or len(session_id) != AUTH_SESSION_ID_LENGTH:
        raise RuntimeError("认证服务返回了无效会话")
    return session_id


def order_trace_id(account: str, order_token: str | int, order_ref: str = "") -> str:
    """生成与 C++ 日志一致的订单关联标识。"""
    token = str(order_token or "").strip()
    if token and token != "0":
        return f"QF-{account}-{token}"
    return f"QF-{account}-REF-{order_ref or 'UNKNOWN'}"


def load_security_master() -> list[dict]:
    """加载行情适配器生成的证券主数据；服务未启动时退回默认观察列表。"""
    paths = [SECURITY_MASTER_PATH, REPO_ROOT / "runtime" / "config" / "PyTdxBridge.json"]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        securities = data if isinstance(data, list) else data.get("securities", [])
        if securities:
            return securities
    return []


def map_exchange(value: str) -> Exchange:
    aliases = {
        "SH": Exchange.SSE,
        "SSE": Exchange.SSE,
        "SZ": Exchange.SZSE,
        "SZSE": Exchange.SZSE,
    }
    return aliases.get(str(value).strip().upper(), Exchange.LOCAL)


class QuantFabricGateway(BaseGateway):
    """把 C++ PackMessage 事件映射为 vn.py 标准行情和交易对象。"""

    default_name = GATEWAY_NAME
    exchanges = [Exchange.SSE, Exchange.SZSE]
    default_setting = {
        "XServer地址": "127.0.0.1",
        "XServer端口": 8000,
        "用户": "admin",
        "密码": "123456",
        "交易机房": "LocalTest",
        # The checked-in desktop defaults are intentionally bound to the
        # local TestTrader chain. Production account details are configured
        # only after the broker integration has passed its separate review.
        "交易产品": "Test",
        "资金账号": "188795",
        "认证服务地址": "http://127.0.0.1:18080",
        "OIDC访问令牌": "",
    }

    def __init__(self, event_engine, gateway_name: str) -> None:
        super().__init__(event_engine, gateway_name)
        self.account_id = self.default_setting["资金账号"]
        self.native_client = None
        self.contracts: set[str] = set()
        self.orders_enabled = False
        self.order_token = 0
        self.order_refs: dict[str, str] = {}
        self.pending_order_tokens: set[str] = set()
        self.security_master = load_security_master()
        self.security_names = {
            f"{item['ticker']}.{item['exchange']}": item.get("name", item["ticker"])
            for item in self.security_master
        }
        self.requested_subscriptions: dict[str, SubscribeRequest] = {}
        self.sent_subscriptions: set[str] = set()
        self.received_quotes: set[str] = set()
        self._last_session_state = (False, False)
        self._next_login_at = 0.0
        self._next_session_refresh_at = 0.0
        self._next_auth_retry_at = 0.0
        self._connection_setting: dict | None = None

    def connect(self, setting: dict) -> None:
        if self.native_client:
            return
        self.account_id = str(setting.get("资金账号", self.account_id))
        self._connection_setting = dict(setting)
        self.event_engine.register(EVENT_TIMER, self._on_timer)
        self._open_authenticated_connection()
        self._publish_contracts()
        self._publish_connection_state()

    def _open_authenticated_connection(self) -> None:
        if not self._connection_setting:
            return
        setting = self._connection_setting
        try:
            session_id = create_auth_session(
                str(setting.get("认证服务地址", self.default_setting["认证服务地址"])),
                str(setting.get("用户", "admin")),
                str(setting.get("密码", "")),
                str(setting.get("OIDC访问令牌", "")),
            )
        except RuntimeError as exc:
            self._next_auth_retry_at = time.monotonic() + 15.0
            self.write_log(f"认证会话创建失败：{exc}")
            return

        previous_client = self.native_client
        if previous_client:
            previous_client.stop()
        self.native_client = QuantFabricClient(
            str(setting.get("XServer地址", "127.0.0.1")),
            int(setting.get("XServer端口", 8000)),
            str(setting.get("用户", "admin")),
            str(setting.get("密码", "123456")),
            session_id,
            str(setting.get("交易机房", "LocalTest")),
            str(setting.get("交易产品", "ATPTest")),
            self.account_id,
        )
        if not self.native_client.start():
            self.write_log(f"XServer 连接失败：{self.native_client.last_error}")
        else:
            # The auth session is deliberately renewed before its 15-minute
            # server lifetime ends, which keeps a running desktop usable.
            self._next_session_refresh_at = time.monotonic() + 600.0
            self._next_auth_retry_at = 0.0
            self.sent_subscriptions.clear()
            self.received_quotes.clear()
            self.write_log("已启动已鉴权 C++ 原生会话：vn.py -> PackMessage -> XServer")

    def close(self) -> None:
        self.event_engine.unregister(EVENT_TIMER, self._on_timer)
        if self.native_client:
            self.native_client.stop()
        self.native_client = None
        self._connection_setting = None
        self.orders_enabled = False
        self._publish_connection_state()

    def subscribe(self, req: SubscribeRequest) -> None:
        if req.exchange not in self.exchanges or req.vt_symbol not in self.security_names:
            self.write_log(f"证券主数据中不存在：{req.vt_symbol}")
            return
        self.requested_subscriptions[req.vt_symbol] = req
        self._flush_subscriptions()

    def send_order(self, req: OrderRequest) -> str:
        if not self.orders_enabled or not self.native_client:
            self.write_log("C++ 风控会话未就绪，委托未发送")
            return ""
        if req.type is not OrderType.LIMIT or req.direction not in (Direction.LONG, Direction.SHORT):
            self.write_log("当前仅支持普通股票限价买入和卖出")
            return ""
        if req.vt_symbol not in self.security_names:
            self.write_log(f"证券主数据中不存在，委托未发送：{req.vt_symbol}")
            return ""
        if req.vt_symbol not in self.received_quotes:
            self.write_log(f"当前标的尚未收到有效行情，委托未发送：{req.vt_symbol}")
            return ""
        volume = int(req.volume)
        if req.price <= 0 or volume <= 0 or volume % 100:
            self.write_log("价格必须大于 0，数量必须是 100 股的整数倍")
            return ""

        self.order_token += 1
        orderid = str(self.order_token)
        sent = self.native_client.send_order(
            req.symbol,
            req.exchange.value,
            1 if req.direction is Direction.LONG else 2,
            float(req.price),
            volume,
            self.order_token,
        )
        if not sent:
            self.write_log(f"C++ 风控拒绝委托：{self.native_client.last_error}")
            return ""
        self.pending_order_tokens.add(orderid)
        self.on_order(req.create_order_data(orderid, self.gateway_name))
        trace_id = order_trace_id(self.account_id, orderid)
        self.write_log(
            f"TraceID={trace_id} Stage=VnpySubmit 委托已提交 C++ 风控："
            f"{req.symbol} {req.price} x {volume}"
        )
        return f"{self.gateway_name}.{orderid}"

    def cancel_order(self, req: CancelRequest) -> None:
        if not self.orders_enabled or not self.native_client:
            self.write_log("C++ 风控会话未就绪，撤单未发送")
            return
        if req.orderid in self.pending_order_tokens:
            self.write_log("委托尚未取得 ATP 委托号，请稍后再撤")
            return
        order_ref = self.order_refs.get(req.orderid, req.orderid)
        if self.native_client.cancel_order(order_ref, req.exchange.value):
            trace_id = order_trace_id(self.account_id, 0, order_ref)
            parent_trace_id = order_trace_id(self.account_id, req.orderid)
            self.write_log(
                f"TraceID={trace_id} ParentTraceID={parent_trace_id} "
                f"Stage=VnpyCancel 撤单已提交 C++ 风控：{order_ref}"
            )
        else:
            self.write_log(f"撤单发送失败：{self.native_client.last_error}")

    def query_account(self) -> None:
        self.write_log("资金由 XTrader 通过 XServer 持续推送，无需旁路查询柜台")

    def query_position(self) -> None:
        self.write_log("持仓由 XTrader 通过 XServer 持续推送，无需旁路查询柜台")

    def query_all(self) -> None:
        self.query_account()
        self.query_position()

    def _on_timer(self, event) -> None:
        if not self.native_client and self._connection_setting and time.monotonic() >= self._next_auth_retry_at:
            self._open_authenticated_connection()
        if not self.native_client:
            return
        for message in self.native_client.poll():
            self._on_native_message(message)
        if time.monotonic() >= self._next_session_refresh_at:
            self._open_authenticated_connection()
            self._publish_connection_state()
            return
        if not self.native_client.is_connected():
            self.sent_subscriptions.clear()
            self.received_quotes.clear()
            self.native_client.reconnect()
        elif not self.native_client.is_logged_in() and time.monotonic() >= self._next_login_at:
            # The native client retries only the compact login packet. This
            # keeps TCP reconnection and authentication failures independent.
            # Limit retries so a bad credential cannot flood XServer logs.
            self.native_client.login()
            self._next_login_at = time.monotonic() + 3.0
        self._flush_subscriptions()
        self._publish_connection_state()

    def _flush_subscriptions(self) -> None:
        if not self.native_client or not self.native_client.is_logged_in():
            return
        for vt_symbol, request in self.requested_subscriptions.items():
            if vt_symbol in self.sent_subscriptions:
                continue
            if self.native_client.subscribe(request.symbol, request.exchange.value):
                self.sent_subscriptions.add(vt_symbol)
                self.write_log(f"行情订阅请求已发送，等待首笔报价：{vt_symbol}")
            else:
                self.write_log(f"行情订阅失败：{vt_symbol}，{self.native_client.last_error}")

    def _publish_contracts(self) -> None:
        for item in self.security_master:
            exchange = map_exchange(item.get("exchange", ""))
            symbol = str(item.get("ticker", "")).strip()
            if not symbol or exchange is Exchange.LOCAL:
                continue
            self.contracts.add(f"{symbol}.{exchange.value}")
            self.on_contract(ContractData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange=exchange,
                name=str(item.get("name", symbol)),
                product=Product.EQUITY,
                size=1,
                pricetick=0.01,
                min_volume=float(item.get("lot_size", 100) or 100),
                net_position=True,
            ))

    def _publish_connection_state(self) -> None:
        connected = bool(self.native_client and self.native_client.is_connected())
        logged_in = bool(self.native_client and self.native_client.is_logged_in())
        self.orders_enabled = connected and logged_in
        if connected and logged_in:
            detail = "XServer 已登录，C++ 风控在线"
        elif connected:
            detail = "已连接 XServer，正在登录"
        else:
            detail = "XServer 未连接"
        session_state = (connected, logged_in)
        if not connected:
            self.sent_subscriptions.clear()
        if session_state != self._last_session_state:
            self.on_event(EVENT_QF_CONNECTION, {
                "name": "C++原生会话",
                # Only enable an order button after the XServer permission
                # response has completed; a bare TCP connection is not enough.
                "connected": connected and logged_in,
                "tcp_connected": connected,
                "detail": detail,
                "time": datetime.now(),
            })
            self.write_log(f"{detail}")
            self._last_session_state = session_state

    def _on_native_message(self, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "login":
            if not message.get("connected"):
                self.write_log(f"XServer 登录失败：{message.get('error', '未知错误')}")
                # A rejected login can mean that AuthAdminService was restarted
                # and lost a local development session. Renew it immediately
                # instead of retrying the same opaque identifier for 10 minutes.
                self._next_session_refresh_at = 0.0
            return
        if message_type == "stock_quote":
            self._on_market_message(message)
        elif message_type in {"fund", "position", "order_status"}:
            self._on_trade_message(message)
        elif message_type == "event_log":
            self.write_log(f"{message.get('app', 'QuantFabric')}：{message.get('message', '')}")

    def _on_market_message(self, message: dict) -> None:
        symbol = str(message.get("ticker", "")).strip()
        exchange = map_exchange(message.get("exchange", ""))
        if not symbol or exchange is Exchange.LOCAL:
            return
        vt_symbol = f"{symbol}.{exchange.value}"
        if vt_symbol not in self.received_quotes:
            self.received_quotes.add(vt_symbol)
            self.write_log(f"实时行情已就绪：{vt_symbol}")
        name = self.security_names.get(vt_symbol, symbol)
        if vt_symbol not in self.contracts:
            self.contracts.add(vt_symbol)
            self.on_contract(ContractData(
                gateway_name=self.gateway_name,
                symbol=symbol,
                exchange=exchange,
                name=name,
                product=Product.EQUITY,
                size=1,
                pricetick=0.01,
                min_volume=100,
                net_position=True,
            ))
        timestamp = str(message.get("update_time", ""))
        try:
            tick_time = datetime.strptime(timestamp, "%H:%M:%S")
            tick_time = datetime.combine(datetime.now().date(), tick_time.time())
        except ValueError:
            tick_time = datetime.now()
        bids = list(message.get("bid_prices", [])) + [0] * 5
        asks = list(message.get("ask_prices", [])) + [0] * 5
        bid_volumes = list(message.get("bid_volumes", [])) + [0] * 5
        ask_volumes = list(message.get("ask_volumes", [])) + [0] * 5
        self.on_tick(TickData(
            gateway_name=self.gateway_name,
            symbol=symbol,
            exchange=exchange,
            datetime=tick_time,
            name=name,
            last_price=float(message.get("last_price", 0) or 0),
            volume=float(message.get("volume", 0) or 0),
            turnover=float(message.get("turnover", 0) or 0),
            pre_close=float(message.get("pre_close", 0) or 0),
            open_price=float(message.get("open", 0) or 0),
            high_price=float(message.get("high", 0) or 0),
            low_price=float(message.get("low", 0) or 0),
            bid_price_1=float(bids[0]), bid_price_2=float(bids[1]), bid_price_3=float(bids[2]),
            bid_price_4=float(bids[3]), bid_price_5=float(bids[4]), ask_price_1=float(asks[0]),
            ask_price_2=float(asks[1]), ask_price_3=float(asks[2]), ask_price_4=float(asks[3]),
            ask_price_5=float(asks[4]), bid_volume_1=float(bid_volumes[0]), bid_volume_2=float(bid_volumes[1]),
            bid_volume_3=float(bid_volumes[2]), bid_volume_4=float(bid_volumes[3]), bid_volume_5=float(bid_volumes[4]),
            ask_volume_1=float(ask_volumes[0]), ask_volume_2=float(ask_volumes[1]), ask_volume_3=float(ask_volumes[2]),
            ask_volume_4=float(ask_volumes[3]), ask_volume_5=float(ask_volumes[4]), localtime=datetime.now(),
        ))

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
            order = self._map_order(message)
            self.on_order(order)
            trace_id = order_trace_id(
                self.account_id,
                message.get("order_token", ""),
                str(message.get("order_ref", "")),
            )
            self.write_log(
                f"TraceID={trace_id} Stage=VnpyOrderStatus Status={message.get('status', 'unknown')} "
                f"OrderRef={message.get('order_ref', '') or '-'} ErrorID={message.get('error_id', 0)}"
            )

    def _map_order(self, message: dict) -> OrderData:
        statuses = {
            "submitting": Status.SUBMITTING,
            "accepted": Status.NOTTRADED,
            "partial": Status.PARTTRADED,
            "partial_cancelled": Status.CANCELLED,
            "filled": Status.ALLTRADED,
            "cancelling": Status.SUBMITTING,
            "cancelled": Status.CANCELLED,
            "rejected": Status.REJECTED,
        }
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
            direction=Direction.LONG if int(message.get("side", 0) or 0) == 1 else Direction.SHORT,
            price=float(message.get("price", 0) or 0),
            volume=float(message.get("volume", 0) or 0),
            traded=float(message.get("traded", 0) or 0),
            status=statuses.get(str(message.get("status", "")), Status.SUBMITTING),
            datetime=datetime.now(),
            reference="QuantFabric/XServer",
        )
