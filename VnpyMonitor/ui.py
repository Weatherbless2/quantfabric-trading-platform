"""QuantFabric 的 vn.py 桌面工作台。"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from vnpy.event import Event
from vnpy.trader.constant import Direction, Exchange, Offset, OrderType
from vnpy.trader.event import EVENT_ACCOUNT, EVENT_TICK
from vnpy.trader.object import OrderRequest
from vnpy.trader.ui import QtCore, QtGui, QtWidgets
from vnpy.trader.ui.widget import AccountMonitor, LogMonitor, OrderMonitor, PositionMonitor, TickMonitor

from .gateway import EVENT_QF_CONNECTION, GATEWAY_NAME, QuantFabricGateway


ROOT_DIR = Path(__file__).resolve().parents[1]


STYLE = """
QWidget { color: #17202a; font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; font-size: 13px; }
QMainWindow, #central { background: #f4f6f8; }
#header { background: #ffffff; border-bottom: 1px solid #dfe4ea; }
#brand { font-size: 19px; font-weight: 700; color: #17202a; }
#subBrand { color: #68717d; }
#statusOnline { color: #166534; background: #e8f5ec; border: 1px solid #b9dfc5; border-radius: 4px; padding: 5px 9px; }
#statusOffline { color: #991b1b; background: #fce8e8; border: 1px solid #efb5b5; border-radius: 4px; padding: 5px 9px; }
#panel { background: #ffffff; border: 1px solid #dfe4ea; border-radius: 6px; }
#panelTitle { font-size: 15px; font-weight: 700; color: #27313c; }
#metricLabel { color: #68717d; }
#metricValue { font-size: 21px; font-weight: 700; color: #17202a; }
#positive { color: #c0392b; font-weight: 700; }
#negative { color: #16825d; font-weight: 700; }
#buyButton { color: #ffffff; background: #c0392b; border-color: #a93226; font-weight: 700; }
#sellButton { color: #ffffff; background: #16825d; border-color: #116b4d; font-weight: 700; }
#buyButton:disabled, #sellButton:disabled { color: #707780; background: #e1e5e9; border-color: #c9cfd5; }
QPushButton { background: #ffffff; border: 1px solid #cfd6de; border-radius: 4px; padding: 7px 12px; }
QPushButton:hover { background: #edf5f7; border-color: #4f8694; }
QTabWidget::pane { background: #ffffff; border: 1px solid #dfe4ea; }
QTabBar::tab { background: #e9edf1; padding: 9px 18px; border: 1px solid #dfe4ea; border-bottom: none; }
QTabBar::tab:selected { background: #ffffff; color: #0b6574; font-weight: 700; }
QTableWidget { background: #ffffff; alternate-background-color: #f7f9fa; border: none; gridline-color: #e7ebef; selection-background-color: #d8ebef; }
QHeaderView::section { background: #eef2f4; color: #4d5966; border: none; border-right: 1px solid #dfe4ea; border-bottom: 1px solid #dfe4ea; padding: 7px; font-weight: 600; }
QScrollBar:vertical { width: 10px; background: #eef1f3; }
QScrollBar::handle:vertical { background: #b7c1ca; min-height: 24px; border-radius: 4px; }
"""


class Metric(QtWidgets.QWidget):
    def __init__(self, title: str, value: str = "--") -> None:
        super().__init__()
        self.setObjectName("panel")
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("metricLabel")
        self.value = QtWidgets.QLabel(value)
        self.value.setObjectName("metricValue")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.value)


class OrderBookWidget(QtWidgets.QWidget):
    signal_tick = QtCore.Signal(Event)

    def __init__(self, event_engine) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.selected_vt_symbol = "300007.SZSE"
        self.ticks = {}
        self.table = QtWidgets.QTableWidget(10, 3)
        self.table.setHorizontalHeaderLabels(["档位", "价格", "数量"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setMinimumSectionSize(16)
        self.table.verticalHeader().setDefaultSectionSize(17)
        self.table.horizontalHeader().setFixedHeight(25)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.addWidget(self.table)
        self.signal_tick.connect(self.update_tick)
        event_engine.register(EVENT_TICK, self.signal_tick.emit)

    def update_tick(self, event: Event) -> None:
        tick = event.data
        self.ticks[tick.vt_symbol] = tick
        if tick.vt_symbol != self.selected_vt_symbol:
            return
        self._render_tick(tick)

    def set_symbol(self, vt_symbol: str) -> None:
        self.selected_vt_symbol = vt_symbol
        tick = self.ticks.get(vt_symbol)
        if tick:
            self._render_tick(tick)

    def _render_tick(self, tick) -> None:
        rows = []
        for level in range(5, 0, -1):
            rows.append((f"卖{level}", getattr(tick, f"ask_price_{level}"), getattr(tick, f"ask_volume_{level}"), "#16825d"))
        for level in range(1, 6):
            rows.append((f"买{level}", getattr(tick, f"bid_price_{level}"), getattr(tick, f"bid_volume_{level}"), "#c0392b"))
        for row, (name, price, volume, color) in enumerate(rows):
            for column, value in enumerate((name, f"{price:.2f}", f"{volume:,.0f}")):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if column < 2:
                    item.setForeground(QtGui.QColor(color))
                self.table.setItem(row, column, item)


class ServiceTable(QtWidgets.QTableWidget):
    SERVICES = {
        "ATPBridge": "ATP 柜台桥",
        "PyTdxBridge": "通达信行情桥",
        "XServer": "消息服务",
        "XVnpyBridge": "交易控制桥",
        "XWatcher": "监控服务",
        "XRiskJudge": "风控服务",
        "XTrader": "交易路由",
        "XMarketCenter": "行情中心",
        "XQuant": "策略引擎",
    }

    def __init__(self) -> None:
        super().__init__(0, 4)
        self.setHorizontalHeaderLabels(["服务", "职责", "状态", "进程号"])
        self.verticalHeader().hide()
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.horizontalHeader().setSectionResizeMode(self.horizontalHeader().ResizeMode.Stretch)
        self.refresh()

    def refresh(self) -> None:
        self.setRowCount(0)
        pid_dir = ROOT_DIR / "runtime" / "pids"
        for name, description in self.SERVICES.items():
            pid_file = pid_dir / f"{name}.pid"
            pid = pid_file.read_text().strip() if pid_file.exists() else ""
            running = False
            if pid.isdigit():
                try:
                    os.kill(int(pid), 0)
                    running = True
                except OSError:
                    pass
            row = self.rowCount()
            self.insertRow(row)
            values = (name, description, "运行中" if running else "未运行", pid or "--")
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if column == 2:
                    item.setForeground(QtGui.QColor("#16825d" if running else "#b42318"))
                self.setItem(row, column, item)


class ConfirmingOrderMonitor(OrderMonitor):
    """复用 vn.py 委托表，并在撤单前增加明确确认。"""

    def cancel_order(self, cell) -> None:
        order = cell.get_data()
        answer = QtWidgets.QMessageBox.question(
            self,
            "确认撤单",
            f"确认撤销委托 {order.orderid}（{order.symbol}）？",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            super().cancel_order(cell)


class TradingPanel(QtWidgets.QWidget):
    def __init__(self, main_engine) -> None:
        super().__init__()
        self.main_engine = main_engine
        self.vt_symbol = "300007.SZSE"
        self.setObjectName("panel")

        title = QtWidgets.QLabel("普通股票委托")
        title.setObjectName("panelTitle")
        self.symbol = QtWidgets.QLabel("300007 · SZSE")
        self.price = QtWidgets.QDoubleSpinBox()
        self.price.setDecimals(2)
        self.price.setRange(0.01, 1000000)
        self.price.setSingleStep(0.01)
        self.price.setSuffix(" 元")
        self.volume = QtWidgets.QSpinBox()
        self.volume.setRange(100, 100000000)
        self.volume.setSingleStep(100)
        self.volume.setValue(100)
        self.volume.setSuffix(" 股")
        self.state = QtWidgets.QLabel("交易控制连接中")
        self.state.setObjectName("statusOffline")

        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.symbol)

        form = QtWidgets.QHBoxLayout()
        form.addWidget(QtWidgets.QLabel("限价"))
        form.addWidget(self.price, 1)
        form.addWidget(QtWidgets.QLabel("数量"))
        form.addWidget(self.volume, 1)

        self.buy_button = QtWidgets.QPushButton("买入")
        self.buy_button.setObjectName("buyButton")
        self.sell_button = QtWidgets.QPushButton("卖出")
        self.sell_button.setObjectName("sellButton")
        self.buy_button.clicked.connect(lambda: self.send_order(Direction.LONG))
        self.sell_button.clicked.connect(lambda: self.send_order(Direction.SHORT))
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(self.buy_button)
        buttons.addWidget(self.sell_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)
        layout.addLayout(heading)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.state)
        self.setMaximumHeight(170)
        self.set_trading_enabled(False)

    def set_symbol(self, vt_symbol: str, tick=None) -> None:
        changed = self.vt_symbol != vt_symbol
        self.vt_symbol = vt_symbol
        symbol, exchange = vt_symbol.rsplit(".", 1)
        self.symbol.setText(f"{symbol} · {exchange}")
        if tick and tick.last_price > 0 and (changed or self.price.value() <= 0.01):
            self.price.setValue(tick.last_price)

    def set_trading_enabled(self, enabled: bool) -> None:
        self.buy_button.setEnabled(enabled)
        self.sell_button.setEnabled(enabled)
        self.state.setText("C++风控已启用" if enabled else "交易控制不可用")
        self.state.setObjectName("statusOnline" if enabled else "statusOffline")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def send_order(self, direction: Direction) -> None:
        symbol, exchange_value = self.vt_symbol.rsplit(".", 1)
        exchange = Exchange(exchange_value)
        side = "买入" if direction is Direction.LONG else "卖出"
        price = self.price.value()
        volume = self.volume.value()
        answer = QtWidgets.QMessageBox.question(
            self,
            "确认委托",
            f"{side} {symbol}，限价 {price:.2f}，数量 {volume} 股？\n订单将经过 C++ 风控后发送至 ATP 柜台。",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        request = OrderRequest(
            symbol=symbol,
            exchange=exchange,
            direction=direction,
            type=OrderType.LIMIT,
            volume=volume,
            price=price,
            offset=Offset.NONE,
            reference="vn.py手工委托",
        )
        vt_orderid = self.main_engine.send_order(request, GATEWAY_NAME)
        if not vt_orderid:
            QtWidgets.QMessageBox.warning(self, "委托未发送", "交易控制未就绪或委托参数无效。")


class WorkbenchWindow(QtWidgets.QMainWindow):
    signal_tick = QtCore.Signal(Event)
    signal_account = QtCore.Signal(Event)
    signal_connection = QtCore.Signal(Event)

    def __init__(self, main_engine, event_engine) -> None:
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.ticks = {}
        self.setWindowTitle("QuantFabric 交易工作台 - vn.py")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        self._register_events()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._create_header())

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(18, 14, 18, 16)
        content_layout.setSpacing(12)
        root.addWidget(content, 1)

        metrics = QtWidgets.QHBoxLayout()
        self.last_price = Metric("300007 最新价")
        self.change = Metric("涨跌幅")
        self.balance = Metric("账户总资产")
        self.available = Metric("可用资金")
        for widget in (self.last_price, self.change, self.balance, self.available):
            metrics.addWidget(widget)
        content_layout.addLayout(metrics)

        market_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.tick_monitor = TickMonitor(self.main_engine, self.event_engine)
        self.tick_monitor.setObjectName("panel")
        self.tick_monitor.setMinimumWidth(720)
        self.tick_monitor.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        market_split.addWidget(self.tick_monitor)
        self.order_book = OrderBookWidget(self.event_engine)
        right_column = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        right_layout.addWidget(self.order_book, 1)
        self.trading_panel = TradingPanel(self.main_engine)
        right_layout.addWidget(self.trading_panel)
        market_split.addWidget(right_column)
        market_split.setSizes([1000, 360])
        content_layout.addWidget(market_split, 5)

        tabs = QtWidgets.QTabWidget()
        self.account_monitor = AccountMonitor(self.main_engine, self.event_engine)
        self.position_monitor = PositionMonitor(self.main_engine, self.event_engine)
        self.order_monitor = ConfirmingOrderMonitor(self.main_engine, self.event_engine)
        self.log_monitor = LogMonitor(self.main_engine, self.event_engine)
        for monitor in (
            self.account_monitor,
            self.position_monitor,
            self.order_monitor,
            self.log_monitor,
        ):
            monitor.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
            monitor.horizontalHeader().setStretchLastSection(True)
        self.service_table = ServiceTable()
        tabs.addTab(self.account_monitor, "资金")
        tabs.addTab(self.position_monitor, "持仓")
        tabs.addTab(self.order_monitor, "委托")
        tabs.addTab(self.service_table, "服务状态")
        tabs.addTab(self.log_monitor, "运行日志")
        content_layout.addWidget(tabs, 4)

        timer = QtCore.QTimer(self)
        timer.timeout.connect(self.service_table.refresh)
        timer.start(3000)
        self.service_timer = timer

    def _create_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        header.setObjectName("header")
        header.setFixedHeight(64)
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(18, 0, 18, 0)
        brand = QtWidgets.QLabel("QuantFabric")
        brand.setObjectName("brand")
        subtitle = QtWidgets.QLabel("vn.py 交易工作台")
        subtitle.setObjectName("subBrand")
        self.trading_mode = QtWidgets.QLabel("交易控制连接中")
        self.trading_mode.setObjectName("statusOffline")
        self.market_status = QtWidgets.QLabel("行情桥连接中")
        self.market_status.setObjectName("statusOffline")
        self.trade_status = QtWidgets.QLabel("ATP桥连接中")
        self.trade_status.setObjectName("statusOffline")
        self.server_status = QtWidgets.QLabel("中间层检测中")
        self.server_status.setObjectName("statusOffline")
        self.symbol_selector = QtWidgets.QComboBox()
        self.symbol_selector.setMinimumWidth(210)
        self.symbol_selector.addItem("300007 汉威科技 · SZSE", "300007.SZSE")
        self.symbol_selector.currentIndexChanged.connect(self._select_symbol)
        refresh = QtWidgets.QPushButton("刷新账户")
        refresh.setToolTip("重新查询 ATP 资金、持仓、委托和成交")
        refresh.clicked.connect(self.refresh_account)
        layout.addWidget(brand)
        layout.addWidget(subtitle)
        layout.addSpacing(16)
        layout.addWidget(self.trading_mode)
        layout.addStretch()
        layout.addWidget(self.market_status)
        layout.addWidget(self.trade_status)
        layout.addWidget(self.server_status)
        layout.addWidget(self.symbol_selector)
        layout.addWidget(refresh)

        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._check_xserver)
        timer.start(2000)
        self.server_timer = timer
        self._check_xserver()
        return header

    def _register_events(self) -> None:
        self.signal_tick.connect(self._update_tick_metrics)
        self.signal_account.connect(self._update_account_metrics)
        self.signal_connection.connect(self._update_connection)
        self.event_engine.register(EVENT_TICK, self.signal_tick.emit)
        self.event_engine.register(EVENT_ACCOUNT, self.signal_account.emit)
        self.event_engine.register(EVENT_QF_CONNECTION, self.signal_connection.emit)

    def _update_tick_metrics(self, event: Event) -> None:
        tick = event.data
        self.ticks[tick.vt_symbol] = tick
        if self.symbol_selector.findData(tick.vt_symbol) < 0:
            display = f"{tick.symbol} {tick.name} · {tick.exchange.value}"
            self.symbol_selector.addItem(display, tick.vt_symbol)
        if self.symbol_selector.currentData() != tick.vt_symbol:
            return
        self.trading_panel.set_symbol(tick.vt_symbol, tick)
        self._render_tick_metrics(tick)

    def _render_tick_metrics(self, tick) -> None:
        self.last_price.title.setText(f"{tick.symbol} {tick.name} 最新价")
        self.last_price.value.setText(f"{tick.last_price:,.2f}")
        change = ((tick.last_price / tick.pre_close) - 1) * 100 if tick.pre_close else 0
        self.change.value.setText(f"{change:+.2f}%")
        self.change.value.setObjectName("positive" if change >= 0 else "negative")
        self.change.value.style().unpolish(self.change.value)
        self.change.value.style().polish(self.change.value)

    def _select_symbol(self) -> None:
        vt_symbol = self.symbol_selector.currentData()
        if not vt_symbol:
            return
        self.order_book.set_symbol(vt_symbol)
        tick = self.ticks.get(vt_symbol)
        self.trading_panel.set_symbol(vt_symbol, tick)
        if tick:
            self._render_tick_metrics(tick)

    def _update_account_metrics(self, event: Event) -> None:
        account = event.data
        self.balance.value.setText(f"¥ {account.balance:,.2f}")
        self.available.value.setText(f"¥ {account.available:,.2f}")

    def _update_connection(self, event: Event) -> None:
        data = event.data
        if data["name"] == "交易控制":
            enabled = bool(data["connected"])
            self.trading_panel.set_trading_enabled(enabled)
            self.trading_mode.setText("交易模式 · C++风控" if enabled else "交易控制不可用")
            self.trading_mode.setObjectName("statusOnline" if enabled else "statusOffline")
            self.trading_mode.style().unpolish(self.trading_mode)
            self.trading_mode.style().polish(self.trading_mode)
            return
        label = self.market_status if data["name"] == "行情桥" else self.trade_status
        label.setText(f"{data['name']} {'在线' if data['connected'] else '离线'}")
        label.setObjectName("statusOnline" if data["connected"] else "statusOffline")
        label.style().unpolish(label)
        label.style().polish(label)

    def _check_xserver(self) -> None:
        connected = False
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=0.15):
                connected = True
        except OSError:
            pass
        self.server_status.setText(f"C++中间层 {'在线' if connected else '离线'}")
        self.server_status.setObjectName("statusOnline" if connected else "statusOffline")
        self.server_status.style().unpolish(self.server_status)
        self.server_status.style().polish(self.server_status)

    def refresh_account(self) -> None:
        gateway = self.main_engine.get_gateway(GATEWAY_NAME)
        if isinstance(gateway, QuantFabricGateway):
            gateway.query_all()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.main_engine.close()
        event.accept()
