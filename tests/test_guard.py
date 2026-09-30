from tneoral.core.guard import Guard, GuardSettings
from tneoral.core.orderbook import OrderBook, find_plate


def test_plate_skips_small_orders(rddt):
    plate = find_plate(rddt["plate_gone"].bids, 20)
    #1 1 1, 1 10, 3 1,плиты тут нет вообще
    assert plate is None

    plate = find_plate(rddt["normal"].bids, 20)
    assert plate.price == 151.38


def test_19_lots_is_not_plate():
    book = OrderBook.from_lists([(150.0, 19), (149.0, 20)], [])
    assert find_plate(book.bids, 20).price == 149.0


def test_normal_book_is_ok(rddt):
    g = Guard()
    q = g.update(rddt["normal"], now=0)
    assert q.ok
    assert q.bid == 151.38
    assert q.ask == 151.53
    assert round(q.spread, 3) == 0.099


def test_plate_gone_price_is_held(rddt):
    #робот убрал плиту, сверху осталась мелочь 149.66 x1
    g = Guard()
    g.update(rddt["normal"], now=0)

    q = g.update(rddt["plate_gone"], now=0.3)
    assert q.bid == 151.38      # держим старую цену
    assert q.bid_held
    assert q.ok

    #через 1 сек робот поставил новую плиту чуть ниже (151.12, это -0.17%) -
    # принимаем сразу это обычный шаг цены
    q = g.update(rddt["requoted"], now=1.3)
    assert q.bid == 151.12
    assert not q.bid_held
    assert q.ok


def test_big_jump_to_other_plate_waits():
    # плита пропала а ниже на 1.3% стоит чья-то крупная заявка,ждём робота
    g = Guard(GuardSettings(requote_wait=1.5, small_step=1.0))
    g.update(OrderBook.from_lists([(151.38, 130), (149.40, 50)], [(151.53, 65)]), now=0)
    gone = OrderBook.from_lists([(149.40, 50)], [(151.53, 65)])

    q = g.update(gone, now=0.2)
    assert q.bid == 151.38 and q.bid_held
    q = g.update(gone, now=1.8)
    assert q.bid == 149.40


def test_gradual_drop_no_delay():
    # робот плавно двигает плиту вниз по 0.1-0.2%,каждую цену принимаем сразу
    g = Guard()
    t = 0.0
    for price in [151.38, 151.20, 151.00, 150.80, 150.60]:
        q = g.update(OrderBook.from_lists([(price, 130)], [(price + 0.15, 65)]), now=t)
        assert q.bid == price
        assert not q.bid_held
        t += 0.2


def test_plate_not_back_after_wait(rddt):
    g = Guard(GuardSettings(requote_wait=1.5))
    g.update(rddt["normal"], now=0)
    g.update(rddt["plate_gone"], now=0.5)
    q = g.update(rddt["plate_gone"], now=2.1)
    # плиты так и нет, цены покупки нет решения не принимаем
    assert q.bid is None
    assert not q.ok


def test_real_drop_accepted_after_wait():
    #плита реально переехала сильно ниже (-1.2%) и стоит там
    g = Guard(GuardSettings(requote_wait=1.5))
    g.update(OrderBook.from_lists([(151.38, 130)], [(151.53, 65)]), now=0)

    lower = OrderBook.from_lists([(149.50, 130)], [(149.70, 65)])
    q = g.update(lower, now=0.1)
    assert q.bid == 151.38  #пока держим

    q = g.update(lower, now=1.7)
    assert q.bid == 149.50
    assert q.ok


def test_drop_under_1_percent_at_once():
    # -0.85%, меньше 1% принимаем сразу
    g = Guard()
    g.update(OrderBook.from_lists([(151.38, 130)], [(151.53, 65)]), now=0)
    q = g.update(OrderBook.from_lists([(150.10, 130)], [(150.30, 65)]), now=0.1)
    assert q.bid == 150.10
    assert not q.bid_held


def test_price_up_accepted_at_once():
    g = Guard()
    g.update(OrderBook.from_lists([(151.38, 130)], [(151.53, 65)]), now=0)
    q = g.update(OrderBook.from_lists([(152.00, 130)], [(152.15, 65)]), now=0.1)
    assert q.bid == 152.00
    assert not q.bid_held


def test_wide_spread_blocks():
    g = Guard(GuardSettings(max_spread=1.0))
    #спред ~1.3%, и держать нечего,это первый снимок
    q = g.update(OrderBook.from_lists([(150.0, 100)], [(152.0, 100)]), now=0)
    assert not q.ok
    assert "спред" in q.reason


def test_wide_spread_blocks_always():
    g = Guard(GuardSettings(max_spread=1.0))
    wide = OrderBook.from_lists([(150.0, 100)], [(152.0, 100)])

    q = g.update(wide, now=0)
    assert not q.ok
    q = g.update(wide, now=60)
    assert not q.ok           # хоть минуту держится, всё равно блок
    assert q.wide_for == 60   # а вот сколько он держится,считаем, для предупреждения

    # спред вернулся в норму,всё как обычно отсчёт сброшен
    q = g.update(OrderBook.from_lists([(150.0, 100)], [(150.3, 100)]), now=61)
    assert q.ok and q.wide_for == 0
    #аск снова прыгнул на 152, сначала 1.5 сек держим старую цену (это ok),
    #потом отсчёт начинается заново
    q = g.update(wide, now=62)
    assert q.ask_held and q.ok
    q = g.update(wide, now=63.6)
    assert not q.ok and q.wide_for == 0
    q = g.update(wide, now=70)
    assert abs(q.wide_for - 6.4) < 1e-9


def test_spread_half_percent_is_fine():
    g = Guard(GuardSettings(max_spread=1.0))
    q = g.update(OrderBook.from_lists([(100.0, 50)], [(100.5, 50)]), now=0)
    assert q.ok


def test_pause_after_open():
    g = Guard(GuardSettings(open_pause=10))
    book = OrderBook.from_lists([(100.0, 50)], [(100.1, 50)])
    g.set_trading(False, now=0)
    g.set_trading(True, now=100)

    assert not g.update(book, now=105).ok
    assert g.update(book, now=111).ok


def test_offline():
    g = Guard()
    book = OrderBook.from_lists([(100.0, 50)], [(100.1, 50)])
    g.update(book, now=0)
    g.set_online(False)
    q = g.update(book, now=1)
    assert not q.ok
    assert q.reason == "нет связи"
