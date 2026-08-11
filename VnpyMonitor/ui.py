"""QuantFabric 的 vn.py 桌面工作台。"""

from __future__ import annotations

import os
import unicodedata
from collections import OrderedDict
from pathlib import Path

from vnpy.chart import CandleItem, ChartWidget, VolumeItem
from vnpy.event import Event
from vnpy.trader.constant import Direction, Exchange, Interval, Offset, OrderType
from vnpy.trader.event import EVENT_ACCOUNT, EVENT_TICK
from vnpy.trader.object import BarData, OrderRequest, SubscribeRequest
from vnpy.trader.ui import QtCore, QtGui, QtWidgets
from vnpy.trader.ui.widget import AccountMonitor, LogMonitor, OrderMonitor, PositionMonitor, TickMonitor

from .gateway import EVENT_QF_CONNECTION, GATEWAY_NAME, QuantFabricGateway, load_security_master


ROOT_DIR = Path(__file__).resolve().parents[1]


def normalize_search_text(value: str) -> str:
    """统一全角/半角字符并忽略证券简称中的空白。"""
    return "".join(unicodedata.normalize("NFKC", value).lower().split())


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
        "AuthAdmin": "认证与权限服务",
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


class SecurityMasterTable(QtWidgets.QTableWidget):
    """展示全量证券主数据；实时行情只对用户选择的标的按需订阅。"""

    def __init__(self, securities: list[dict]) -> None:
        super().__init__(len(securities), 3)
        self.setHorizontalHeaderLabels(["代码", "名称", "交易所"])
        self.verticalHeader().hide()
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setSortingEnabled(False)
        for row, security in enumerate(securities):
            ticker = str(security.get("ticker", ""))
            exchange = str(security.get("exchange", ""))
            values = (ticker, str(security.get("name", ticker)), exchange)
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setData(QtCore.Qt.ItemDataRole.UserRole, f"{ticker}.{exchange}")
                self.setItem(row, column, item)
        self.setSortingEnabled(True)
        self.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)


class SecurityUniversePanel(QtWidgets.QWidget):
    """左侧常驻的全量证券列表，行情仍只对选中的标的订阅。"""

    def __init__(self, securities: list[dict], select_callback) -> None:
        super().__init__()
        self.securities = securities
        title = QtWidgets.QLabel(f"证券库（{len(securities)}）")
        title.setObjectName("panelTitle")
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("输入代码或名称检索")
        self.filter_edit.setClearButtonEnabled(True)
        self.table = SecurityMasterTable(securities)
        self.table.cellDoubleClicked.connect(select_callback)
        self.filter_edit.textChanged.connect(self._filter_rows)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.table, 1)

    def _filter_rows(self, text: str) -> None:
        keyword = normalize_search_text(text)
        self.table.setUpdatesEnabled(False)
        try:
            for row in range(self.table.rowCount()):
                haystack = normalize_search_text(" ".join(
                    self.table.item(row, column).text() for column in range(3)
                ))
                self.table.setRowHidden(row, bool(keyword and keyword not in haystack))
        finally:
            self.table.setUpdatesEnabled(True)


class VisibleCandleItem(CandleItem):
    """在只有一根或平盘 Bar 时仍提供可绘制的纵轴范围。"""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        up_color = QtGui.QColor("#c0392b")
        down_color = QtGui.QColor("#16825d")
        # vn.py 默认用黑色填充上涨 K 线；A 股工作台沿用盘口的红涨绿跌约定。
        self._up_pen = QtGui.QPen(up_color)
        self._black_brush = QtGui.QBrush(up_color)
        self._down_pen = QtGui.QPen(down_color)
        self._down_brush = QtGui.QBrush(down_color)

    def get_y_range(self, min_ix=None, max_ix=None):
        minimum, maximum = super().get_y_range(min_ix, max_ix)
        if maximum <= minimum:
            padding = max(abs(maximum) * 0.005, 0.01)
            return minimum - padding, maximum + padding
        return minimum, maximum


class VisibleVolumeItem(VolumeItem):
    """成交量为零时扩展纵轴，避免空白图层误认为没有数据。"""

    def get_y_range(self, min_ix=None, max_ix=None):
        minimum, maximum = super().get_y_range(min_ix, max_ix)
        return minimum, max(maximum, 1)


class RealtimeChartWidget(ChartWidget):
    """展示当前会话累积的 1 分钟 K 线和成交量。"""

    def __init__(self) -> None:
        super().__init__()
        self.setBackground("#ffffff")
        self.add_plot("price", minimum_height=120, hide_x_axis=True)
        self.add_item(VisibleCandleItem, "candle", "price")
        self.add_plot("volume", minimum_height=45)
        self.add_item(VisibleVolumeItem, "volume", "volume")
        self.close_curve = self.get_plot("price").plot(
            pen=QtGui.QPen(QtGui.QColor("#c0392b"), 2),
            symbol="o",
            symbolSize=7,
            symbolPen=QtGui.QPen(QtGui.QColor("#c0392b")),
            symbolBrush=QtGui.QBrush(QtGui.QColor("#ffffff")),
        )
        for plot in self.get_all_plots():
            plot.getAxis("right").setPen(QtGui.QPen(QtGui.QColor("#68717d")))
            plot.getAxis("right").setTextPen(QtGui.QPen(QtGui.QColor("#4d5966")))
            plot.getAxis("bottom").setPen(QtGui.QPen(QtGui.QColor("#68717d")))
            plot.getAxis("bottom").setTextPen(QtGui.QPen(QtGui.QColor("#4d5966")))

    def update_close_curve(self, bars) -> None:
        self.close_curve.setData(
            list(range(len(bars))),
            [bar.close_price for bar in bars],
        )

    def update_history(self, history) -> None:
        super().update_history(history)
        # ChartWidget 仅在横轴变化时自动刷新纵轴。启动初期只有一根 Bar 时横轴
        # 范围保持不变，必须主动重算，否则价格会被绘制在过期的坐标范围之外。
        self._update_y_range()


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
        self.state = QtWidgets.QLabel("C++ 原生会话连接中")
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
            f"{side} {symbol}，限价 {price:.2f}，数量 {volume} 股？\n"
            "订单将经过 C++ 风控后发送至当前柜台适配器。",
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
        self.bars: dict[str, OrderedDict] = {}
        self.volume_anchors: dict[str, float] = {}
        self.securities = load_security_master()
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
        left_market = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_market)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        left_layout.addWidget(self.tick_monitor, 3)
        chart_title = QtWidgets.QLabel("实时 1 分钟 K 线（启动后累积）")
        chart_title.setObjectName("panelTitle")
        left_layout.addWidget(chart_title)
        self.chart = RealtimeChartWidget()
        self.chart.setObjectName("panel")
        left_layout.addWidget(self.chart, 2)
        market_split.addWidget(left_market)
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
        self.security_panel = SecurityUniversePanel(self.securities, self._select_security_row)
        self.security_table = self.security_panel.table
        tabs.addTab(self.account_monitor, "资金")
        tabs.addTab(self.position_monitor, "持仓")
        tabs.addTab(self.order_monitor, "委托")
        tabs.addTab(self.service_table, "服务状态")
        tabs.addTab(self.log_monitor, "运行日志")
        content_layout.addWidget(tabs, 4)

        self.security_dock = QtWidgets.QDockWidget(f"证券库（{len(self.securities)}）", self)
        self.security_dock.setObjectName("securityDock")
        self.security_dock.setWidget(self.security_panel)
        self.security_dock.setMinimumWidth(245)
        self.security_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.security_dock)

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
        self.trading_mode = QtWidgets.QLabel("C++ 原生会话连接中")
        self.trading_mode.setObjectName("statusOffline")
        self.market_status = QtWidgets.QLabel("行情等待中")
        self.market_status.setObjectName("statusOffline")
        self.trade_status = QtWidgets.QLabel("账户等待中")
        self.trade_status.setObjectName("statusOffline")
        self.server_status = QtWidgets.QLabel("XServer 检测中")
        self.server_status.setObjectName("statusOffline")
        self.universe_status = QtWidgets.QLabel(f"证券库 {len(self.securities)} 只")
        self.universe_status.setObjectName("subBrand")
        self.symbol_selector = QtWidgets.QComboBox()
        self.symbol_selector.setMinimumWidth(210)
        self.symbol_selector.setMaxVisibleItems(20)
        self.symbol_selector.setEditable(True)
        self.symbol_selector.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self.symbol_selector.view().setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        ordered = sorted(
            self.securities,
            key=lambda item: (item.get("ticker") != "300007", item.get("exchange", ""), item.get("ticker", "")),
        )
        for security in ordered:
            ticker = str(security.get("ticker", ""))
            exchange = str(security.get("exchange", ""))
            name = str(security.get("name", ticker))
            self.symbol_selector.addItem(f"{ticker} {name} · {exchange}", f"{ticker}.{exchange}")
        completer = self.symbol_selector.completer()
        completer.setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
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
        layout.addWidget(self.universe_status)
        layout.addWidget(self.symbol_selector)
        layout.addWidget(refresh)

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
        self._set_status(self.market_status, "行情在线", True)
        self.ticks[tick.vt_symbol] = tick
        self._update_bar(tick)
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
        self.subscribe_selected()
        if tick:
            self._render_tick_metrics(tick)
        self._render_chart(vt_symbol)

    def subscribe_selected(self) -> None:
        vt_symbol = self.symbol_selector.currentData()
        if not vt_symbol or "." not in vt_symbol:
            return
        symbol, exchange_value = vt_symbol.rsplit(".", 1)
        self.main_engine.subscribe(
            SubscribeRequest(symbol=symbol, exchange=Exchange(exchange_value)),
            GATEWAY_NAME,
        )

    def _select_security_row(self, row: int, column: int) -> None:
        code_item = self.security_table.item(row, 0)
        if not code_item:
            return
        vt_symbol = code_item.data(QtCore.Qt.ItemDataRole.UserRole)
        index = self.symbol_selector.findData(vt_symbol)
        if index >= 0:
            self.symbol_selector.setCurrentIndex(index)

    def _update_bar(self, tick) -> None:
        """将累计成交量行情聚合成当前标的的 1 分钟 Bar。"""
        bar_datetime = tick.datetime.replace(second=0, microsecond=0)
        bars = self.bars.setdefault(tick.vt_symbol, OrderedDict())
        bar = bars.get(bar_datetime)
        if bar is None:
            self.volume_anchors[tick.vt_symbol] = tick.volume
            bar = BarData(
                gateway_name=GATEWAY_NAME,
                symbol=tick.symbol,
                exchange=tick.exchange,
                datetime=bar_datetime,
                interval=Interval.MINUTE,
                open_price=tick.last_price,
                high_price=tick.last_price,
                low_price=tick.last_price,
                close_price=tick.last_price,
            )
            bars[bar_datetime] = bar
        bar.high_price = max(bar.high_price, tick.last_price)
        bar.low_price = min(bar.low_price, tick.last_price)
        bar.close_price = tick.last_price
        bar.turnover = tick.turnover
        bar.volume = max(0, tick.volume - self.volume_anchors[tick.vt_symbol])
        while len(bars) > 240:
            bars.popitem(last=False)
        if self.symbol_selector.currentData() == tick.vt_symbol:
            self._render_chart(tick.vt_symbol)

    def _render_chart(self, vt_symbol: str) -> None:
        bars = self.bars.get(vt_symbol)
        if not bars:
            self.chart.clear_all()
            self.chart.update_close_curve([])
            return
        self.chart.clear_all()
        # Keep one empty slot on each side of the first candle. Otherwise its
        # x=0 center lies on the plot boundary and Qt clips the whole line.
        self.chart._bar_count = max(2, min(60, len(bars)))
        history = list(bars.values())
        self.chart.update_history(history)
        self.chart.update_close_curve(history)

    def _update_account_metrics(self, event: Event) -> None:
        account = event.data
        self._set_status(self.trade_status, "账户在线", True)
        self.balance.value.setText(f"¥ {account.balance:,.2f}")
        self.available.value.setText(f"¥ {account.available:,.2f}")

    def _update_connection(self, event: Event) -> None:
        data = event.data
        if data["name"] == "C++原生会话":
            enabled = bool(data["connected"])
            self.trading_panel.set_trading_enabled(enabled)
            self._set_status(
                self.trading_mode,
                "交易模式 · C++风控" if enabled else data["detail"],
                enabled,
            )
            self._set_status(self.server_status, data["detail"], bool(data.get("tcp_connected")))
            return

    @staticmethod
    def _set_status(label: QtWidgets.QLabel, text: str, connected: bool) -> None:
        label.setText(text)
        label.setObjectName("statusOnline" if connected else "statusOffline")
        label.style().unpolish(label)
        label.style().polish(label)

    def refresh_account(self) -> None:
        gateway = self.main_engine.get_gateway(GATEWAY_NAME)
        if isinstance(gateway, QuantFabricGateway):
            gateway.query_all()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.main_engine.close()
        event.accept()
