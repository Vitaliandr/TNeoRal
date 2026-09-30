from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from tneoral.core import calc

from .orderbook_view import fmt
from .widgets import KeepColors

GREEN = QColor("#3ddc97")
RED = QColor("#ff6b7a")
TEXT = QColor("#e1e7ef")
MUTED = QColor("#8e9bab")

PERIODS = [("Сегодня", 1), ("7 дней", 7), ("30 дней", 30)]
HEADERS = ["Время", "Актив", "Операция", "Кол.", "Цена", "Сумма", "Результат"]

# с запасом: для результата нужна средняя а позицию могли открыть раньше
# TODO: если позиция старше 90 дней,догружать историю кусками пока не найдём начало
LOAD_DAYS = 90


class HistoryView(QFrame):
    refresh = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.trades = []
        self.cur_qty = None  # None,портфель ещё не пришёл
        self.sizes = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setContentsMargins(10, 4, 10, 4)
        self.info = QLabel("")
        self.info.setProperty("muted", True)
        top.addWidget(self.info)
        top.addStretch()
        self.period = QComboBox()
        for name, days in PERIODS:
            self.period.addItem(name, days)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(lambda _: self._render())
        top.addWidget(self.period)
        btn = QPushButton("Обновить")
        btn.clicked.connect(self.ask)
        top.addWidget(btn)
        lay.addLayout(top)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setTextElideMode(Qt.ElideNone)
        self.table.setItemDelegate(KeepColors(self.table))
        self.table.ensurePolished()
        self.table.verticalHeader().setDefaultSectionSize(self.table.fontMetrics().lineSpacing() + 10)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignRight | Qt.AlignVCenter)
        for col in (0, 1, 2):
            self.table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(6).setToolTip(
            "Финансовый результат по сделке, которая закрывает позицию (целиком или частично). "
            "Считается от средней цены позиции, как в терминале")
        lay.addWidget(self.table)

    @property
    def days(self):
        return self.period.currentData()

    def ask(self):
        self.info.setText("Загружаю...")
        self.refresh.emit(LOAD_DAYS)

    def set_assets(self, assets):
        self.sizes = {a.uid: a.size for a in assets}

    def set_positions(self, positions):
        qty = {uid: p.qty for uid, p in positions.items()}
        if qty != self.cur_qty:
            self.cur_qty = qty
            self._render()

    def show_trades(self, trades):
        self.trades = trades
        self._render()

    def _results(self):
        by_uid = {}
        for t in reversed(self.trades):
            by_uid.setdefault(t.uid, []).append(t)
        res = {}
        for uid, lst in by_uid.items():
            if self.cur_qty is None:
                continue
            # позиция до первой сделки = текущая минус всё наторгованное
            moved = sum(t.qty if t.side == "buy" else -t.qty for t in lst)
            start = self.cur_qty.get(uid, 0) - moved
            for t, r in zip(lst, calc.trade_results(lst, self.sizes.get(uid, 1.0), start)):
                res[id(t)] = r
        return res

    def _render(self):
        results = self._results()
        since = datetime.now(timezone.utc) - timedelta(days=self.days)
        if self.days == 1:
            #с полуночи, а не 24 часа
            since = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        shown = [t for t in self.trades if t.when >= since]

        self.table.setRowCount(len(shown))
        buy_sum = sell_sum = total = 0.0
        for row, t in enumerate(shown):
            is_buy = t.side == "buy"
            cur = "$" if t.currency in ("USD", "") else t.currency
            local = t.when.astimezone()
            cells = [
                (local.strftime("%d.%m %H:%M:%S"), MUTED, False),
                (t.ticker, TEXT, False),
                ("Покупка" if is_buy else "Продажа", GREEN if is_buy else RED, False),
                (str(t.qty), TEXT, True),
                (f"{fmt(t.price)} {cur}", TEXT, True),
                (f"{fmt(abs(t.amount))} {cur}", TEXT, True),
            ]
            r = results.get(id(t))
            if r is None:
                cells.append(("", MUTED, True))
            else:
                usd, pct = r
                total += usd
                sign = "+" if usd > 0.005 else ""
                color = GREEN if usd > 0.005 else RED if usd < -0.005 else MUTED
                cells.append((f"{sign}{fmt(usd)} $ · {sign}{fmt(pct)}%", color, True))
            for col, (text, color, right) in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setForeground(color)
                if right:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(row, col, it)
            if is_buy:
                buy_sum += abs(t.amount)
            else:
                sell_sum += abs(t.amount)

        if not shown:
            self.info.setText("Сделок по неоактивам за этот период нет")
            return
        sign = "+" if total > 0.005 else ""
        color = "#3ddc97" if total > 0.005 else "#ff6b7a" if total < -0.005 else "#8e9bab"
        self.info.setText(
            f"Сделок: {len(shown)}   ·   куплено на {fmt(buy_sum)} $   ·   продано на {fmt(sell_sum)} $"
            f"   ·   результат: <span style='color:{color}'>{sign}{fmt(total)} $</span>")
