"""QuantFabric 的 vn.py 桌面工作台。"""

from __future__ import annotations

import os
import socket
from pathlib import Path

from vnpy.event import Event
from vnpy.trader.event import EVENT_ACCOUNT, EVENT_TICK
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
#readonly { color: #8a5200; background: #fff3d6; border: 1px solid #efcf87; border-radius: 4px; padding: 5px 9px; }
#statusOnline { color: #166534; background: #e8f5ec; border: 1px solid #b9dfc5; border-radius: 4px; padding: 5px 9px; }
#statusOffline { color: #991b1b; background: #fce8e8; border: 1px solid #efb5b5; border-radius: 4px; padding: 5px 9px; }
#panel { background: #ffffff; border: 1px solid #dfe4ea; border-radius: 6px; }
#panelTitle { font-size: 15px; font-weight: 700; color: #27313c; }
#metricLabel { color: #68717d; }
#metricValue { font-size: 21px; font-weight: 700; color: #17202a; }
#positive { color: #c0392b; font-weight: 700; }
#negative { color: #16825d; font-weight: 700; }
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
        title = QtWidgets.QLabel("五档盘口")
        title.setObjectName("panelTitle")
        self.table = QtWidgets.QTableWidget(10, 3)
        self.table.setHorizontalHeaderLabels(["档位", "价格", "数量"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(title)
        layout.addWidget(self.table)
        self.signal_tick.connect(self.update_tick)
        event_engine.register(EVENT_TICK, self.signal_tick.emit)

    def update_tick(self, event: Event) -> None:
        tick = event.data
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


class ReadOnlyOrderMonitor(OrderMonitor):
    """复用 vn.py 委托表，但明确关闭双击撤单入口。"""

    def init_ui(self) -> None:
        super().init_ui()
        self.itemDoubleClicked.disconnect(self.cancel_order)
        self.setToolTip("只读模式：委托仅用于查看")


class WorkbenchWindow(QtWidgets.QMainWindow):
    signal_tick = QtCore.Signal(Event)
    signal_account = QtCore.Signal(Event)
    signal_connection = QtCore.Signal(Event)

    def __init__(self, main_engine, event_engine) -> None:
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
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
        market_split.addWidget(self.order_book)
        market_split.setSizes([1000, 360])
        content_layout.addWidget(market_split, 5)

        tabs = QtWidgets.QTabWidget()
        self.account_monitor = AccountMonitor(self.main_engine, self.event_engine)
        self.position_monitor = PositionMonitor(self.main_engine, self.event_engine)
        self.order_monitor = ReadOnlyOrderMonitor(self.main_engine, self.event_engine)
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
        readonly = QtWidgets.QLabel("只读模式 · 禁止下单")
        readonly.setObjectName("readonly")
        self.market_status = QtWidgets.QLabel("行情桥连接中")
        self.market_status.setObjectName("statusOffline")
        self.trade_status = QtWidgets.QLabel("ATP桥连接中")
        self.trade_status.setObjectName("statusOffline")
        self.server_status = QtWidgets.QLabel("中间层检测中")
        self.server_status.setObjectName("statusOffline")
        refresh = QtWidgets.QPushButton("刷新账户")
        refresh.setToolTip("重新查询 ATP 资金、持仓、委托和成交")
        refresh.clicked.connect(self.refresh_account)
        layout.addWidget(brand)
        layout.addWidget(subtitle)
        layout.addSpacing(16)
        layout.addWidget(readonly)
        layout.addStretch()
        layout.addWidget(self.market_status)
        layout.addWidget(self.trade_status)
        layout.addWidget(self.server_status)
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
        self.last_price.value.setText(f"{tick.last_price:,.2f}")
        change = ((tick.last_price / tick.pre_close) - 1) * 100 if tick.pre_close else 0
        self.change.value.setText(f"{change:+.2f}%")
        self.change.value.setObjectName("positive" if change >= 0 else "negative")
        self.change.value.style().unpolish(self.change.value)
        self.change.value.style().polish(self.change.value)

    def _update_account_metrics(self, event: Event) -> None:
        account = event.data
        self.balance.value.setText(f"¥ {account.balance:,.2f}")
        self.available.value.setText(f"¥ {account.available:,.2f}")

    def _update_connection(self, event: Event) -> None:
        data = event.data
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
