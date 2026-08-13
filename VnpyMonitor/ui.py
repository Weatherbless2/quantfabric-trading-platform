"""QuantFabric 的 vn.py 桌面工作台。"""

from __future__ import annotations

import unicodedata
from collections import OrderedDict

from vnpy.chart import CandleItem, ChartWidget, VolumeItem
from vnpy.event import Event
from vnpy.trader.constant import Direction, Exchange, Interval, Offset, OrderType
from vnpy.trader.event import EVENT_TICK
from vnpy.trader.object import BarData, OrderRequest, SubscribeRequest
from vnpy.trader.ui import QtCore, QtGui, QtWidgets
from vnpy.trader.ui.widget import AccountMonitor, OrderMonitor, PositionMonitor

from .gateway import EVENT_QF_CONNECTION, GATEWAY_NAME, QuantFabricGateway, load_security_master
from .history import HistoryBar, start_history_load

def normalize_search_text(value: str) -> str:
    """统一全角/半角字符并忽略证券简称中的空白。"""
    return "".join(unicodedata.normalize("NFKC", value).lower().split())


STYLE = """
QWidget {
    color: #dbe5ee;
    font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QMainWindow, #central { background: #111820; }
#header { background: #151d26; border-bottom: 1px solid #293745; }
#brandMark {
    min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    color: #ffffff; background: #d94f49; border-radius: 3px;
    font-size: 12px; font-weight: 700; qproperty-alignment: AlignCenter;
}
#brand { font-size: 18px; font-weight: 700; color: #f2f6fa; }
#marketLabel { color: #8ca2b4; padding-left: 10px; }
#statusOnline {
    color: #66d9ad; background: #153c35; border: 1px solid #246552;
    border-radius: 3px; padding: 4px 8px;
}
#statusOffline {
    color: #f09089; background: #412a2d; border: 1px solid #744248;
    border-radius: 3px; padding: 4px 8px;
}
#panel { background: #171f28; border: 1px solid #293846; border-radius: 3px; }
#panelTitle { font-size: 13px; font-weight: 700; color: #edf2f7; }
#quoteSymbol { font-size: 17px; font-weight: 700; color: #edf2f7; }
#quoteMeta { color: #8397a8; }
#quotePrice { font-size: 29px; font-weight: 700; color: #edf2f7; }
#quoteChange { font-size: 15px; font-weight: 700; }
#quoteField { color: #8196a8; }
#quoteFieldValue { font-weight: 600; color: #dbe5ee; }
#positive { color: #f15b54; font-weight: 700; }
#negative { color: #25bd8a; font-weight: 700; }
#buyButton { color: #ffffff; background: #d94f49; border: 1px solid #f06a62; font-weight: 700; }
#buyButton:hover { background: #ed5e56; }
#sellButton { color: #ffffff; background: #158a67; border: 1px solid #25ae84; font-weight: 700; }
#sellButton:hover { background: #1aa478; }
#buyButton:disabled, #sellButton:disabled {
    color: #748492; background: #27313c; border-color: #354250;
}
QPushButton {
    background: #202b36; border: 1px solid #354656; border-radius: 3px;
    padding: 7px 12px; color: #dbe5ee;
}
QPushButton:hover { background: #2a3744; border-color: #547187; }
QPushButton:pressed { background: #18212a; }
QLineEdit, QAbstractSpinBox {
    background: #111820; border: 1px solid #344555; border-radius: 3px;
    padding: 5px 7px; color: #e6edf3; selection-background-color: #38546b;
}
QLineEdit:focus, QAbstractSpinBox:focus { border-color: #66869e; }
QComboBox::drop-down, QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    border: none; width: 17px; background: #202b36;
}
QTabWidget::pane { background: #171f28; border: 1px solid #293846; top: -1px; }
QTabBar::tab {
    background: #151d26; color: #889cab; padding: 8px 18px;
    border: 1px solid #293846; border-bottom: none; margin-right: 1px;
}
QTabBar::tab:selected { background: #171f28; color: #f1f5f8; font-weight: 700; border-top: 2px solid #d94f49; }
QTableWidget {
    background: #171f28; alternate-background-color: #1a2530; border: none;
    gridline-color: #263440; selection-background-color: #2a4151;
    selection-color: #ffffff;
}
QTableWidget::item { padding: 0 6px; }
QHeaderView::section {
    background: #202b36; color: #9fb0bd; border: none;
    border-right: 1px solid #2b3a47; border-bottom: 1px solid #2b3a47;
    padding: 6px; font-weight: 600;
}
QDockWidget { color: #dbe5ee; font-weight: 700; }
QDockWidget::title { background: #151d26; padding: 9px 10px; border-bottom: 1px solid #293846; }
QDockWidget::close-button, QDockWidget::float-button { background: transparent; border: none; }
QSplitter::handle { background: #111820; }
QSplitter::handle:hover { background: #334553; }
QScrollBar:vertical { width: 9px; background: #151d26; margin: 0; }
QScrollBar::handle:vertical { background: #3c5161; min-height: 28px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #536d80; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { color: #edf2f7; background: #202b36; border: 1px solid #43596a; }
"""


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
        self.table.verticalHeader().setMinimumSectionSize(18)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.horizontalHeader().setFixedHeight(28)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(7)
        title = QtWidgets.QLabel("五档行情")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
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
        else:
            self.table.clearContents()

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


class SecurityMasterTable(QtWidgets.QTableWidget):
    """展示全量证券主数据；实时行情只对用户选择的标的按需订阅。"""

    def __init__(self, securities: list[dict]) -> None:
        super().__init__(len(securities), 3)
        self.setHorizontalHeaderLabels(["代码", "名称", "交易所"])
        self.verticalHeader().hide()
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(self.SelectionBehavior.SelectRows)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.setAlternatingRowColors(True)
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
        self.filter_edit = QtWidgets.QLineEdit()
        self.filter_edit.setPlaceholderText("搜索代码或名称")
        self.filter_edit.setClearButtonEnabled(True)
        self.table = SecurityMasterTable(securities)
        self.table.cellClicked.connect(select_callback)
        self.filter_edit.textChanged.connect(self._filter_rows)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 7, 8, 8)
        layout.setSpacing(6)
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
    """A-share candle with narrow bodies and clearly visible wicks."""

    BODY_WIDTH = 0.26

    def __init__(self, manager) -> None:
        super().__init__(manager)
        up_color = QtGui.QColor("#c0392b")
        down_color = QtGui.QColor("#16825d")
        # vn.py 默认用黑色填充上涨 K 线；A 股工作台沿用盘口的红涨绿跌约定。
        self._up_pen = QtGui.QPen(up_color)
        self._up_pen.setWidth(1)
        self._up_pen.setCosmetic(True)
        self._black_brush = QtGui.QBrush(up_color)
        self._down_pen = QtGui.QPen(down_color)
        self._down_pen.setWidth(1)
        self._down_pen.setCosmetic(True)
        self._down_brush = QtGui.QBrush(down_color)

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        """Draw a standard candle instead of a full-width color block."""
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)

        is_up = bar.close_price >= bar.open_price
        painter.setPen(self._up_pen if is_up else self._down_pen)
        painter.setBrush(self._black_brush if is_up else self._down_brush)

        # The wick always spans the actual high-low range. A flat minute bar
        # remains a short horizontal line so it never turns into a giant body.
        if bar.high_price > bar.low_price:
            painter.drawLine(
                QtCore.QPointF(ix, bar.high_price),
                QtCore.QPointF(ix, bar.low_price),
            )
        if bar.open_price == bar.close_price:
            painter.drawLine(
                QtCore.QPointF(ix - self.BODY_WIDTH, bar.open_price),
                QtCore.QPointF(ix + self.BODY_WIDTH, bar.open_price),
            )
        else:
            painter.drawRect(QtCore.QRectF(
                ix - self.BODY_WIDTH,
                bar.open_price,
                self.BODY_WIDTH * 2,
                bar.close_price - bar.open_price,
            ))
        painter.end()
        return picture

    def get_y_range(self, min_ix=None, max_ix=None):
        minimum, maximum = super().get_y_range(min_ix, max_ix)
        if maximum <= minimum:
            padding = max(abs(maximum) * 0.005, 0.01)
            return minimum - padding, maximum + padding
        return minimum, maximum

    def get_info_text(self, ix: int) -> str:
        bar = self._manager.get_bar(ix)
        if not bar:
            return ""
        return "\n".join((
            bar.datetime.strftime("%Y-%m-%d %H:%M"),
            f"开 {bar.open_price:.2f}  高 {bar.high_price:.2f}",
            f"低 {bar.low_price:.2f}  收 {bar.close_price:.2f}",
        ))


class VisibleVolumeItem(VolumeItem):
    """成交量为零时扩展纵轴，避免空白图层误认为没有数据。"""

    BODY_WIDTH = VisibleCandleItem.BODY_WIDTH

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self._up_pen = QtGui.QPen(QtGui.QColor("#c0392b"))
        self._up_pen.setWidth(1)
        self._up_pen.setCosmetic(True)
        self._up_brush = QtGui.QBrush(QtGui.QColor("#c0392b"))
        self._down_pen = QtGui.QPen(QtGui.QColor("#16825d"))
        self._down_pen.setWidth(1)
        self._down_pen.setCosmetic(True)
        self._down_brush = QtGui.QBrush(QtGui.QColor("#16825d"))

    def _draw_bar_picture(self, ix: int, bar: BarData) -> QtGui.QPicture:
        picture = QtGui.QPicture()
        painter = QtGui.QPainter(picture)
        is_up = bar.close_price >= bar.open_price
        painter.setPen(self._up_pen if is_up else self._down_pen)
        painter.setBrush(self._up_brush if is_up else self._down_brush)
        painter.drawRect(QtCore.QRectF(
            ix - self.BODY_WIDTH,
            0,
            self.BODY_WIDTH * 2,
            bar.volume,
        ))
        painter.end()
        return picture

    def get_y_range(self, min_ix=None, max_ix=None):
        minimum, maximum = super().get_y_range(min_ix, max_ix)
        return minimum, max(maximum, 1)


class QuoteOverview(QtWidgets.QWidget):
    """显示当前选中证券的核心行情，避免展示历史订阅标的的无关数据。"""

    fields = (
        ("昨收", "pre_close"),
        ("开盘", "open_price"),
        ("最高", "high_price"),
        ("最低", "low_price"),
        ("成交量", "volume"),
        ("更新时间", "datetime"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("panel")
        self.symbol = QtWidgets.QLabel("300007 · SZSE")
        self.symbol.setObjectName("quoteSymbol")
        self.name = QtWidgets.QLabel("等待行情")
        self.name.setObjectName("quoteMeta")
        self.last_price = QtWidgets.QLabel("--")
        self.last_price.setObjectName("quotePrice")
        self.change = QtWidgets.QLabel("--")
        self.change.setObjectName("quoteChange")
        self.values: dict[str, QtWidgets.QLabel] = {}

        title = QtWidgets.QVBoxLayout()
        title.setSpacing(2)
        title.addWidget(self.symbol)
        title.addWidget(self.name)

        price = QtWidgets.QVBoxLayout()
        price.setSpacing(2)
        price.addWidget(self.last_price)
        price.addWidget(self.change)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(18)
        layout.addLayout(title)
        layout.addLayout(price)
        for title_text, field in self.fields:
            field_layout = QtWidgets.QVBoxLayout()
            field_layout.setSpacing(2)
            label = QtWidgets.QLabel(title_text)
            label.setObjectName("quoteField")
            value = QtWidgets.QLabel("--")
            value.setObjectName("quoteFieldValue")
            field_layout.addWidget(label)
            field_layout.addWidget(value)
            layout.addLayout(field_layout)
            self.values[field] = value
        layout.addStretch()

    def set_symbol(self, vt_symbol: str, name: str, tick=None) -> None:
        symbol, exchange = vt_symbol.rsplit(".", 1)
        self.symbol.setText(f"{symbol} · {exchange}")
        self.name.setText(name)
        if tick:
            self.update_tick(tick)
            return
        self.last_price.setText("--")
        self.change.setText("--")
        self.change.setObjectName("quoteChange")
        self._refresh_style(self.change)
        for value in self.values.values():
            value.setText("--")

    def update_tick(self, tick) -> None:
        self.symbol.setText(f"{tick.symbol} · {tick.exchange.value}")
        self.name.setText(tick.name)
        self.last_price.setText(f"{tick.last_price:,.2f}")
        change = ((tick.last_price / tick.pre_close) - 1) * 100 if tick.pre_close else 0
        self.change.setText(f"{change:+.2f}%")
        self.change.setObjectName("positive" if change >= 0 else "negative")
        self._refresh_style(self.change)
        self.values["pre_close"].setText(f"{tick.pre_close:,.2f}")
        self.values["open_price"].setText(f"{tick.open_price:,.2f}")
        self.values["high_price"].setText(f"{tick.high_price:,.2f}")
        self.values["low_price"].setText(f"{tick.low_price:,.2f}")
        self.values["volume"].setText(f"{tick.volume:,.0f}")
        self.values["datetime"].setText(tick.datetime.strftime("%H:%M:%S"))

    @staticmethod
    def _refresh_style(widget: QtWidgets.QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class RealtimeChartWidget(ChartWidget):
    """Tonghuashun-style A-share candles backed by vn.py's chart widget."""

    DEFAULT_VISIBLE_BARS = 100

    def __init__(self) -> None:
        super().__init__()
        self.setBackground("#171f28")
        self.add_plot("price", minimum_height=120, hide_x_axis=True)
        self.add_item(VisibleCandleItem, "candle", "price")
        self.add_plot("volume", minimum_height=45)
        self.add_item(VisibleVolumeItem, "volume", "volume")
        for plot in self.get_all_plots():
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.getAxis("right").setPen(QtGui.QPen(QtGui.QColor("#53697a")))
            plot.getAxis("right").setTextPen(QtGui.QPen(QtGui.QColor("#a7b7c3")))
            plot.getAxis("bottom").setPen(QtGui.QPen(QtGui.QColor("#53697a")))
            plot.getAxis("bottom").setTextPen(QtGui.QPen(QtGui.QColor("#a7b7c3")))

    def show_recent_bars(self, count: int) -> None:
        """Synchronize the visible window after every history repaint."""
        total = self._manager.get_count()
        self._bar_count = min(max(2, count), max(2, total))
        self._right_ix = total
        self._update_x_range()
        self._update_y_range()

    def update_history(self, history) -> None:
        super().update_history(history)
        # 主图只绘制 K 线与成交量柱。不把价格曲线或指标图层混在行情图中，
        # 以免他们的独立坐标范围遇到异常值时覆盖真实的蜗烛图。
        self._items["candle"].setVisible(True)
        self._items["volume"].setVisible(True)
        # ChartWidget 仅在横轴变化时自动刷新纵轴。启动初期只有一根 Bar 时横轴
        # 范围保持不变，必须主动重算，否则价格会被绘制在过期的坐标范围之外。
        self._update_y_range()


def _bar_from_history(vt_symbol: str, history_bar: HistoryBar) -> BarData:
    """Convert the HTTP history contract to vn.py's chart-native object."""
    symbol, exchange_value = vt_symbol.rsplit(".", 1)
    return BarData(
        gateway_name=GATEWAY_NAME,
        symbol=symbol,
        exchange=Exchange(exchange_value),
        datetime=history_bar.datetime,
        interval=Interval.MINUTE,
        open_price=history_bar.open_price,
        high_price=history_bar.high_price,
        low_price=history_bar.low_price,
        close_price=history_bar.close_price,
        volume=history_bar.volume,
        turnover=history_bar.turnover,
    )


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
        self.connection_ready = False
        self.quote_ready = False
        self.setObjectName("panel")

        title = QtWidgets.QLabel("快速委托")
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
        self.state = QtWidgets.QLabel("交易会话连接中")
        self.state.setObjectName("statusOffline")

        heading = QtWidgets.QHBoxLayout()
        heading.addWidget(title)
        heading.addStretch()
        heading.addWidget(self.symbol)

        form = QtWidgets.QHBoxLayout()
        form.setSpacing(5)
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
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        layout.addLayout(heading)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.state)
        self.setMaximumHeight(168)
        self.set_trading_enabled(False)

    def set_symbol(self, vt_symbol: str, tick=None) -> None:
        changed = self.vt_symbol != vt_symbol
        self.vt_symbol = vt_symbol
        symbol, exchange = vt_symbol.rsplit(".", 1)
        self.symbol.setText(f"{symbol} · {exchange}")
        self.quote_ready = bool(tick and tick.last_price > 0)
        if self.quote_ready and (changed or self.price.value() <= 0.01):
            self.price.setValue(tick.last_price)
        elif changed:
            self.price.setValue(0.01)
        self._refresh_trading_state()

    def set_trading_enabled(self, enabled: bool) -> None:
        self.connection_ready = enabled
        if not enabled:
            # 重连后必须等待当前标的的新报价，不能复用断线前的价格。
            self.quote_ready = False
        self._refresh_trading_state()

    def _refresh_trading_state(self) -> None:
        enabled = self.connection_ready and self.quote_ready
        self.buy_button.setEnabled(enabled)
        self.sell_button.setEnabled(enabled)
        if not self.connection_ready:
            self.state.setText("交易会话未就绪")
        elif not self.quote_ready:
            self.state.setText("等待当前标的行情")
        else:
            self.state.setText("可下单")
        self.state.setObjectName("statusOnline" if enabled else "statusOffline")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def send_order(self, direction: Direction) -> None:
        if not self.connection_ready or not self.quote_ready:
            QtWidgets.QMessageBox.warning(self, "委托未发送", "当前标的尚未收到有效行情或交易会话未就绪。")
            return
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
    signal_connection = QtCore.Signal(Event)
    signal_history_loaded = QtCore.Signal(str, int, list)
    signal_history_failed = QtCore.Signal(str, str)

    def __init__(self, main_engine, event_engine) -> None:
        super().__init__()
        self.main_engine = main_engine
        self.event_engine = event_engine
        self.ticks = {}
        # Live minute bars remain separate from database history.  The chart
        # merges them only after aggregating both sources to the same period.
        self.bars: dict[str, OrderedDict] = {}
        self.history_bars: dict[tuple[str, int], list[BarData]] = {}
        self.history_threads: dict[str, QtCore.QThread] = {}
        self.history_workers: dict[str, object] = {}
        self.history_interval = 1
        self.volume_anchors: dict[str, float] = {}
        self.securities = load_security_master()
        self.security_names = {
            f"{item.get('ticker', '')}.{item.get('exchange', '')}": item.get("name", item.get("ticker", ""))
            for item in self.securities
        }
        self.selected_vt_symbol = self._default_symbol()
        self.setWindowTitle("QuantFabric 交易终端")
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
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(8)
        root.addWidget(content, 1)

        market_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        left_market = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left_market)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        self.quote_overview = QuoteOverview()
        left_layout.addWidget(self.quote_overview)
        chart_header = QtWidgets.QHBoxLayout()
        self.chart_title = QtWidgets.QLabel("1 分钟 K 线")
        self.chart_title.setObjectName("panelTitle")
        chart_header.addWidget(self.chart_title)
        chart_header.addStretch()
        chart_header.addWidget(QtWidgets.QLabel("周期"))
        self.interval_combo = QtWidgets.QComboBox()
        self.interval_combo.addItem("1 分钟", 1)
        self.interval_combo.addItem("5 分钟", 5)
        self.interval_combo.addItem("15 分钟", 15)
        self.interval_combo.currentIndexChanged.connect(self._interval_changed)
        chart_header.addWidget(self.interval_combo)
        left_layout.addLayout(chart_header)
        self.chart = RealtimeChartWidget()
        self.chart.setObjectName("panel")
        left_layout.addWidget(self.chart, 1)
        market_split.addWidget(left_market)
        self.order_book = OrderBookWidget(self.event_engine)
        right_column = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(self.order_book, 1)
        self.trading_panel = TradingPanel(self.main_engine)
        right_layout.addWidget(self.trading_panel)
        market_split.addWidget(right_column)
        market_split.setSizes([1020, 350])
        content_layout.addWidget(market_split, 5)

        tabs = QtWidgets.QTabWidget()
        self.account_monitor = AccountMonitor(self.main_engine, self.event_engine)
        self.position_monitor = PositionMonitor(self.main_engine, self.event_engine)
        self.order_monitor = ConfirmingOrderMonitor(self.main_engine, self.event_engine)
        for monitor in (
            self.account_monitor,
            self.position_monitor,
            self.order_monitor,
        ):
            monitor.horizontalHeader().setSectionResizeMode(
                QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
            monitor.horizontalHeader().setStretchLastSection(True)
            monitor.verticalHeader().setDefaultSectionSize(24)
            monitor.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self._hide_monitor_columns(self.account_monitor, {"gateway_name"})
        self._hide_monitor_columns(self.position_monitor, {"gateway_name"})
        self._hide_monitor_columns(
            self.order_monitor,
            {"reference", "offset", "gateway_name"},
        )
        self.security_panel = SecurityUniversePanel(self.securities, self._select_security_row)
        self.security_table = self.security_panel.table
        tabs.addTab(self.account_monitor, "资金")
        tabs.addTab(self.position_monitor, "持仓")
        tabs.addTab(self.order_monitor, "委托")
        content_layout.addWidget(tabs, 4)

        self.security_dock = QtWidgets.QDockWidget(f"行情列表  {len(self.securities)}", self)
        self.security_dock.setObjectName("securityDock")
        self.security_dock.setWidget(self.security_panel)
        self.security_dock.setMinimumWidth(250)
        self.security_dock.setAllowedAreas(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.security_dock)

    def _create_header(self) -> QtWidgets.QWidget:
        header = QtWidgets.QWidget()
        header.setObjectName("header")
        header.setFixedHeight(52)
        layout = QtWidgets.QHBoxLayout(header)
        layout.setContentsMargins(14, 0, 14, 0)
        mark = QtWidgets.QLabel("QF")
        mark.setObjectName("brandMark")
        brand = QtWidgets.QLabel("QuantFabric")
        brand.setObjectName("brand")
        market_label = QtWidgets.QLabel("A 股交易终端")
        market_label.setObjectName("marketLabel")
        self.session_state = QtWidgets.QLabel("交易会话连接中")
        self.session_state.setObjectName("statusOffline")
        layout.addWidget(mark)
        layout.addWidget(brand)
        layout.addWidget(market_label)
        layout.addStretch()
        layout.addWidget(self.session_state)

        return header

    def _register_events(self) -> None:
        self.signal_tick.connect(self._update_tick_metrics)
        self.signal_connection.connect(self._update_connection)
        self.signal_history_loaded.connect(self._history_loaded)
        self.signal_history_failed.connect(self._history_failed)
        self.event_engine.register(EVENT_TICK, self.signal_tick.emit)
        self.event_engine.register(EVENT_QF_CONNECTION, self.signal_connection.emit)

    def _update_tick_metrics(self, event: Event) -> None:
        tick = event.data
        self.ticks[tick.vt_symbol] = tick
        self._update_bar(tick)
        if self.selected_vt_symbol != tick.vt_symbol:
            return
        self.trading_panel.set_symbol(tick.vt_symbol, tick)
        self.quote_overview.update_tick(tick)

    def _select_symbol(self, vt_symbol: str) -> None:
        if not vt_symbol or "." not in vt_symbol:
            return
        self.selected_vt_symbol = vt_symbol
        self.order_book.set_symbol(vt_symbol)
        tick = self.ticks.get(vt_symbol)
        self.trading_panel.set_symbol(vt_symbol, tick)
        name = self.security_names.get(vt_symbol, vt_symbol.rsplit(".", 1)[0])
        self.quote_overview.set_symbol(vt_symbol, name, tick)
        self.chart_title.setText(f"{name} {self.history_interval} 分钟 K 线")
        self.subscribe_selected()
        self._load_history(vt_symbol)
        self._render_chart(vt_symbol)

    def _interval_changed(self, index: int) -> None:
        self.history_interval = int(self.interval_combo.itemData(index))
        name = self.security_names.get(self.selected_vt_symbol, self.selected_vt_symbol)
        self.chart_title.setText(f"{name} {self.history_interval} 分钟 K 线")
        self._load_history(self.selected_vt_symbol)

    def _history_service_setting(self) -> tuple[str, str]:
        gateway = self.main_engine.get_gateway(GATEWAY_NAME)
        if not isinstance(gateway, QuantFabricGateway):
            return "", ""
        return gateway.history_url, gateway.auth_session_id

    def _load_history(self, vt_symbol: str) -> None:
        service_url, session_id = self._history_service_setting()
        if not service_url or not session_id or "." not in vt_symbol:
            return
        old_thread = self.history_threads.pop(vt_symbol, None)
        if old_thread and old_thread.isRunning():
            old_thread.quit()
        thread, worker = start_history_load(
            service_url, session_id, vt_symbol, self.history_interval, 240,
            self.signal_history_loaded.emit,
            self.signal_history_failed.emit,
        )
        thread.finished.connect(lambda: self._forget_history_thread(vt_symbol, thread))
        self.history_threads[vt_symbol] = thread
        self.history_workers[vt_symbol] = worker
        thread.start()

    def _history_loaded(self, vt_symbol: str, interval: int,
                        history: list[HistoryBar]) -> None:
        bars = [_bar_from_history(vt_symbol, item) for item in history]
        self.history_bars[(vt_symbol, interval)] = bars
        if vt_symbol == self.selected_vt_symbol and interval == self.history_interval:
            self._render_chart(vt_symbol)

    def _history_failed(self, vt_symbol: str, detail: str) -> None:
        # History is optional: live quotes and trading remain available.
        self.main_engine.write_log(f"历史行情加载失败 {vt_symbol}：{detail}")

    def _forget_history_thread(self, vt_symbol: str, thread: QtCore.QThread) -> None:
        """Do not remove a newer request when an older HTTP request finishes."""
        if self.history_threads.get(vt_symbol) is thread:
            self.history_threads.pop(vt_symbol, None)
            self.history_workers.pop(vt_symbol, None)

    def subscribe_selected(self) -> None:
        if not self.selected_vt_symbol or "." not in self.selected_vt_symbol:
            return
        symbol, exchange_value = self.selected_vt_symbol.rsplit(".", 1)
        self.main_engine.subscribe(
            SubscribeRequest(symbol=symbol, exchange=Exchange(exchange_value)),
            GATEWAY_NAME,
        )

    def _select_security_row(self, row: int, column: int) -> None:
        code_item = self.security_table.item(row, 0)
        if not code_item:
            return
        vt_symbol = code_item.data(QtCore.Qt.ItemDataRole.UserRole)
        self._select_symbol(vt_symbol)

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
        if self.selected_vt_symbol == tick.vt_symbol:
            self._render_chart(tick.vt_symbol)

    def _render_chart(self, vt_symbol: str) -> None:
        bars = self._merge_chart_bars(vt_symbol)
        if not bars:
            self.chart.clear_all()
            return
        self.chart.clear_all()
        history = list(bars.values())
        self.chart.update_history(history)
        # Do not only mutate _bar_count: ChartWidget needs the matching right
        # index and x range refreshed, otherwise the candle picture can be
        # stretched into misleading horizontal color blocks.
        self.chart.show_recent_bars(self.chart.DEFAULT_VISIBLE_BARS)

    def _merge_chart_bars(self, vt_symbol: str) -> OrderedDict:
        """Overlay live data onto history after both use the selected period."""
        merged = OrderedDict(
            (bar.datetime, bar)
            for bar in self.history_bars.get((vt_symbol, self.history_interval), [])
        )
        live_bars = self._aggregate_live_bars(vt_symbol)
        if merged and live_bars and not self._live_bars_match_history(merged, live_bars):
            # TestMarket deliberately generates independent demonstration
            # quotes. Its price is not a continuation of ClickHouse history,
            # so overlaying it would expand the y-axis and visually flatten
            # all real candles. Keep the test quote in the order book and
            # trading panel, but preserve an honest historical price chart.
            return merged
        for bar in live_bars.values():
            merged[bar.datetime] = bar
        return OrderedDict(sorted(merged.items()))

    @staticmethod
    def _live_bars_match_history(history: OrderedDict, live: OrderedDict) -> bool:
        """Reject a simulated or malformed live price far from the last close."""
        historical_close = next(reversed(history.values())).close_price
        first_live_close = next(iter(live.values())).close_price
        if historical_close <= 0 or first_live_close <= 0:
            return False
        # A-share daily limits make a 20% discontinuity an invalid chart
        # overlay. This guard is intentionally display-only: it neither
        # alters a real-time quote nor changes order/risk behavior.
        return abs(first_live_close / historical_close - 1) <= 0.20

    def _aggregate_live_bars(self, vt_symbol: str) -> OrderedDict:
        source = self.bars.get(vt_symbol, OrderedDict())
        if self.history_interval == 1:
            return source
        result: OrderedDict = OrderedDict()
        for source_bar in source.values():
            minute = (source_bar.datetime.minute // self.history_interval) * self.history_interval
            bucket = source_bar.datetime.replace(minute=minute, second=0, microsecond=0)
            bar = result.get(bucket)
            if bar is None:
                bar = BarData(
                    gateway_name=GATEWAY_NAME,
                    symbol=source_bar.symbol,
                    exchange=source_bar.exchange,
                    datetime=bucket,
                    interval=Interval.MINUTE,
                    open_price=source_bar.open_price,
                    high_price=source_bar.high_price,
                    low_price=source_bar.low_price,
                    close_price=source_bar.close_price,
                    volume=source_bar.volume,
                    turnover=source_bar.turnover,
                )
                result[bucket] = bar
                continue
            bar.high_price = max(bar.high_price, source_bar.high_price)
            bar.low_price = min(bar.low_price, source_bar.low_price)
            bar.close_price = source_bar.close_price
            bar.volume += source_bar.volume
            bar.turnover += source_bar.turnover
        return result

    def _update_connection(self, event: Event) -> None:
        data = event.data
        if data["name"] == "C++原生会话":
            enabled = bool(data["connected"])
            self.trading_panel.set_trading_enabled(enabled)
            self.session_state.setText("交易会话已连接" if enabled else "交易会话未连接")
            self.session_state.setObjectName("statusOnline" if enabled else "statusOffline")
            self.session_state.style().unpolish(self.session_state)
            self.session_state.style().polish(self.session_state)
            if enabled:
                self._load_history(self.selected_vt_symbol)
            return

    def _default_symbol(self) -> str:
        default = "300007.SZSE"
        if default in self.security_names:
            return default
        return next(iter(self.security_names), "")

    @staticmethod
    def _hide_monitor_columns(monitor, fields: set[str]) -> None:
        """隐藏 vn.py 监控器中仅用于排障的内部字段。"""
        for index, field in enumerate(monitor.headers):
            if field in fields:
                monitor.setColumnHidden(index, True)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        for thread in self.history_threads.values():
            if thread.isRunning():
                thread.quit()
        self.main_engine.close()
        event.accept()
