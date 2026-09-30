# неоактивы позиции сделки. неоактивы в API,фьючерсы "Neo ..." / "...perpA"

from dataclasses import dataclass

from tneoral.core.orderbook import Level, OrderBook


def q2f(q):
    # Quotation/MoneyValue -> float
    if q is None:
        return 0.0
    return q.units + q.nano / 1_000_000_000


@dataclass
class NeoAsset:
    uid: str
    figi: str
    ticker: str
    name: str
    lot: int
    step: float
    step_amount: float   # в рублях!
    short_ok: bool
    api_ok: bool
    size: float = 1.0    # basic_asset_size

    @property
    def short_name(self):
        return self.name[4:] if self.name.lower().startswith("neo ") else self.name


def is_neo(fut):
    name = (fut.name or "").strip()
    ticker = fut.ticker or ""
    return name.lower().startswith("neo ") or ticker.endswith("perpA")


def to_asset(fut):
    return NeoAsset(
        uid=fut.uid,
        figi=fut.figi,
        ticker=fut.ticker,
        name=fut.name,
        lot=fut.lot or 1,
        step=q2f(fut.min_price_increment),
        step_amount=q2f(fut.min_price_increment_amount),
        short_ok=bool(fut.short_enabled_flag),
        api_ok=bool(fut.api_trade_available_flag),
        size=q2f(fut.basic_asset_size) or 1.0,
    )


@dataclass
class Position:
    qty: int           # шорт с минусом
    avg_price: float   #в пунктах

    @property
    def is_short(self):
        return self.qty < 0


@dataclass
class Trade:
    when: object      #datetime UTC
    ticker: str
    uid: str
    side: str
    qty: int
    price: float
    amount: float     # покупка с минусом
    currency: str


async def load_trades(client, account_id, assets, days):
    from datetime import datetime, timedelta, timezone

    from t_tech.invest.schemas import OperationState

    now = datetime.now(timezone.utc)
    resp = await client.operations.get_operations(
        account_id=account_id, from_=now - timedelta(days=days), to=now,
        state=OperationState.OPERATION_STATE_EXECUTED)
    res = []
    for op in resp.operations:
        a = assets.get(op.instrument_uid)
        if a is None:
            continue
        kind = op.operation_type.name
        #вариационная маржа и прочее нас не интересует
        if "BUY" in kind:
            side = "buy"
        elif "SELL" in kind:
            side = "sell"
        else:
            continue
        res.append(Trade(op.date, a.ticker, a.uid, side, int(op.quantity), q2f(op.price),
                         q2f(op.payment), (op.payment.currency or op.currency or "").upper()))
    res.sort(key=lambda t: t.when, reverse=True)
    return res


async def load_positions(client, account_id, uids):
    pf = await client.operations.get_portfolio(account_id=account_id)
    res = {}
    for p in pf.positions:
        if p.instrument_uid not in uids:
            continue
        qty = int(round(q2f(p.quantity_lots)))
        if qty == 0:
            continue
        #у фьючерсов средняя в пунктах лежит в _pt в обычном поле рубли
        avg = q2f(p.average_position_price_pt) or q2f(p.average_position_price)
        res[p.instrument_uid] = Position(qty, avg)
    return res


async def load_neo_assets(client):
    from t_tech.invest import InstrumentStatus

    resp = await client.instruments.futures(
        instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE)
    assets = [to_asset(f) for f in resp.instruments if is_neo(f)]
    assets.sort(key=lambda a: a.name)
    return assets


def to_book(ob, now):
    bids = [Level(q2f(o.price), int(o.quantity)) for o in ob.bids]
    asks = [Level(q2f(o.price), int(o.quantity)) for o in ob.asks]
    return OrderBook(bids, asks, now)
