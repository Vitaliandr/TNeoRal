import pytest

from tneoral.core import calc
from tneoral.core.orderbook import OrderBook, fill_price, fits_in_plate


def test_order_value():
    #акция: 1 пт = 1$
    assert calc.order_value(145.0, 10) == pytest.approx(1450.0)
    #SOL: базовый актив 0.1, контракт по 121.9 стоит 12.19$
    assert calc.order_value(121.9, 1, size=0.1) == pytest.approx(12.19)


def test_profit_long_and_short():
    usd, pct = calc.close_profit(146.20, 145.0, 10)
    assert usd == pytest.approx(-12.0)
    assert pct == pytest.approx(-0.8208, abs=1e-3)

    usd, pct = calc.close_profit(146.20, 145.0, 10, short=True)
    assert usd == pytest.approx(12.0)


def test_profit_crypto():
    # BTC: размер 0.0001 цена выросла на 1000 пт -> 0.1$ на контракт
    usd, _ = calc.close_profit(60000, 61000, 5, size=0.0001)
    assert usd == pytest.approx(0.5)


def test_close_now_long_uses_buy_side(rddt):
    #лонг 10 по 146.20, закрываем продажей в левую сторону: плита 151.12 x65
    book = rddt["requoted"]
    exit_price, got, usd, pct = calc.close_now(10, 146.20, book)
    assert exit_price == 151.12 and got == 10
    assert usd == pytest.approx((151.12 - 146.20) * 10)
    assert pct == pytest.approx((151.12 - 146.20) / 146.20 * 100)


def test_close_now_short_uses_sell_side(rddt):
    #шорт 3 по 155 закрываем покупкой из правой стороны: 151.27
    exit_price, got, usd, _ = calc.close_now(-3, 155.0, rddt["requoted"])
    assert exit_price == 151.27 and got == 3
    assert usd == pytest.approx((155.0 - 151.27) * 3)


def test_close_now_takes_depth():
    # сверху 2 лота, у нас 10, остальные 8 по следующей цене
    book = OrderBook.from_lists([(197.00, 2), (196.80, 16)], [(200.0, 70)])
    exit_price, got, usd, _ = calc.close_now(10, 190.0, book)
    assert exit_price == pytest.approx((197.00 * 2 + 196.80 * 8) / 10)
    assert usd == pytest.approx((exit_price - 190.0) * 10)


def test_close_now_crypto_size():
    book = OrderBook.from_lists([(122.0, 2000)], [(122.1, 2000)])
    _, _, usd, _ = calc.close_now(5, 120.0, book, size=0.1)
    assert usd == pytest.approx(2.0 * 5 * 0.1)


def test_close_now_empty_side():
    assert calc.close_now(5, 100.0, OrderBook.from_lists([], [(101, 10)])) is None


def _t(side, qty, price):
    from types import SimpleNamespace
    return SimpleNamespace(side=side, qty=qty, price=price)


def test_trade_results_mixed():
    trades = [
        _t("sell", 1, 42.50),  # шорт
        _t("buy", 1, 42.50),   #закрыл в ноль
        _t("sell", 1, 42.30),  # шорт
        _t("buy", 1, 42.45),   # закрыл: -0.15
        _t("buy", 1, 42.40),   #лонг
        _t("sell", 1, 42.38),  # закрыл: -0.02
        _t("buy", 1, 42.35),
        _t("buy", 4, 42.60),
    ]
    r = calc.trade_results(trades)
    assert r[0] is None and r[2] is None and r[4] is None and r[6] is None and r[7] is None
    assert r[1][0] == pytest.approx(0.0)
    assert r[3][0] == pytest.approx(-0.15) and r[3][1] == pytest.approx(-0.3546, abs=1e-3)
    assert r[5][0] == pytest.approx(-0.02) and r[5][1] == pytest.approx(-0.0472, abs=1e-3)


def test_trade_results_average_and_partial():
    # купил 1 по 100 и 1 по 110,средняя 105 продал 1 по 120: +15
    r = calc.trade_results([_t("buy", 1, 100), _t("buy", 1, 110), _t("sell", 1, 120)])
    assert r[2][0] == pytest.approx(15.0)


def test_trade_results_flip():
    # лонг 1 по 100 продал 3 по 90: закрыл лонг с -10, открыл шорт 2 по 90 откупил по 80: +20
    r = calc.trade_results([_t("buy", 1, 100), _t("sell", 3, 90), _t("buy", 2, 80)])
    assert r[1][0] == pytest.approx(-10.0)
    assert r[2][0] == pytest.approx(20.0)


def test_trade_results_unknown_start():
    # до периода уже была позиция 2 средняя неизвестна,результат не выдумываем
    r = calc.trade_results([_t("sell", 2, 100), _t("buy", 1, 90), _t("sell", 1, 95)],
                           start_qty=2)
    assert r[0] is None
    assert r[2][0] == pytest.approx(5.0)  # после обнуления всё известно


def test_trade_results_crypto_size():
    r = calc.trade_results([_t("buy", 5, 120), _t("sell", 5, 122)], size=0.1)
    assert r[1][0] == pytest.approx(1.0)


def test_round_to_step():
    assert calc.round_to_step(151.1299999, 0.01) == 151.12
    assert calc.round_to_step(151.121, 0.01, up=True) == 151.13
    assert calc.round_to_step(151.12, 0.01, up=True) == 151.12


def test_limit_price():
    # продаём с проскальзыванием 0.3% от 151.12
    assert calc.limit_price("sell", 151.12, 0.3, 0.01) == 150.66
    assert calc.limit_price("buy", 151.27, 0.3, 0.01) == 151.73


def test_fill_price(rddt):
    book = rddt["normal"]
    avg, got = fill_price(book.bids, 10)
    assert avg == 151.38 and got == 10

    # 130 из плиты + 1 лот по 149.66
    avg, got = fill_price(book.bids, 131)
    assert got == 131
    assert avg == pytest.approx((151.38 * 130 + 149.66) / 131)


def test_fill_not_enough():
    book = OrderBook.from_lists([(100, 5)], [])
    avg, got = fill_price(book.bids, 10)
    assert got == 5


def test_fits_in_plate(rddt):
    assert fits_in_plate(rddt["normal"].asks, 65, 15)
    assert not fits_in_plate(rddt["normal"].asks, 66, 15)
