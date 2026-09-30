from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from .orderbook_view import fmt
from .widgets import KeepColors

GREEN = QColor("#3ddc97")
RED = QColor("#ff6b7a")
MUTED = QColor("#6f7d8f")
YELLOW = QColor("#f2c14e")
TEXT = QColor("#e1e7ef")


class AssetsList(QFrame):

    selected = Signal(str)  #uid

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.rows = {}
        self.assets = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        title = QLabel("  Неоактивы")
        title.setObjectName("panelTitle")
        title.setFixedHeight(32)
        lay.addWidget(title)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Актив", "Покупка", "Продажа", "Спред"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # высоту от шрифта,при масштабе 150% фиксированная не влезала
        self.table.ensurePolished()
        line = self.table.fontMetrics().lineSpacing()
        self.table.verticalHeader().setDefaultSectionSize(line * 2 + 12)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setWordWrap(False)
        self.table.setItemDelegate(KeepColors(self.table))
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, width in ((1, 76), (2, 76), (3, 58)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, width)
        hh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemSelectionChanged.connect(self._on_select)
        lay.addWidget(self.table)

    def set_assets(self, assets):
        self.table.setRowCount(len(assets))
        self.rows.clear()
        for i, a in enumerate(assets):
            self.assets[a.uid] = a
            self.rows[a.uid] = i
            name = QTableWidgetItem(f"{a.short_name}\n{a.ticker}")
            name.setData(Qt.UserRole, a.uid)
            self.table.setItem(i, 0, name)
            for c in (1, 2, 3):
                it = QTableWidgetItem("—")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setForeground(MUTED)
                self.table.setItem(i, c, it)

    def update_quote(self, uid, quote, trading=True, decimals=2):
        row = self.rows.get(uid)
        if row is None:
            return
        bid, ask, spr = (self.table.item(row, c) for c in (1, 2, 3))

        if not trading:
            bid.setText("—")
            ask.setText("—")
            spr.setText("закр.")
            for it in (bid, ask, spr):
                it.setForeground(MUTED)
            return

        bid.setText(fmt(quote.bid, decimals))
        ask.setText(fmt(quote.ask, decimals))
        bid.setForeground(YELLOW if quote.bid_held else GREEN)
        ask.setForeground(YELLOW if quote.ask_held else RED)

        if quote.spread is None:
            spr.setText("—")
        else:
            spr.setText(f"{quote.spread:.2f}%".replace(".", ","))
        spr.setForeground(TEXT if quote.ok else YELLOW)
        spr.setToolTip(quote.reason)

    def current_uid(self):
        items = self.table.selectedItems()
        if not items:
            return None
        return self.table.item(items[0].row(), 0).data(Qt.UserRole)

    def select_uid(self, uid):
        row = self.rows.get(uid)
        if row is not None:
            self.table.selectRow(row)
            self.table.scrollToItem(self.table.item(row, 0))

    def _on_select(self):
        uid = self.current_uid()
        if uid:
            self.selected.emit(uid)

    def _filter(self, text):
        text = text.lower().strip()
        for uid, row in self.rows.items():
            a = self.assets[uid]
            hide = bool(text) and text not in a.name.lower() and text not in a.ticker.lower()
            self.table.setRowHidden(row, hide)
