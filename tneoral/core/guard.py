#защита от ложных срабатываний: цену берём по плитам робота а не по верху стакана.
#подробно как это работает, в README

from dataclasses import dataclass

from .orderbook import find_plate, spread_pct


@dataclass
class GuardSettings:
    min_plate: int = 20          #лотов, меньше,мелочь
    max_spread: float = 1.0      # %
    requote_wait: float = 1.5    # сек, робот переставляет плиту не дольше
    small_step: float = 1.0      #%, такой шаг вниз принимаем сразу
    confirm_time: float = 0.3    # сек
    open_pause: float = 10.0     # сек после открытия торгов
    wide_warn: float = 10.0      #сек широкого спреда до предупреждения


@dataclass
class Quote:
    bid: float = None       #цены по плитам, с учётом удержания
    ask: float = None
    raw_bid: float = None   # первая плита как есть
    raw_ask: float = None
    spread: float = None
    ok: bool = False
    wide_for: float = 0.0
    reason: str = ""        # почему не ok, для журнала
    bid_held: bool = False
    ask_held: bool = False


class _Side:
    def __init__(self, is_bid):
        self.is_bid = is_bid
        self.price = None
        self.held_since = None

    def worse(self, new, old):
        #для покупки хуже,ниже для продажи, выше
        if self.is_bid:
            return new < old
        return new > old

    def update(self, plate_price, now, s: GuardSettings):
        if self.price is None:
            self.price = plate_price
            self.held_since = None
            return

        if plate_price is not None and not self.worse(plate_price, self.price):
            self.price = plate_price
            self.held_since = None
            return

        # небольшой шаг, робот просто подвинул цену ждать нечего
        if plate_price is not None:
            step = abs(plate_price - self.price) / self.price * 100
            if step <= s.small_step:
                self.price = plate_price
                self.held_since = None
                return

        # плита пропала или прыгнула далеко, держим старую цену, вдруг вернёт
        if self.held_since is None:
            self.held_since = now
        if now - self.held_since >= s.requote_wait:
            self.price = plate_price
            self.held_since = None

    @property
    def holding(self):
        return self.held_since is not None


class Guard:
    # один на инструмент

    def __init__(self, settings: GuardSettings = None):
        self.s = settings or GuardSettings()
        self.bid_side = _Side(is_bid=True)
        self.ask_side = _Side(is_bid=False)

        self.trading = True
        self.trading_since = None
        self.online = True
        self.wide_since = None

    def set_trading(self, active, now):
        if active and not self.trading:
            self.trading_since = now
        self.trading = active
        if not active:
            self.reset()

    def set_online(self, online):
        self.online = online
        if not online:
            self.reset()

    def reset(self):
        self.bid_side = _Side(is_bid=True)
        self.ask_side = _Side(is_bid=False)
        self.wide_since = None

    def update(self, book, now) -> Quote:
        s = self.s
        q = Quote()

        bid_plate = find_plate(book.bids, s.min_plate)
        ask_plate = find_plate(book.asks, s.min_plate)
        q.raw_bid = bid_plate.price if bid_plate else None
        q.raw_ask = ask_plate.price if ask_plate else None

        self.bid_side.update(q.raw_bid, now, s)
        self.ask_side.update(q.raw_ask, now, s)

        q.bid = self.bid_side.price
        q.ask = self.ask_side.price
        q.bid_held = self.bid_side.holding
        q.ask_held = self.ask_side.holding
        #по реальным плитам, по удержанным он бы всегда был нормальный
        q.spread = spread_pct(q.raw_bid, q.raw_ask)

        if not self.online:
            q.reason = "нет связи"
        elif not self.trading:
            q.reason = "торги закрыты"
        elif self.trading_since is not None and now - self.trading_since < s.open_pause:
            q.reason = "пауза после открытия"
        elif q.bid is None or q.ask is None:
            q.reason = "нет плиты"
        elif q.spread is None:
            q.ok = True  # плиты сейчас нет, но цену ещё держим
        elif q.spread > s.max_spread and not (q.bid_held or q.ask_held):
            if self.wide_since is None:
                self.wide_since = now
            q.wide_for = now - self.wide_since
            q.reason = f"спред {q.spread:.2f}%"
        else:
            q.ok = True

        if q.spread is not None and q.spread <= s.max_spread:
            self.wide_since = None

        return q
