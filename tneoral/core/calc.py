# деньги: стоимость, доход, цена лимитки.
#цена неоактива в пунктах, 1 пт = 1$ * basic_asset_size (у акций 1, SOL 0.1, BTC 0.0001).
#min_price_increment_amount из API в рублях,для долларов не годится.
#комиссии нет, она уже в цене.

import math


def order_value(price, qty, size=1.0, lot=1):
    return price * size * qty * lot


def close_profit(avg_price, price, qty, size=1.0, lot=1, short=False):
    # ($, %)
    diff = price - avg_price
    if short:
        diff = -diff
    usd = diff * size * qty * lot
    pct = diff / avg_price * 100 if avg_price else 0.0
    return usd, pct


def close_now(position_qty, avg_price, book, size=1.0, lot=1):
    #если закрыть позицию прямо сейчас: (цена выхода, сколько нашлось, $, %) или None.
    # по всему объёму в первой строке часто всего 1-2 лота
    from .orderbook import fill_price

    short = position_qty < 0
    qty = abs(position_qty)
    levels = book.asks if short else book.bids
    exit_price, got = fill_price(levels, qty)
    if exit_price is None:
        return None
    usd, pct = close_profit(avg_price, exit_price, qty, size, lot, short=short)
    return exit_price, got, usd, pct


def trade_results(trades, size=1.0, start_qty=0):
    # результат по средней цене позиции как считает брокер. trades от старых к новым.
    # start_qty != 0, средней до периода не знаем, до обнуления позиции отдаём None
    pos = start_qty
    avg = None if start_qty else 0.0
    out = []
    for t in trades:
        signed = t.qty if t.side == "buy" else -t.qty
        res = None
        if pos != 0 and (pos > 0) != (signed > 0):
            closed = min(abs(signed), abs(pos))
            if avg is not None:
                diff = (t.price - avg) if pos > 0 else (avg - t.price)
                usd = diff * closed * size
                pct = diff / avg * 100 if avg else 0.0
                res = (usd, pct)
            pos += closed if pos < 0 else -closed
            left = abs(signed) - closed
            if pos == 0:
                avg = 0.0
            if left:
                # переворот,остаток открывает позицию в другую сторону
                pos = left if signed > 0 else -left
                avg = t.price
        else:
            if avg is not None:
                total = abs(pos) + abs(signed)
                avg = (avg * abs(pos) + t.price * abs(signed)) / total
            pos += signed
        out.append(res)
    return out


def round_to_step(price, step, up=False):
    # на продажу вниз на покупку вверх, поэтому не round()
    if not step:
        return price
    n = price / step
    n = math.ceil(n - 1e-9) if up else math.floor(n + 1e-9)  # 151.1299999
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 0
    return round(n * step, decimals + 2)


def limit_price(side, plate_price, slippage, step):
    # чуть хуже плиты, чтобы точно исполнилось но не дальше slippage %
    k = slippage / 100
    if side == "sell":
        return round_to_step(plate_price * (1 - k), step, up=False)
    return round_to_step(plate_price * (1 + k), step, up=True)
