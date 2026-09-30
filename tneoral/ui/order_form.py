import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabBar, QVBoxLayout, QWidget,
)

from tneoral.core import calc
from tneoral.core.orderbook import fill_price, fits_in_plate
from tneoral.core.orders import (
    ALERT, COL_BUY, COL_SELL, LIMIT, LONG, MARKET, SHORT, STOP, TAKE, TRAIL, VirtualOrder,
)

from .orderbook_view import fmt
from .widgets import with_steps

#рыночная и лимитная видны только с галочкой "Торговля"
TRADE_MKT = "mkt"
TRADE_LMT = "lmt"
TRADE_TABS = (TRADE_MKT, TRADE_LMT)

KINDS = [TRADE_MKT, TRADE_LMT, STOP, TAKE, TRAIL, ALERT]
TAB_NAMES = ["Рыночная", "Лимитная", "Стоп-лосс", "Тейк-профит", "Трейлинг", "Уведомление"]
BTN_TEXT = {STOP: "Поставить стоп-лосс", TAKE: "Поставить тейк-профит",
            TRAIL: "Поставить трейлинг-стоп", ALERT: "Создать уведомление"}


def _row_label(text):
    lbl = QLabel(text)
    lbl.setProperty("muted", True)
    return lbl


class OrderForm(QFrame):
    created = Signal(list)  # для OCO их два
    trade = Signal(str, int, object)  #side, qty, price (None,рыночная)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.asset = None
        self.position = None
        self.book = None
        self.quote = None
        self.limits = None
        self.min_plate = 20
        self.dec = 2

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(8)

        self.tabs = QTabBar()
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        for name in TAB_NAMES:
            self.tabs.addTab(name)
        self.tabs.currentChanged.connect(self._on_tab)
        lay.addWidget(self.tabs)

        head = QHBoxLayout()
        head.setContentsMargins(12, 2, 12, 0)
        self.name_lbl = QLabel("Выберите неоактив")
        self.name_lbl.setStyleSheet("font-weight: 600;")
        head.addWidget(self.name_lbl)
        head.addStretch()
        self.price_lbl = QLabel("")
        head.addWidget(self.price_lbl)
        lay.addLayout(head)

        pos_row = QHBoxLayout()
        pos_row.setContentsMargins(12, 0, 12, 0)
        self.pos_lbl = _row_label("")
        pos_row.addWidget(self.pos_lbl)
        pos_row.addStretch()
        self.pnl_lbl = QLabel("")
        self.pnl_lbl.setToolTip("Итог, если закрыть всю позицию прямо сейчас по стакану: "
                                "лонг - по стороне «Покупка», шорт - по стороне «Продажа»")
        pos_row.addWidget(self.pnl_lbl)
        lay.addLayout(pos_row)

        self.side_lbl = _row_label("")
        self.side_lbl.setContentsMargins(12, 0, 12, 0)
        self.side_lbl.setWordWrap(True)
        lay.addWidget(self.side_lbl)

        grid = QGridLayout()
        self.grid = grid
        grid.setContentsMargins(12, 4, 12, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        self.price_cap = _row_label("Цена срабатывания, $")
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 10_000_000)
        self.price.setDecimals(2)
        self.price.setKeyboardTracking(False)
        self.price.valueChanged.connect(self.recalc)

        self.trail_cap = _row_label("Отступ, %")
        self.trail = QDoubleSpinBox()
        self.trail.setRange(0.1, 50)
        self.trail.setValue(2.0)
        self.trail.setSingleStep(0.1)
        self.trail.valueChanged.connect(self.recalc)

        self.qty_cap = _row_label("Количество")
        self.qty = QSpinBox()
        self.qty.setRange(1, 1)
        self.qty.valueChanged.connect(self.recalc)

        self.col_cap = _row_label("Сторона стакана")
        self.column = QComboBox()
        self.column.addItem("Покупка", COL_BUY)
        self.column.addItem("Продажа", COL_SELL)
        self.column.currentIndexChanged.connect(self.recalc)

        self.mkt_price = QLineEdit()
        self.mkt_price.setPlaceholderText("Рыночная")
        self.mkt_price.setReadOnly(True)
        self.mkt_price.setEnabled(False)

        grid.addWidget(self.price_cap, 0, 0)
        grid.addWidget(self.trail_cap, 0, 0)
        grid.addWidget(self.qty_cap, 0, 1)
        self.price_box = with_steps(self.price)
        self.trail_box = with_steps(self.trail)
        self.qty_box = with_steps(self.qty)
        grid.addWidget(self.price_box, 1, 0)
        grid.addWidget(self.mkt_price, 1, 0)
        grid.addWidget(self.trail_box, 1, 0)
        grid.addWidget(self.qty_box, 1, 1)
        grid.addWidget(self.col_cap, 2, 0, 1, 2)
        grid.addWidget(self.column, 3, 0, 1, 2)
        lay.addLayout(grid)

        self.exec_box = QWidget()
        self.exec_box.setObjectName("clear")
        eb = QGridLayout(self.exec_box)
        eb.setContentsMargins(12, 2, 12, 0)
        eb.setHorizontalSpacing(8)
        eb.addWidget(_row_label("Исполнение"), 0, 0)
        self.slip_cap = _row_label("Проскальзывание, %")
        eb.addWidget(self.slip_cap, 0, 1)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.btn_market = QPushButton("Рыночная")
        self.btn_limit = QPushButton("Лимитная")
        self.exec_group = QButtonGroup(self)
        for i, b in enumerate((self.btn_market, self.btn_limit)):
            b.setCheckable(True)
            b.setObjectName("segLeft" if i == 0 else "segRight")
            self.exec_group.addButton(b)
            seg.addWidget(b)
        self.btn_market.setChecked(True)
        self.exec_group.buttonToggled.connect(self._on_exec)
        eb.addLayout(seg, 1, 0)
        self.slip = QDoubleSpinBox()
        self.slip.setRange(0.01, 5)
        self.slip.setValue(0.3)
        self.slip.setSingleStep(0.05)
        self.slip_box = with_steps(self.slip)
        eb.addWidget(self.slip_box, 1, 1)
        lay.addWidget(self.exec_box)

        # OCO
        oco = QHBoxLayout()
        oco.setContentsMargins(12, 2, 12, 0)
        self.oco_chk = QCheckBox("Добавить тейк-профит")
        self.oco_chk.toggled.connect(self._on_oco)
        oco.addWidget(self.oco_chk)
        self.oco_price = QDoubleSpinBox()
        self.oco_price.setRange(0, 10_000_000)
        self.oco_price.setDecimals(2)
        self.oco_price_box = with_steps(self.oco_price)
        self.oco_price_box.setVisible(False)
        oco.addWidget(self.oco_price_box)
        self.oco_box = QWidget()
        self.oco_box.setObjectName("clear")
        self.oco_box.setLayout(oco)
        lay.addWidget(self.oco_box)

        self.sep = QFrame()
        self.sep.setFrameShape(QFrame.HLine)
        self.sep.setStyleSheet("color: #2a3848;")
        lay.addWidget(self.sep)

        res = QGridLayout()
        res.setContentsMargins(12, 0, 12, 0)
        res.setVerticalSpacing(5)
        self.r_cost = QLabel()
        self.r_fill = QLabel()
        self.r_profit = QLabel()
        self.r_profit_cap = _row_label("Доход от продажи")
        self.r_fill_cap = _row_label("Исполнение по стакану сейчас")
        self.r_cost_cap = _row_label("Примерная стоимость")
        self.r_rate = QLabel()
        self.r_rate_cap = _row_label("Курс конвертации")
        rows = [(self.r_cost_cap, self.r_cost),
                (self.r_fill_cap, self.r_fill),
                (self.r_profit_cap, self.r_profit),
                (self.r_rate_cap, self.r_rate)]
        for i, (cap, val) in enumerate(rows):
            val.setAlignment(Qt.AlignRight)
            res.addWidget(cap, i, 0)
            res.addWidget(val, i, 1)
        lay.addLayout(res)

        boxes = QHBoxLayout()
        boxes.setContentsMargins(12, 4, 12, 0)
        self.box_pos = self._box("Позиция")
        self.box_can = self._box("Можно продать")
        boxes.addWidget(self.box_pos[0])
        boxes.addWidget(self.box_can[0])
        lay.addLayout(boxes)

        self.limits_box = QWidget()
        self.limits_box.setObjectName("clear")
        lg = QGridLayout(self.limits_box)
        lg.setContentsMargins(12, 4, 12, 0)
        lg.setSpacing(6)
        self.lim = {}
        for col, side in enumerate(("buy", "sell")):
            for row, (key, cap) in enumerate(((side, "Доступно"), (side + "_margin", "С плечом"))):
                b = self._box(cap)
                self.lim[key] = b[2]
                lg.addWidget(b[0], row, col)
        lay.addWidget(self.limits_box)

        self.err = QLabel("")
        self.err.setStyleSheet("color: #ff6b7a;")
        self.err.setContentsMargins(12, 0, 12, 0)
        self.err.setWordWrap(True)
        lay.addWidget(self.err)

        lay.addStretch()
        self.submit = QPushButton(BTN_TEXT[STOP])
        self.submit.setMinimumHeight(38)
        self.submit.clicked.connect(self._submit)
        sub = QHBoxLayout()
        sub.setContentsMargins(12, 0, 12, 0)
        sub.addWidget(self.submit)
        self.buy_btn = QPushButton("Купить")
        self.buy_btn.setObjectName("buy")
        self.sell_btn = QPushButton("Продать")
        self.sell_btn.setObjectName("sell")
        for b, side in ((self.buy_btn, "buy"), (self.sell_btn, "sell")):
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _=False, s=side: self._trade(s))
            sub.addWidget(b)
        lay.addLayout(sub)

        self.set_trading(False)
        self._on_tab(self.tabs.currentIndex())

    def _box(self, caption):
        f = QFrame()
        f.setObjectName("infoBox")
        h = QHBoxLayout(f)
        h.setContentsMargins(8, 6, 8, 6)
        cap = _row_label(caption)
        val = QLabel("—")
        h.addWidget(cap)
        h.addStretch()
        h.addWidget(val)
        return f, cap, val


    @property
    def kind(self):
        return KINDS[self.tabs.currentIndex()]

    def set_asset(self, asset, position, min_plate, decimals):
        changed = self.asset is None or asset is None or asset.uid != self.asset.uid
        self.asset = asset
        self.min_plate = min_plate
        self.dec = decimals
        for sb in (self.price, self.oco_price):
            sb.setDecimals(decimals)
            sb.setSingleStep(asset.step if asset else 0.01)
        if changed:
            self.book = None
            self.quote = None
            self.set_limits(None)
            self.price.setValue(0)
            self.oco_price.setValue(0)
            self.err.setText("")
        self.set_position(position)

    def set_position(self, position):
        self.position = position
        self._update_qty_range()
        self._update_texts()
        self.recalc()

    def _update_qty_range(self):
        if self.kind in TRADE_TABS:
            self.qty.setRange(1, 1_000_000)
        elif self.position:
            n = abs(self.position.qty)
            self.qty.setRange(1, n)
            if self.qty.value() > n:
                self.qty.setValue(n)
        else:
            self.qty.setRange(1, 1)

    def set_trading(self, on):
        for i in (0, 1):
            self.tabs.setTabVisible(i, on)
        #шесть вкладок в полные названия не влезают
        self.tabs.setTabText(2, "Стоп" if on else "Стоп-лосс")
        self.tabs.setTabText(3, "Тейк" if on else "Тейк-профит")
        if on:
            self.tabs.setCurrentIndex(0)
        elif self.kind in TRADE_TABS:
            self.tabs.setCurrentIndex(2)

    def set_limits(self, limits):
        self.limits = limits
        for key, lbl in self.lim.items():
            lbl.setText(str(limits.get(key, "—")) if limits else "—")

    def update_market(self, book, quote):
        first = self.quote is None
        self.book = book
        self.quote = quote
        if first:
            self._fill_default_price()
        self.recalc()


    def _direction(self):
        if self.position and self.position.is_short:
            return SHORT
        return LONG

    def _watch_price(self):
        q = self.quote
        if not q:
            return None
        if self.kind in TRADE_TABS:
            return q.bid
        if self.kind == ALERT:
            return q.bid if self.column.currentData() == COL_BUY else q.ask
        return q.bid if self._direction() == LONG else q.ask

    def _fill_default_price(self):
        p = self._watch_price()
        if p and not self.price.value():
            self.price.setValue(p)
        if p and not self.oco_price.value():
            self.oco_price.setValue(p)

    def _on_tab(self, i):
        if i >= 0 and not self.tabs.isTabVisible(i):
            self.tabs.setCurrentIndex(2)
            return
        k = self.kind
        is_alert = k == ALERT
        is_trade = k in TRADE_TABS
        self.price_cap.setText("Цена исполнения, $" if is_trade else "Цена срабатывания, $")
        self.price_cap.setVisible(k != TRAIL)
        self.price_box.setVisible(k not in (TRAIL, TRADE_MKT))
        self.mkt_price.setVisible(k == TRADE_MKT)
        self.trail_cap.setVisible(k == TRAIL)
        self.trail_box.setVisible(k == TRAIL)
        self.qty_cap.setVisible(not is_alert)
        self.qty_box.setVisible(not is_alert)
        self.grid.addWidget(self.price_box, 1, 0, 1, 2 if is_alert else 1)
        for w in (self.col_cap, self.column):
            w.setVisible(is_alert)
        self.exec_box.setVisible(not is_alert and not is_trade)
        self.oco_box.setVisible(k in (STOP, TAKE))
        self.oco_chk.setText("Добавить тейк-профит" if k == STOP else "Добавить стоп-лосс")
        for w in (self.sep, self.r_cost_cap, self.r_cost, self.r_fill_cap, self.r_fill):
            w.setVisible(not is_alert)
        for w in (self.r_profit_cap, self.r_profit):
            w.setVisible(not is_alert and not is_trade)
        for w in (self.r_rate_cap, self.r_rate):
            w.setVisible(is_trade)
        self.r_cost_cap.setText("Стоимость" if is_trade else "Примерная стоимость")
        self.box_pos[0].setVisible(not is_alert and not is_trade)
        self.box_can[0].setVisible(not is_alert and not is_trade)
        self.limits_box.setVisible(is_trade)

        self.submit.setVisible(not is_trade)
        self.buy_btn.setVisible(is_trade)
        self.sell_btn.setVisible(is_trade)
        self.err.setText("")
        self._update_qty_range()
        self._update_texts()
        self.recalc()

    def _on_exec(self, *_):
        self.slip_cap.setVisible(self.btn_limit.isChecked())
        self.slip_box.setVisible(self.btn_limit.isChecked())

    def _on_oco(self, on):
        self.oco_price_box.setVisible(on)
        if on and not self.oco_price.value():
            self._fill_default_price()

    def _style_submit(self):
        # цвет по действию: стоп шорта закрывается покупкой, зелёный
        k = self.kind
        if k in TRADE_TABS:
            return
        if k == ALERT:
            name = "primary"
            text = BTN_TEXT[k]
        else:
            name = "sell" if self._direction() == LONG else "buy"
            text = BTN_TEXT[k] + (" (продажа)" if name == "sell" else " (покупка)")
        self.submit.setText(text)
        if self.submit.objectName() != name:
            self.submit.setObjectName(name)
            # после смены objectName стиль сам не обновится
            self.submit.style().unpolish(self.submit)
            self.submit.style().polish(self.submit)

    def _update_texts(self):
        self._style_submit()
        a = self.asset
        if not a:
            self.name_lbl.setText("Выберите неоактив")
            self.pos_lbl.setText("")
            self.side_lbl.setText("")
            return
        self.name_lbl.setText(f"{a.name}  ·  {a.ticker}")
        p = self.position
        if p:
            side = "Шорт" if p.is_short else "Лонг"
            self.pos_lbl.setText(f"{side} {abs(p.qty)} · ср. цена {fmt(p.avg_price, self.dec)} $")
        else:
            self.pos_lbl.setText("Нет открытой позиции")

        if self.kind == TRADE_MKT:
            self.side_lbl.setText("Сделка сразу уходит на биржу по лучшей цене стакана")
        elif self.kind == TRADE_LMT:
            self.side_lbl.setText("Заявка встанет в стакан и будет ждать исполнения до конца дня")
        elif self.kind == ALERT:
            self.side_lbl.setText("Уведомление без заявки: сработает, когда цена на выбранной стороне стакана дойдёт до заданной")
        elif self._direction() == LONG:
            self.side_lbl.setText("Проверка по стороне «Покупка» · закрытие лонга продажей")
        else:
            self.side_lbl.setText("Проверка по стороне «Продажа» · закрытие шорта покупкой")

        close_word = "продать" if self._direction() == LONG else "купить"
        self.box_can[1].setText(f"Можно {close_word}")
        self.box_pos[2].setText(str(p.qty) if p else "0")
        self.box_can[2].setText(str(abs(p.qty)) if p else "0")
        self.r_profit_cap.setText("Доход от продажи" if self._direction() == LONG
                                  else "Доход от покупки")

    def _update_pnl(self):
        p, a = self.position, self.asset
        res = calc.close_now(p.qty, p.avg_price, self.book, a.size, a.lot) \
            if p and a and self.book else None
        if res is None:
            self.pnl_lbl.setText("")
            return
        _, _, usd, pct = res
        sign = "+" if usd > 0 else ""
        color = "#3ddc97" if usd > 0 else "#ff6b7a" if usd < 0 else "#e1e7ef"
        self.pnl_lbl.setText(f"{sign}{fmt(usd)} $ ({sign}{fmt(pct)}%)")
        self.pnl_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")

    def recalc(self, *_):
        a = self.asset
        if not a:
            self.pnl_lbl.setText("")
            return
        self._update_pnl()
        q = self.quote
        if q:
            p = self._watch_price()
            self.price_lbl.setText(f"{fmt(p, self.dec)} $" if p else "")

        k = self.kind
        if k in TRADE_TABS:
            self._recalc_trade()
            return
        qty = 1 if k == ALERT else self.qty.value()

        if k == TRAIL:
            base = self._watch_price()
            if base:
                shift = self.trail.value() / 100
                price = base * (1 - shift) if self._direction() == LONG else base * (1 + shift)
            else:
                price = None
        else:
            price = self.price.value() or None

        if price:
            self.r_cost.setText(f"{fmt(calc.order_value(price, qty, a.size, a.lot))} $")
        else:
            self.r_cost.setText("—")

        self.r_fill.setStyleSheet("")
        if self.book and k != ALERT:
            levels = self.book.bids if self._direction() == LONG else self.book.asks
            avg, got = fill_price(levels, qty)
            if avg is None:
                self.r_fill.setText("стакан пуст")
            else:
                txt = f"{fmt(avg, self.dec)} $"
                if got < qty:
                    txt += f" · в стакане только {got}"
                    self.r_fill.setStyleSheet("color: #f2c14e;")
                elif fits_in_plate(levels, qty, self.min_plate):
                    txt += " · в плите"
                else:
                    txt += " · больше плиты"
                    self.r_fill.setStyleSheet("color: #f2c14e;")
                self.r_fill.setText(txt)
        elif k == ALERT:
            self.r_fill.setText("—")
        else:
            self.r_fill.setText("нет стакана")

        pos = self.position
        if pos and price and k != ALERT:
            usd, pct = calc.close_profit(pos.avg_price, price, qty, a.size, a.lot,
                                         short=pos.is_short)
            sign = "+" if usd > 0 else ""
            self.r_profit.setText(f"{sign}{fmt(usd)} $ ({sign}{fmt(pct)}%)")
            color = "#3ddc97" if usd > 0 else "#ff6b7a" if usd < 0 else "#e1e7ef"
            self.r_profit.setStyleSheet(f"color: {color};")
        else:
            self.r_profit.setText("—")
            self.r_profit.setStyleSheet("")

    def _recalc_trade(self):
        a = self.asset
        qty = self.qty.value()
        q = self.quote
        #рыночную считаем по плите продажи, как терминал
        if self.kind == TRADE_LMT:
            price = self.price.value() or None
        else:
            price = q.ask if q and q.ask else None
        self.r_cost.setText(f"{fmt(calc.order_value(price, qty, a.size, a.lot))} $"
                            if price else "—")

        self.r_fill.setStyleSheet("")
        if self.book:
            parts = []
            warn = False
            for name, levels in (("купить", self.book.asks), ("продать", self.book.bids)):
                avg, got = fill_price(levels, qty)
                if avg is None:
                    parts.append(f"{name} —")
                    continue
                parts.append(f"{name} {fmt(avg, self.dec)}")
                if got < qty or not fits_in_plate(levels, qty, self.min_plate):
                    warn = True
            self.r_fill.setText(" · ".join(parts))
            if warn:
                self.r_fill.setStyleSheet("color: #f2c14e;")
                self.r_fill.setToolTip("Объём больше плиты - часть исполнится по худшим ценам")
            else:
                self.r_fill.setToolTip("")
        else:
            self.r_fill.setText("нет стакана")

        # step_amount в рублях
        if a.step and a.size:
            rate = a.step_amount / a.step / a.size
            self.r_rate.setText(f"1 $ = {fmt(rate)} ₽")
        else:
            self.r_rate.setText("—")

    def _trade(self, side):
        a = self.asset
        if not a:
            self.err.setText("Выберите неоактив в списке слева")
            return
        qty = self.qty.value()
        price = None
        if self.kind == TRADE_LMT:
            price = self.price.value()
            if not price:
                self.err.setText("Укажите цену")
                return
        if self.limits:
            can = max(self.limits.get(side, 0), self.limits.get(side + "_margin", 0))
            if qty > can:
                word = "купить" if side == "buy" else "продать"
                self.err.setText(f"Недостаточно средств: можно {word} не больше {can}")
                return
        self.err.setText("")
        self.trade.emit(side, qty, price)


    def _submit(self):
        a = self.asset
        if not a:
            self.err.setText("Выберите неоактив в списке слева")
            return
        k = self.kind

        if k == ALERT:
            if not self.price.value():
                self.err.setText("Укажите цену")
                return
            #ниже заданной,ждём роста, выше,падения
            cur = self._watch_price()
            if not cur:
                self.err.setText("Нет текущей цены, дождитесь стакана")
                return
            target = self.price.value()
            if abs(target - cur) < 1e-9:
                self.err.setText("Цена уже на этом уровне")
                return
            o = VirtualOrder(uid=a.uid, ticker=a.ticker, kind=ALERT, price=target,
                             column=self.column.currentData(), above=target > cur)
            self.err.setText("")
            self.created.emit([o])
            return

        pos = self.position
        if not pos:
            self.err.setText("Нет открытой позиции по этому активу")
            return
        if k != TRAIL and not self.price.value():
            self.err.setText("Укажите цену срабатывания")
            return

        #сработает сразу,скорее всего ошибся в цене
        cur = self._watch_price()
        direction = self._direction()
        if cur and k in (STOP, TAKE):
            probe = VirtualOrder(uid="", ticker="", kind=k, price=self.price.value(),
                                 direction=direction)
            if probe.condition(cur):
                self.err.setText("С такой ценой заявка сработает сразу, текущая цена "
                                 f"{fmt(cur, self.dec)} $")
                return

        common = dict(uid=a.uid, ticker=a.ticker, qty=self.qty.value(), direction=direction,
                      exec_type=LIMIT if self.btn_limit.isChecked() else MARKET,
                      slippage=self.slip.value())
        if k == TRAIL:
            orders = [VirtualOrder(kind=TRAIL, trail_pct=self.trail.value(), **common)]
        else:
            orders = [VirtualOrder(kind=k, price=self.price.value(), **common)]
            if self.oco_chk.isChecked():
                other = TAKE if k == STOP else STOP
                oco_id = uuid.uuid4().hex[:8]
                orders[0].oco = oco_id
                orders.append(VirtualOrder(kind=other, price=self.oco_price.value(),
                                           oco=oco_id, **common))
                if cur and orders[1].condition(cur):
                    self.err.setText("Цена второй заявки сработает сразу, проверьте её")
                    return

        self.err.setText("")
        self.created.emit(orders)
