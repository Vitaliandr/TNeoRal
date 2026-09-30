#стакан и расчёты по нему, без сети и интерфейса

from dataclasses import dataclass, field


@dataclass
class Level:
    price: float
    qty: int  #лоты


@dataclass
class OrderBook:
    #bids, "Покупка" (слева) от большей цены к меньшей
    #asks,"Продажа" (справа) от меньшей к большей
    bids: list = field(default_factory=list)
    asks: list = field(default_factory=list)
    ts: float = 0.0  # time.monotonic()

    @classmethod
    def from_lists(cls, bids, asks, ts=0.0):
        b = [Level(float(p), int(q)) for p, q in bids]
        a = [Level(float(p), int(q)) for p, q in asks]
        # API отдаёт уже отсортированным но на всякий случай
        b.sort(key=lambda x: x.price, reverse=True)
        a.sort(key=lambda x: x.price)
        return cls(b, a, ts)

    def best_bid(self):
        return self.bids[0] if self.bids else None

    def best_ask(self):
        return self.asks[0] if self.asks else None


def find_plate(levels, min_lots):
    # плита = первый уровень с объёмом от min_lots мелочь сверху пропускаем
    for lvl in levels:
        if lvl.qty >= min_lots:
            return lvl
    return None


def spread_pct(bid, ask):
    if not bid or not ask:
        return None
    mid = (bid + ask) / 2
    return (ask - bid) / mid * 100


def fill_price(levels, qty):
    #(средняя цена, сколько набрали) если съесть qty лотов прямо сейчас
    left = qty
    total = 0.0
    got = 0
    for lvl in levels:
        if left <= 0:
            break
        take = min(left, lvl.qty)
        total += take * lvl.price
        got += take
        left -= take

    if got == 0:
        return None, 0
    return total / got, got


def fits_in_plate(levels, qty, min_lots):
    plate = find_plate(levels, min_lots)
    if plate is None:
        return False
    # мелочь перед плитой не считаем там копейки
    return qty <= plate.qty
