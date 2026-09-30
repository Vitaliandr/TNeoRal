from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from tneoral.core.orders import ALERT, COL_BUY, LIMIT, LONG, STOP, TAKE, TRAIL

from .orderbook_view import fmt

KIND_NAMES = {STOP: "Стоп-лосс", TAKE: "Тейк-профит", TRAIL: "Трейлинг", ALERT: "Уведомление"}
KIND_COLORS = {STOP: "#ff9aa5", TAKE: "#7ff0bd", TRAIL: "#a8c6ff", ALERT: "#f2c14e"}


def describe(o, dec=2):
    # пишем действие, а не сторону стакана
    if o.kind == ALERT:
        col = "Покупка" if o.column == COL_BUY else "Продажа"
        return f"цена «{col}» {'≥' if o.above else '≤'} {fmt(o.price, dec)}"
    action = "Продать" if o.direction == LONG else "Купить"
    if o.kind == TRAIL:
        lvl = o.trail_level()
        tail = f", сейчас {fmt(lvl, dec)}" if lvl else ""
        return f"{action}, отступ {fmt(o.trail_pct, 1)}%{tail}"
    if o.kind == STOP:
        sign = "≤" if o.direction == LONG else "≥"
    else:
        sign = "≥" if o.direction == LONG else "≤"
    return f"{action} при цене {sign} {fmt(o.price, dec)}"


class OrdersTable(QFrame):
    cancel_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.title = QLabel("  Активные заявки")
        self.title.setObjectName("panelTitle")
        self.title.setFixedHeight(30)
        lay.addWidget(self.title)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Заявка", "Условие", "Кол.", ""])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: self.table.resizeRowsToContents())
        self.table.verticalHeader().setDefaultSectionSize(40)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 34)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.cellClicked.connect(self._on_click)
        lay.addWidget(self.table)

    def _on_click(self, row, col):
        if col != 3:
            return
        it = self.table.item(row, 3)
        if it is not None:
            self.cancel_clicked.emit(it.data(Qt.UserRole))

    def show_orders(self, orders, decimals_of):
        self.table.setRowCount(len(orders))
        for i, o in enumerate(orders):
            dec = decimals_of(o.uid)

            side = "" if o.kind == ALERT else (" лонга" if o.direction == LONG else " шорта")
            name = QTableWidgetItem(f"{o.ticker}\n{KIND_NAMES[o.kind]}{side}"
                                    + (" · OCO" if o.oco else ""))
            name.setForeground(QColor(KIND_COLORS[o.kind]))

            cond = describe(o, dec)
            if o.kind != ALERT:
                cond += "\n" + ("лимитная" if o.exec_type == LIMIT else "рыночная")
            cells = [name, QTableWidgetItem(cond),
                     QTableWidgetItem("" if o.kind == ALERT else str(o.qty))]
            for c, it in enumerate(cells):
                self.table.setItem(i, c, it)

            # не кнопка: кнопки в ячейках иногда рисуются не на своём месте
            x = QTableWidgetItem("✕")
            x.setTextAlignment(Qt.AlignCenter)
            x.setForeground(QColor("#8e9bab"))
            x.setToolTip("Отменить заявку")
            x.setData(Qt.UserRole, o.id)
            self.table.setItem(i, 3, x)

        self.table.resizeRowsToContents()
        # ширина колонки известна только после раскладки
        QTimer.singleShot(0, self.table.resizeRowsToContents)
        self.title.setText(f"  Активные заявки: {len(orders)}" if orders else "  Активных заявок нет")
