from tneoral.core.guard import Guard, GuardSettings, Quote
from tneoral.core.orderbook import OrderBook
from tneoral.core.orders import (
    ALERT, COL_SELL, LONG, SHORT, STOP, TAKE, TRAIL,
    OrderBookWatcher, VirtualOrder,
)


def q(bid, ask, ok=True):
    return Quote(bid=bid, ask=ask, ok=ok)


def make(kind, price=0.0, direction=LONG, **kw):
    return VirtualOrder(uid="rddt", ticker="RDDTperpA", kind=kind, price=price,
                        qty=10, direction=direction, **kw)


def test_long_stop_by_buy_column():
    w = OrderBookWatcher(confirm_time=0)
    o = w.add(make(STOP, 150.0))
    #аск упал ниже стопа, но лонг смотрим по колонке "Покупка",не срабатывает
    assert w.on_quote("rddt", q(150.5, 149.0), now=0) == []
    assert w.on_quote("rddt", q(149.9, 150.1), now=1) == [o]
    assert o.close_side() == "sell"


def test_short_stop_by_sell_column():
    w = OrderBookWatcher(confirm_time=0)
    o = w.add(make(STOP, 155.0, direction=SHORT))
    assert w.on_quote("rddt", q(155.5, 154.9), now=0) == []
    assert w.on_quote("rddt", q(154.9, 155.0), now=1) == [o]
    assert o.close_side() == "buy"


def test_take_long_and_short():
    w = OrderBookWatcher(confirm_time=0)
    tl = w.add(make(TAKE, 160.0))
    ts = w.add(make(TAKE, 140.0, direction=SHORT))
    assert w.on_quote("rddt", q(160.0, 160.2), now=0) == [tl]
    assert w.on_quote("rddt", q(139.8, 140.0), now=1) == [ts]


def test_confirm_time():
    w = OrderBookWatcher(confirm_time=0.5)
    o = w.add(make(STOP, 150.0))
    assert w.on_quote("rddt", q(149.0, 149.2), now=0) == []
    assert w.on_quote("rddt", q(149.0, 149.2), now=0.3) == []
    #цена вернулась, отсчёт сбрасывается
    assert w.on_quote("rddt", q(151.0, 151.2), now=0.4) == []
    assert w.on_quote("rddt", q(149.0, 149.2), now=0.6) == []
    assert w.on_quote("rddt", q(149.0, 149.2), now=1.1) == [o]


def test_bad_quote_does_not_fire():
    w = OrderBookWatcher(confirm_time=0)
    w.add(make(STOP, 150.0))
    assert w.on_quote("rddt", q(140.0, 152.0, ok=False), now=0) == []


def test_mm_left_one_side_nothing_fires():
    #робот надолго ушёл с покупки спред по плитам 4.4%. это его сбой, а не рынок -
    # ничего не должно сработать сколько бы это ни длилось
    bids = [(197.03, 2), (197.02, 1), (196.85, 2), (196.82, 16), (196.81, 6), (193.40, 3),
            (192.57, 2), (192.00, 60), (190.05, 11), (190.03, 8), (183.46, 1), (181.00, 1)]
    asks = [(200.64, 7), (200.68, 70), (200.78, 70), (201.97, 52), (204.80, 2), (205.00, 1),
            (207.00, 17)]
    before = OrderBook.from_lists([(200.50, 70)] + bids, asks)
    broken = OrderBook.from_lists(bids, asks)

    g = Guard()
    w = OrderBookWatcher()
    orders = [w.add(make(STOP, p)) for p in (199.0, 195.0, 193.0)]
    orders.append(w.add(make(ALERT, 198.0, above=False)))
    w.on_quote("rddt", g.update(before, 0), 0, g.s.confirm_time)

    t = 0.1
    while t < 90:
        assert w.on_quote("rddt", g.update(broken, t), t, g.s.confirm_time) == []
        t += 0.1
    assert all(o.status == "active" for o in orders)


def test_oco():
    w = OrderBookWatcher(confirm_time=0)
    sl = w.add(make(STOP, 145.0, oco="pair1"))
    tp = w.add(make(TAKE, 160.0, oco="pair1"))
    assert w.on_quote("rddt", q(160.5, 160.7), now=0) == [tp]
    assert sl.status == "cancelled"
    # стоп уже снят падение его не трогает
    assert w.on_quote("rddt", q(140.0, 140.2), now=1) == []


def test_trailing_spike_does_not_move_extreme():
    #робот на миг поставил цену выше и сразу вернул, максимум не трогаем
    w = OrderBookWatcher(confirm_time=0.3)
    o = w.add(make(TRAIL, trail_pct=2.0))
    w.on_quote("rddt", q(100.0, 100.1), now=0)
    w.on_quote("rddt", q(105.0, 105.1), now=0.1)   # скачок
    w.on_quote("rddt", q(100.0, 100.1), now=0.2)   # вернулся
    w.on_quote("rddt", q(100.0, 100.1), now=1.0)
    assert o.extreme == 100.0
    # а если рост держится,принимаем, причём по самой низкой цене за время ожидания
    w.on_quote("rddt", q(104.0, 104.1), now=2.0)
    w.on_quote("rddt", q(103.5, 103.6), now=2.2)
    w.on_quote("rddt", q(104.2, 104.3), now=2.4)
    assert o.extreme == 103.5


def test_trailing_with_guard_full_scenario():
    #всё вместе через настоящую защиту: плавный рост, перестановка плиты, откат
    g = Guard()
    w = OrderBookWatcher(confirm_time=g.s.confirm_time)
    o = w.add(make(TRAIL, trail_pct=2.0))

    def book(bid):
        return OrderBook.from_lists([(bid, 130), (bid - 1.6, 1)], [(bid + 0.15, 65)])

    t = 0.0
    for bid in [100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0]:
        for _ in range(5):  # каждая цена держится 0.5 сек
            assert w.on_quote("rddt", g.update(book(bid), t), t, g.s.confirm_time) == []
            t += 0.1
    assert o.extreme == 103.0  # 103 * 0.98 = 100.94

    #робот убрал плиту, сверху мелочь по 101.4,это не падение, стоп не должен сработать
    gone = OrderBook.from_lists([(101.4, 1)], [(103.15, 65)])
    for _ in range(10):
        assert w.on_quote("rddt", g.update(gone, t), t, g.s.confirm_time) == []
        t += 0.1
    assert o.status == "active"

    # реальный откат шагами вниз,срабатывает на уровне 100.94
    fired_at = None
    for bid in [102.5, 102.0, 101.5, 101.0, 100.9, 100.9, 100.9, 100.9, 100.9]:
        if w.on_quote("rddt", g.update(book(bid), t), t, g.s.confirm_time):
            fired_at = bid
            break
        t += 0.2
    assert fired_at == 100.9
    assert o.extreme == 103.0


def test_trailing_long():
    w = OrderBookWatcher(confirm_time=0)
    o = w.add(make(TRAIL, trail_pct=2.0))
    w.on_quote("rddt", q(150.0, 150.2), now=0)
    w.on_quote("rddt", q(155.0, 155.2), now=1)
    assert o.extreme == 155.0
    # 155 * 0.98 = 151.9
    assert w.on_quote("rddt", q(152.0, 152.2), now=2) == []
    assert w.on_quote("rddt", q(151.8, 152.0), now=3) == [o]


def test_trailing_short():
    w = OrderBookWatcher(confirm_time=0)
    o = w.add(make(TRAIL, direction=SHORT, trail_pct=2.0))
    w.on_quote("rddt", q(99.8, 100.0), now=0)
    w.on_quote("rddt", q(94.8, 95.0), now=1)
    assert o.extreme == 95.0
    assert w.on_quote("rddt", q(96.7, 96.8), now=2) == []
    assert w.on_quote("rddt", q(96.9, 97.0), now=3) == [o]  # 95 * 1.02 = 96.9


def test_trailing_ignores_bad_quote():
    w = OrderBookWatcher(confirm_time=0)
    o = w.add(make(TRAIL, trail_pct=2.0))
    w.on_quote("rddt", q(150.0, 150.2), now=0)
    w.on_quote("rddt", q(170.0, 170.2, ok=False), now=1)
    assert o.extreme == 150.0


def test_alert_sell_column():
    w = OrderBookWatcher(confirm_time=0)
    a = w.add(make(ALERT, 155.0, column=COL_SELL, above=True))
    assert w.on_quote("rddt", q(155.1, 154.9), now=0) == []
    assert w.on_quote("rddt", q(154.9, 155.0), now=1) == [a]


def test_reaction_under_one_second():
    # робот ведёт плиту вниз шагами по 0.1%, стоп на 150.
    #с момента когда плита пересекла стоп до срабатывания должно пройти < 1 сек
    g = Guard()
    w = OrderBookWatcher(confirm_time=g.s.confirm_time)
    stop = w.add(make(STOP, 150.0))

    t = 0.0
    price = 150.60
    crossed_at = None
    fired_at = None
    while t < 10 and fired_at is None:
        book = OrderBook.from_lists([(price, 130)], [(price + 0.15, 65)])
        quote = g.update(book, now=t)
        if crossed_at is None and price <= 150.0:
            crossed_at = t
        if w.on_quote("rddt", quote, now=t):
            fired_at = t
        price = round(price - 0.15, 2)
        t += 0.1  #стакан обновляется примерно так часто

    assert stop.status == "triggered"
    assert fired_at - crossed_at < 1.0


def test_screenshot_case_stop_not_fired(rddt):
    # всё вместе: стоп лонга на 150 робот убирает плиту 151.38,
    # сверху остаётся 149.66 x1, стоп НЕ должен сработать
    g = Guard(GuardSettings(requote_wait=1.5))
    w = OrderBookWatcher(confirm_time=0.5)
    stop = w.add(make(STOP, 150.0))

    t = 0.0
    for name in ["normal", "plate_gone", "plate_gone", "plate_gone", "requoted", "requoted"]:
        quote = g.update(rddt[name], now=t)
        assert w.on_quote("rddt", quote, now=t) == []
        t += 0.4

    assert stop.status == "active"
