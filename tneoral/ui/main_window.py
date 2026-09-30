import time
import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from tneoral import token_store
from tneoral.broker.trading import OrderRequest
from tneoral.broker.worker import BrokerWorker
from tneoral.core import calc
from tneoral.core.guard import Guard
from tneoral.core.orders import ALERT, OrderBookWatcher
from tneoral.settings import Settings
from tneoral.storage import Storage

from .assets_list import AssetsList
from .dialogs import GuardDialog, TokenDialog
from .history_view import HistoryView
from .log_view import LogView
from .order_form import TRADE_TABS, OrderForm
from .orderbook_view import OrderBookView, fmt
from .orders_table import KIND_NAMES, OrdersTable, describe
from .positions_table import PositionsTable
from .tray import Tray, make_icon
from .widgets import ask


def decimals_for(step):
    s = f"{step:.10f}".rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TNeoRal")
        self.setWindowIcon(make_icon())
        self.resize(1360, 820)

        self.settings = Settings().load()
        self.storage = Storage()
        self.watcher = OrderBookWatcher()
        for o in self.storage.active_orders():
            self.watcher.add(o)

        self.worker = None
        self.assets = {}
        self.guards = {}
        self.books = {}
        self.quotes = {}
        self.trading = {}
        self.positions = {}
        self.dirty = set()    #что поменялось с прошлой перерисовки
        self.manual = {}
        self.wide_warned = set()
        self._positions_changed = True
        self._orphan_seen = set()
        self.pending = {}  #лоты в отправке, чтобы не продать дважды
        self.sent = {}
        self.cur_uid = None
        self._quitting = False
        self._tray_hint_shown = False

        self._build()
        self.tray = Tray(self)
        self.tray.show()

        for ts, ticker, kind, text in self.storage.last_journal(100):
            self.log_view.add(ts, ticker, kind, text)
        for o in self.storage.stuck_orders():
            o.status = "error"
            self.storage.save_order(o)
            self.journal(o.ticker, "error", f"{KIND_NAMES[o.kind]} отправлялся, когда приложение "
                                            "закрылось - статус неизвестен, проверьте в терминале")
        self._refresh_orders()

        #10 раз в секунду а не на каждый стакан,иначе тормозит
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(100)

        self.limits_timer = QTimer(self)
        self.limits_timer.timeout.connect(self._ask_limits)
        self.limits_timer.start(3000)

        self.history_timer = QTimer(self)
        self.history_timer.timeout.connect(self._history_tick)
        self.history_timer.start(60_000)


    def _build(self):
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        top = QHBoxLayout()
        name = QLabel("TNeoRal")
        name.setStyleSheet("font-size: 12pt; font-weight: 600;")
        top.addWidget(name)
        top.addSpacing(8)
        self.mode_btn = QPushButton()
        self.mode_btn.clicked.connect(self._toggle_mode)
        top.addWidget(self.mode_btn)
        self._update_mode_btn()
        top.addSpacing(8)
        self.trade_chk = QCheckBox("Торговля")
        self.trade_chk.setToolTip("Показать вкладки «Рыночная» и «Лимитная» для обычных сделок")
        top.addWidget(self.trade_chk)
        top.addSpacing(8)
        self.conn_lbl = QLabel("Не подключено")
        self.conn_lbl.setProperty("muted", True)
        top.addWidget(self.conn_lbl)
        top.addStretch()

        settings_btn = QPushButton("Настройки")
        settings_btn.clicked.connect(self._open_settings)
        top.addWidget(settings_btn)

        conn_btn = QPushButton("Подключение")
        #clicked передаёт checked
        conn_btn.clicked.connect(lambda: self.ask_token())
        top.addWidget(conn_btn)
        lay.addLayout(top)

        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.setHandleWidth(6)

        self.assets_list = AssetsList()
        self.assets_list.selected.connect(self._select)
        self.hsplit.addWidget(self.assets_list)

        center = QFrame()
        center.setObjectName("panel")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(10, 6, 10, 6)
        self.title_lbl = QLabel("")
        self.title_lbl.setObjectName("panelTitle")
        head.addWidget(self.title_lbl)
        head.addStretch()
        self.state_lbl = QLabel("")
        head.addWidget(self.state_lbl)
        cl.addLayout(head)
        self.book_view = OrderBookView()
        cl.addWidget(self.book_view, 1)

        self.csplit = QSplitter(Qt.Vertical)
        self.csplit.setHandleWidth(6)
        self.csplit.addWidget(center)
        self.positions_table = PositionsTable()
        self.positions_table.selected.connect(self.assets_list.select_uid)
        self.csplit.addWidget(self.positions_table)
        self.csplit.setSizes([520, 170])
        self.hsplit.addWidget(self.csplit)

        right = QSplitter(Qt.Vertical)
        right.setHandleWidth(6)
        self.form = OrderForm()
        self.form.created.connect(self._on_created)
        self.form.trade.connect(self._on_trade)
        self.trade_chk.setChecked(self.settings.trading)
        self.form.set_trading(self.settings.trading)
        self.trade_chk.toggled.connect(self._toggle_trading)
        self.form.tabs.currentChanged.connect(lambda _: self._ask_limits())
        right.addWidget(self.form)
        self.orders_table = OrdersTable()
        self.orders_table.cancel_clicked.connect(self._cancel_order)
        right.addWidget(self.orders_table)
        right.setSizes([520, 260])
        self.hsplit.addWidget(right)
        self.hsplit.setSizes([330, 560, 400])

        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.setHandleWidth(6)
        self.vsplit.addWidget(self.hsplit)
        self.bottom_tabs = QTabWidget()
        self.log_view = LogView()
        self.log_view.title.hide()
        self.bottom_tabs.addTab(self.log_view, "Журнал")
        self.history_view = HistoryView()
        self.history_view.refresh.connect(self._ask_history)
        self.bottom_tabs.addTab(self.history_view, "История сделок")
        self.bottom_tabs.currentChanged.connect(
            lambda i: self.history_view.ask() if self.bottom_tabs.widget(i) is self.history_view else None)
        self.vsplit.addWidget(self.bottom_tabs)
        self.vsplit.setSizes([640, 160])
        lay.addWidget(self.vsplit, 1)
        self.setCentralWidget(root)

    def _open_settings(self):
        a = self.assets.get(self.cur_uid)
        dlg = GuardDialog(self.settings, a.ticker if a else None, self)
        if dlg.exec():
            for uid, g in self.guards.items():
                g.s = self.settings.guard_for(self.assets[uid].ticker)
            self.dirty.add(self.cur_uid)


    def start(self):
        token = token_store.load_token()
        if token:
            self._connect(token)
        else:
            self.ask_token()

    def ask_token(self, error=""):
        dlg = TokenDialog(self, error)
        if dlg.exec():
            self._connect(dlg.token)
        elif not token_store.load_token():
            self._disconnect()
            self.conn_lbl.setText("Не подключено")

    def _connect(self, token):
        self._disconnect()
        self.conn_lbl.setText("Подключаюсь...")
        w = BrokerWorker(token, self)
        w.connected.connect(self._on_connected)
        w.status.connect(self.conn_lbl.setText)
        w.failed.connect(self._on_failed)
        w.assets_loaded.connect(self._on_assets)
        w.book.connect(self._on_book)
        w.trading.connect(self._on_trading)
        w.online.connect(self._on_online)
        w.positions.connect(self._on_positions)
        w.order_done.connect(self._on_order_done)
        w.max_lots.connect(self._on_max_lots)
        w.history.connect(self.history_view.show_trades)
        self.worker = w
        w.start()

    def _disconnect(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.guards.clear()
        self.books.clear()
        self.quotes.clear()
        self.book_view.clear()

    def _on_connected(self, account_id):
        self.conn_lbl.setText("Загружаю неоактивы...")

    def _on_failed(self, msg):
        self.conn_lbl.setText("Ошибка подключения")
        self.journal("", "error", msg)
        #после того как поток закончится
        QTimer.singleShot(0, lambda: self.ask_token(msg))

    def _on_assets(self, assets):
        self.assets = {a.uid: a for a in assets}
        for a in assets:
            self.guards[a.uid] = Guard(self.settings.guard_for(a.ticker))
            self.trading.setdefault(a.uid, True)
        self.assets_list.set_assets(assets)
        self.conn_lbl.setText(f"Неоактивов: {len(assets)}")
        self.history_view.set_assets(assets)
        QTimer.singleShot(3000, self.history_view.ask)
        self._refresh_orders()

    def _on_online(self, ok):
        for g in self.guards.values():
            g.set_online(ok)
        txt = f"Неоактивов: {len(self.assets)}"
        self.conn_lbl.setText(txt + (" · стрим подключён" if ok else " · нет связи, переподключаюсь"))
        if not ok and self.watcher.active():
            self.journal("", "error", "Связь со стримом потеряна, заявки не проверяются")

    def _on_trading(self, uid, active):
        was = self.trading.get(uid)
        self.trading[uid] = active
        g = self.guards.get(uid)
        if g:
            g.set_trading(active, time.monotonic())
        if was is not None and was != active and self.watcher.active(uid):
            a = self.assets.get(uid)
            self.journal(a.ticker if a else "", "info",
                         "торги открылись" if active else "торги остановлены")
        self.dirty.add(uid)

    def _on_positions(self, positions):
        self.positions = positions
        if self.cur_uid:
            self.form.set_position(positions.get(self.cur_uid))
        self._positions_changed = True
        self.history_view.set_positions(positions)
        self._drop_orphan_orders(positions)

    def _drop_orphan_orders(self, positions):
        #позиции нет два снимка подряд,снимаем. одному кривому ответу API не верим
        changed = False
        for o in self.watcher.active():
            if o.kind == ALERT:
                continue
            pos = positions.get(o.uid)
            gone = pos is None or pos.is_short != (o.direction == "short")
            if not gone:
                self._orphan_seen.discard(o.id)
                continue
            if o.id not in self._orphan_seen:
                self._orphan_seen.add(o.id)
                continue
            self._orphan_seen.discard(o.id)
            o.status = "cancelled"
            self.storage.save_order(o)
            why = "позиция закрыта" if pos is None else "позиция развернулась"
            self.journal(o.ticker, "info", f"{KIND_NAMES[o.kind]} снят автоматически: {why}")
            changed = True
        if changed:
            self._refresh_orders()

    def _on_book(self, uid, book):
        g = self.guards.get(uid)
        if g is None:
            return
        prev = self.quotes.get(uid)
        q = g.update(book, book.ts)
        self.books[uid] = book
        self.quotes[uid] = q
        self.dirty.add(uid)

        orders = self.watcher.active(uid)
        if not orders:
            self.wide_warned.discard(uid)
            return
        self._log_guard_changes(uid, prev, q)
        self._check_wide(uid, q, g)

        before = {o.id: o.status for o in orders}
        fired = self.watcher.on_quote(uid, q, book.ts, g.s.confirm_time)
        for o in fired:
            self._on_fired(o, q)
        changed = [o for o in self.watcher.orders if o.id in before and o.status != before[o.id]]
        for o in changed:
            if o.status == "cancelled":
                self.journal(o.ticker, "info", f"{KIND_NAMES[o.kind]} снят по OCO")
            self.storage.save_order(o)
        if changed:
            self._refresh_orders()

    def _log_guard_changes(self, uid, prev, q):
        # только переходы, иначе по 10 строк в секунду
        a = self.assets[uid]
        dec = decimals_for(a.step)
        if prev is None:
            return
        if q.bid_held and not prev.bid_held:
            self.journal(a.ticker, "filter",
                         f"плита покупки {fmt(prev.bid, dec)} пропала, держу цену до перестановки")
        if q.ask_held and not prev.ask_held:
            self.journal(a.ticker, "filter",
                         f"плита продажи {fmt(prev.ask, dec)} пропала, держу цену до перестановки")
        if prev.ok and not q.ok:
            self.journal(a.ticker, "filter", f"проверка приостановлена: {q.reason}")
        if not prev.ok and q.ok:
            self.journal(a.ticker, "info", "стакан снова чистый")

    def _check_wide(self, uid, q, g):
        a = self.assets[uid]
        if q.wide_for >= g.s.wide_warn and uid not in self.wide_warned:
            self.wide_warned.add(uid)
            text = (f"Спред {fmt(q.spread)}% держится уже {int(q.wide_for)} с - "
                    "заявки заблокированы, проверьте вручную")
            self.journal(a.ticker, "error", text)
            self.tray.notify(f"TNeoRal · {a.ticker}", text, self.settings.sound)
        elif uid in self.wide_warned and q.ok:
            self.wide_warned.discard(uid)
            text = "Спред снова в норме, заявки работают"
            self.journal(a.ticker, "info", text)
            self.tray.notify(f"TNeoRal · {a.ticker}", text, sound=False)

    def _on_fired(self, o, q):
        a = self.assets.get(o.uid)
        dec = decimals_for(a.step) if a else 2
        price = o.watch_price(q)
        if o.kind == ALERT:
            o.status = "done"
            text = f"Уведомление: {describe(o, dec)}, сейчас {fmt(price, dec)} $"
        elif not self.settings.live:
            o.status = "done"
            text = (f"{KIND_NAMES[o.kind]} сработал: {describe(o, dec)}, "
                    f"цена {fmt(price, dec)} $, {o.qty} шт. (режим уведомлений, заявка не отправлена)")
        else:
            text = self._send(o, q, a, dec)
        self.journal(o.ticker, "fire", text)
        self.tray.notify(f"TNeoRal · {o.ticker}", text, self.settings.sound)

    def _send(self, o, q, a, dec):
        name = KIND_NAMES[o.kind]
        side = o.close_side()
        pos = self.positions.get(o.uid)

        # позицию могли закрыть руками. главное, не открыть обратную
        want_long = side == "sell"
        if pos is None or pos.qty == 0 or (pos.qty > 0) != want_long:
            o.status = "error"
            return f"{name} сработал, но позиции уже нет - заявка не отправлена"
        free = abs(pos.qty) - self.pending.get(o.uid, 0)
        qty = min(o.qty, free)
        if qty <= 0:
            o.status = "error"
            return f"{name} сработал, но вся позиция уже закрывается другой заявкой"
        if self.worker is None:
            o.status = "error"
            return f"{name} сработал, но нет подключения - заявка НЕ отправлена"

        plate = q.bid if side == "sell" else q.ask
        limit = None
        if o.exec_type != "market":
            limit = calc.limit_price(side, plate, o.slippage, a.step if a else 0.01)

        o.status = "sending"
        self.pending[o.uid] = self.pending.get(o.uid, 0) + qty
        self.sent[o.id] = qty
        self.worker.submit(OrderRequest(
            local_id=o.id, uid=o.uid, ticker=o.ticker, side=side, qty=qty,
            market=limit is None, price=limit, request_id=str(uuid.uuid4())))

        what = "продажу" if side == "sell" else "покупку"
        how = "рыночную" if limit is None else f"лимитную по {fmt(limit, dec)} $"
        cut = f" (урезано до позиции, было {o.qty})" if qty < o.qty else ""
        return (f"{name} сработал при {fmt(plate, dec)} $: отправляю {how} заявку "
                f"на {what} {qty} шт.{cut}")


    def _toggle_trading(self, on):
        self.settings.trading = on
        self.settings.save()
        self.form.set_trading(on)
        if on:
            self._ask_limits()

    def _ask_limits(self):
        if self.worker and self.cur_uid and self.form.kind in TRADE_TABS:
            self.worker.request_max_lots(self.cur_uid)

    def _on_max_lots(self, uid, limits):
        if uid == self.cur_uid:
            self.form.set_limits(limits)

    def _on_trade(self, side, qty, price):
        a = self.assets.get(self.cur_uid)
        if a is None:
            return
        if self.worker is None:
            self.journal(a.ticker, "error", "Нет подключения, сделка не отправлена")
            return
        dec = decimals_for(a.step)
        word = "Купить" if side == "buy" else "Продать"
        how = "по рыночной цене" if price is None else f"по {fmt(price, dec)} $ (лимитная)"
        if self.settings.confirm_trades:
            if not ask(self, "Подтвердите сделку", f"{word} {qty} шт. {a.ticker} {how}?"):
                return
        req = OrderRequest(local_id=0, uid=a.uid, ticker=a.ticker, side=side, qty=qty,
                           market=price is None, price=price, request_id=str(uuid.uuid4()),
                           keep=price is not None, manual=True)
        self.manual[req.request_id] = req
        self.worker.submit(req)
        self.journal(a.ticker, "info", f"{word} {qty} шт. {how}: заявка отправлена")

    def _ask_history(self, days=None):
        if self.worker:
            self.worker.request_history(days or 90)

    def _history_tick(self):
        if self.bottom_tabs.currentWidget() is self.history_view:
            self._ask_history()

    def _history_after_trade(self):
        # в API операция появляется не сразу
        QTimer.singleShot(2000, self._ask_history)

    def _on_manual_done(self, req, res):
        a = self.assets.get(req.uid)
        dec = decimals_for(a.step) if a else 2
        word = "Куплено" if req.side == "buy" else "Продано"
        if res.ok and res.lots_executed > 0:
            price = f" по {fmt(res.avg_price, dec)} $" if res.avg_price else ""
            text, kind = f"{word} {res.lots_executed} из {req.qty}{price}", "fire"
        elif res.ok and not req.market and res.status in ("NEW", "PARTIALLYFILL", ""):
            #TODO: показывать выставленные лимитки списком и отменять их отсюда, пока только из терминала
            text, kind = (f"Лимитная заявка {req.qty} шт. по {fmt(req.price, dec)} $ "
                          "выставлена и ждёт исполнения"), "info"
        else:
            why = res.message or res.status
            text, kind = f"Сделка не прошла: {why}", "error"
        self.journal(req.ticker, kind, text)
        self.tray.notify(f"TNeoRal · {req.ticker}", text, self.settings.sound)
        self._ask_limits()
        self._history_after_trade()

    def _on_order_done(self, res):
        req = self.manual.pop(res.request_id, None)
        if req is not None:
            self._on_manual_done(req, res)
            return
        o = next((x for x in self.watcher.orders if x.id == res.local_id), None)
        if o is None:
            return
        sent = self.sent.pop(o.id, res.lots_requested)
        self.pending[o.uid] = max(0, self.pending.get(o.uid, 0) - sent)
        a = self.assets.get(o.uid)
        dec = decimals_for(a.step) if a else 2
        name = KIND_NAMES[o.kind]

        if res.ok and res.lots_executed > 0:
            o.status = "done"
            price = f" по {fmt(res.avg_price, dec)} $" if res.avg_price else ""
            text = f"{name}: исполнено {res.lots_executed} из {sent}{price}"
            kind = "fire"
            if res.lots_executed < sent:
                text += ". Остаток позиции без защиты - проверьте в терминале!"
                kind = "error"
        else:
            o.status = "error"
            why = res.message or res.status
            text = f"{name}: заявка не исполнена ({why}). Проверьте позицию в терминале!"
            kind = "error"

        self.storage.save_order(o)
        self.journal(o.ticker, kind, text)
        self.tray.notify(f"TNeoRal · {o.ticker}", text, self.settings.sound)
        self._refresh_orders()
        self._history_after_trade()


    def _update_mode_btn(self):
        live = self.settings.live
        self.mode_btn.setText("Боевой режим" if live else "Только уведомления")
        self.mode_btn.setObjectName("modeLive" if live else "modeNotify")
        self.mode_btn.setToolTip(
            "При срабатывании заявки отправляются на биржу. Нажмите, чтобы выключить"
            if live else
            "Заявки на биржу не отправляются, только уведомления. Нажмите, чтобы включить боевой режим")
        self.mode_btn.style().unpolish(self.mode_btn)
        self.mode_btn.style().polish(self.mode_btn)

    def _toggle_mode(self):
        if not self.settings.live:
            ok = ask(
                self, "Боевой режим",
                "В боевом режиме при срабатывании стоп-лосса, тейк-профита или трейлинга "
                "приложение само отправит заявку на биржу.\n\n"
                "Заявки проверяются, только пока приложение запущено и есть связь. "
                "Если компьютер выключится или пропадёт интернет, защиты не будет.\n\n"
                "Включить боевой режим?",
                default_yes=False)
            if not ok:
                return
        self.settings.live = not self.settings.live
        self.settings.save()
        self._update_mode_btn()
        self.journal("", "error" if self.settings.live else "info",
                     "включён БОЕВОЙ режим" if self.settings.live else "включён режим уведомлений")


    def _on_created(self, orders):
        if self.settings.live and orders[0].kind != ALERT:
            a = self.assets.get(orders[0].uid)
            dec = decimals_for(a.step) if a else 2
            lines = []
            for o in orders:
                how = "рыночная" if o.exec_type == "market" else f"лимитная ±{fmt(o.slippage)}%"
                lines.append(f"• {KIND_NAMES[o.kind]}: {describe(o, dec)}, {o.qty} шт., {how}")
            text = (f"{orders[0].ticker}\n\n" + "\n".join(lines) +
                    "\n\nПри срабатывании заявка уйдёт на биржу.")
            if not ask(self, "Подтвердите заявку", text):
                return
        for o in orders:
            self.watcher.add(o)
            self.storage.save_order(o)
            a = self.assets.get(o.uid)
            dec = decimals_for(a.step) if a else 2
            what = KIND_NAMES[o.kind] + (" (OCO)" if o.oco else "")
            self.journal(o.ticker, "info", f"создан {what}: {describe(o, dec)}")
        self._refresh_orders()

    def _cancel_order(self, oid):
        if self.watcher.cancel(oid):
            o = next(x for x in self.watcher.orders if x.id == oid)
            self.storage.save_order(o)
            self.journal(o.ticker, "info", f"{KIND_NAMES[o.kind]} отменён")
            self._refresh_orders()

    def _refresh_orders(self):
        def dec(uid):
            a = self.assets.get(uid)
            return decimals_for(a.step) if a else 2
        self.orders_table.show_orders(self.watcher.active(), dec)

    def journal(self, ticker, kind, text):
        ts = self.storage.log(ticker, kind, text)
        self.log_view.add(ts, ticker, kind, text)


    def _select(self, uid):
        self.cur_uid = uid
        a = self.assets.get(uid)
        self.title_lbl.setText(f"{a.name}  ·  {a.ticker}" if a else "")
        g = self.guards.get(uid)
        self.form.set_asset(a, self.positions.get(uid), g.s.min_plate if g else 20,
                            decimals_for(a.step))
        self._ask_limits()
        self.dirty.add(uid)

    def _refresh(self):
        if self._positions_changed or self.dirty & self.positions.keys():
            self._positions_changed = False
            self.positions_table.update_all(
                self.positions, self.assets, self.books, self.quotes,
                lambda uid: decimals_for(self.assets[uid].step))
        if not self.dirty:
            return
        for uid in self.dirty:
            q = self.quotes.get(uid)
            a = self.assets.get(uid)
            if q and a:
                self.assets_list.update_quote(uid, q, self.trading.get(uid, True),
                                              decimals_for(a.step))
        if self.cur_uid in self.dirty:
            self._show_current()
        trails = tuple((o.id, o.extreme) for o in self.watcher.active() if o.kind == "trail")
        if trails != getattr(self, "_last_trails", ()):
            #сохраняем сразу иначе после перезапуска стоп уедет назад
            old = dict(getattr(self, "_last_trails", ()))
            for o in self.watcher.active():
                if o.kind == "trail" and old.get(o.id) != o.extreme:
                    self.storage.save_order(o)
            self._last_trails = trails
            self._refresh_orders()
        self.dirty.clear()

    def _show_current(self):
        uid = self.cur_uid
        book, q, a = self.books.get(uid), self.quotes.get(uid), self.assets.get(uid)
        if not book or not a:
            self.book_view.clear()
            self.state_lbl.setText("")
            return
        g = self.guards[uid]
        self.book_view.set_data(book, q, g.s.min_plate, decimals_for(a.step))
        self.form.update_market(book, q)
        if not self.trading.get(uid, True):
            self.state_lbl.setText("торги закрыты")
            self.state_lbl.setStyleSheet("color: #8e9bab;")
        elif q.ok:
            self.state_lbl.setText("стакан чистый")
            self.state_lbl.setStyleSheet("color: #3ddc97;")
        else:
            self.state_lbl.setText(q.reason)
            self.state_lbl.setStyleSheet("color: #f2c14e;")


    def closeEvent(self, e):
        if self.settings.to_tray and not self._quitting:
            e.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self.tray.notify("TNeoRal работает в фоне",
                                 "Заявки проверяются. Выход - через меню значка в трее",
                                 sound=False)
                self._tray_hint_shown = True
            return
        self._disconnect()
        self.storage.close()
        self.tray.hide()
        super().closeEvent(e)
        QApplication.quit()

    def really_quit(self):
        self._quitting = True
        self.close()
