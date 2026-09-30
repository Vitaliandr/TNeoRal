# итог по стакану, у брокера он по последней сделке а она у неоактивов врёт

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from tneoral.core import calc

from .orderbook_view import fmt
from .widgets import KeepColors

GREEN = QColor("#3ddc97")
RED = QColor("#ff6b7a")
MUTED = QColor("#8e9bab")
YELLOW = QColor("#f2c14e")
TEXT = QColor("#e1e7ef")

HEADERS = ["Актив", "Тип", "Лотов", "Ср. цена", "Цена выхода", "Сумма, $", "Итог"]


class PositionsTable(QFrame):
    selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.uids = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QLabel("Позиции")
        self.title.setObjectName("panelTitle")
        self.title.setIndent(10)  # пробелы в начале html съедаются
        self.title.setFixedHeight(30)
        lay.addWidget(self.title)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.ensurePolished()
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().lineSpacing() + 14)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setItemDelegate(KeepColors(self.table))
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for col in (0, 1):
            self.table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(4).setToolTip(
            "По какой средней цене закроется вся позиция прямо сейчас: "
            "лонг - по стороне «Покупка», шорт - по стороне «Продажа»")
        self.table.horizontalHeaderItem(5).setToolTip("Сколько стоит позиция сейчас, по цене выхода")
        self.table.cellClicked.connect(lambda row, _: self._click(row))
        lay.addWidget(self.table)

    def _click(self, row):
        if 0 <= row < len(self.uids):
            self.selected.emit(self.uids[row])

    def _item(self, text, color=TEXT, right=True):
        it = QTableWidgetItem(text)
        it.setForeground(color)
        if right:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return it

    def update_all(self, positions, assets, books, quotes, decimals_of):
        uids = [uid for uid in positions if uid in assets]
        uids.sort(key=lambda u: assets[u].ticker)
        if uids != self.uids:
            self.uids = uids
            self.table.setRowCount(len(uids))

        total = 0.0
        volume = 0.0
        have_total = False
        for row, uid in enumerate(uids):
            p, a, book, q = positions[uid], assets[uid], books.get(uid), quotes.get(uid)
            dec = decimals_of(uid)
            side = "Шорт" if p.is_short else "Лонг"
            self.table.setItem(row, 0, self._item(a.ticker, TEXT, right=False))
            self.table.setItem(row, 1, self._item(side, RED if p.is_short else GREEN, right=False))
            self.table.setItem(row, 2, self._item(str(abs(p.qty))))
            self.table.setItem(row, 3, self._item(fmt(p.avg_price, dec)))

            res = calc.close_now(p.qty, p.avg_price, book, a.size, a.lot) if book else None
            if res is None:
                for col in (4, 5, 6):
                    self.table.setItem(row, col, self._item("—", MUTED))
                continue

            exit_price, got, usd, pct = res
            total += usd
            value = abs(p.qty) * exit_price * a.size * a.lot
            volume += value
            have_total = True
            price_it = self._item(fmt(exit_price, dec))
            tips = []
            if got < abs(p.qty):
                price_it.setForeground(YELLOW)
                tips.append(f"в стакане только {got} из {abs(p.qty)}")
            if q is not None and not q.ok and q.reason:
                price_it.setForeground(YELLOW)
                tips.append(q.reason)
            price_it.setToolTip(", ".join(tips))
            self.table.setItem(row, 4, price_it)
            self.table.setItem(row, 5, self._item(fmt(value)))

            color = GREEN if usd > 0 else RED if usd < 0 else TEXT
            sign = "+" if usd > 0 else ""
            self.table.setItem(row, 6, self._item(f"{sign}{fmt(usd)} $ · {sign}{fmt(pct)}%", color))

        if not uids:
            self.title.setText("Открытых позиций по неоактивам нет")
        elif have_total:
            sign = "+" if total > 0 else ""
            color = "#3ddc97" if total > 0 else "#ff6b7a" if total < 0 else "#e1e7ef"
            self.title.setText(f"Позиции: {len(uids)}   ·   В позициях: {fmt(volume)} $   ·   Итого: "
                               f"<span style='color:{color}'>{sign}{fmt(total)} $</span>")
        else:
            self.title.setText(f"Позиции: {len(uids)}")
