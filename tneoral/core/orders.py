# виртуальные заявки: на бирже их нет пока не сработают.
# лонг смотрим по "Покупке" шорт по "Продаже", по этим ценам можно выйти прямо сейчас

import itertools
from dataclasses import dataclass

STOP = "stop"
TAKE = "take"
TRAIL = "trail"
ALERT = "alert"

LONG = "long"
SHORT = "short"

COL_BUY = "buy"    # "Покупка"
COL_SELL = "sell"  # "Продажа"

MARKET = "market"
LIMIT = "limit"

_ids = itertools.count(1)


def continue_ids_from(last_id):
    global _ids
    _ids = itertools.count(last_id + 1)


@dataclass
class VirtualOrder:
    uid: str                 #instrument_uid
    ticker: str
    kind: str
    price: float = 0.0
    qty: int = 0
    direction: str = LONG    #какую позицию закрываем
    exec_type: str = MARKET
    slippage: float = 0.3    # % для лимитки

    trail_pct: float = 0.0
    extreme: float = None    #максимум (лонг) / минимум (шорт)

    column: str = COL_BUY    # для уведомлений
    above: bool = True

    oco: str = None
    status: str = "active"   # active / triggered / sending / done / cancelled / error
    id: int = 0

    _since: float = None     #с какого момента выполняется условие
    _peak: tuple = None      #кандидат в новый максимум трейлинга

    def __post_init__(self):
        if not self.id:
            self.id = next(_ids)

    def watch_price(self, quote):
        if self.kind == ALERT:
            return quote.bid if self.column == COL_BUY else quote.ask
        return quote.bid if self.direction == LONG else quote.ask

    def trail_level(self):
        if self.extreme is None:
            return None
        k = self.trail_pct / 100
        if self.direction == LONG:
            return self.extreme * (1 - k)
        return self.extreme * (1 + k)

    def condition(self, p):
        if self.kind == STOP:
            return p <= self.price if self.direction == LONG else p >= self.price
        if self.kind == TAKE:
            return p >= self.price if self.direction == LONG else p <= self.price
        if self.kind == ALERT:
            return p >= self.price if self.above else p <= self.price
        if self.kind == TRAIL:
            lvl = self.trail_level()
            if lvl is None:
                return False
            return p <= lvl if self.direction == LONG else p >= lvl
        return False

    def close_side(self):
        return "sell" if self.direction == LONG else "buy"


class OrderBookWatcher:

    def __init__(self, confirm_time=0.5):
        self.orders = []
        self.confirm_time = confirm_time

    def add(self, order):
        self.orders.append(order)
        return order

    def cancel(self, order_id):
        for o in self.orders:
            if o.id == order_id and o.status == "active":
                o.status = "cancelled"
                return True
        return False

    def active(self, uid=None):
        return [o for o in self.orders
                if o.status == "active" and (uid is None or o.uid == uid)]

    @staticmethod
    def _move_extreme(o, p, now, confirm_time):
        #новый максимум принимаем только если продержался confirm_time,
        #а то робот на миг поднимет плиты, и стоп уедет за ним
        if o.extreme is None:
            o.extreme = p
            return
        better = p > o.extreme if o.direction == LONG else p < o.extreme
        if not better:
            o._peak = None
            return
        if o._peak is None:
            value, since = p, now
        else:
            value, since = o._peak
            value = min(value, p) if o.direction == LONG else max(value, p)
        if now - since >= confirm_time:
            o.extreme = value
            o._peak = None
        else:
            o._peak = (value, since)

    def on_quote(self, uid, quote, now, confirm_time=None):
        #возвращает сработавшие заявки
        if confirm_time is None:
            confirm_time = self.confirm_time
        fired = []
        for o in self.active(uid):
            p = o.watch_price(quote)

            if o.kind == TRAIL and quote.ok and p is not None:
                self._move_extreme(o, p, now, confirm_time)

            if not quote.ok or p is None or not o.condition(p):
                o._since = None
                continue

            if o._since is None:
                o._since = now
            if now - o._since < confirm_time:
                continue

            o.status = "triggered"
            fired.append(o)

        # OCO. если обе из пары сработали разом (кривые цены),берём первую
        result = []
        for o in fired:
            if o.status != "triggered":
                continue
            result.append(o)
            if o.oco:
                for other in self.orders:
                    if other is not o and other.oco == o.oco and other.status in ("active", "triggered"):
                        other.status = "cancelled"
        return result
