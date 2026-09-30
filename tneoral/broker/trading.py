#отправка настоящих заявок

import asyncio
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .instruments import q2f

log = logging.getLogger(__name__)

RETRY_CODES = {"UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}


@dataclass
class OrderRequest:
    local_id: int        # id виртуальной заявки 0 для ручной
    uid: str
    ticker: str
    side: str
    qty: int
    market: bool
    price: float = None
    request_id: str = "" #uuid с ним биржа не исполнит одно и то же дважды
    keep: bool = False   #лимитка висит до конца дня
    manual: bool = False


@dataclass
class OrderResult:
    local_id: int
    ok: bool
    lots_requested: int = 0
    lots_executed: int = 0
    avg_price: float = None
    status: str = ""
    message: str = ""
    order_id: str = ""
    request_id: str = ""


def f2q(price):
    #через Decimal дабы избежать ошибки на округлении
    from t_tech.invest import Quotation
    d = Decimal(str(price)).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
    units = int(d)
    nano = int((d - units) * 1_000_000_000)
    return Quotation(units=units, nano=nano)


def _short_status(st):
    return st.name.replace("EXECUTION_REPORT_STATUS_", "") if st is not None else ""


async def send_order(client, account_id, req: OrderRequest, attempts=3):
    from t_tech.invest import OrderDirection, OrderType
    from t_tech.invest.exceptions import AioRequestError
    from t_tech.invest.schemas import TimeInForceType

    direction = (OrderDirection.ORDER_DIRECTION_BUY if req.side == "buy"
                 else OrderDirection.ORDER_DIRECTION_SELL)
    kwargs = dict(
        instrument_id=req.uid,
        quantity=req.qty,
        direction=direction,
        account_id=account_id,
        order_id=req.request_id,
    )
    if req.market:
        kwargs["order_type"] = OrderType.ORDER_TYPE_MARKET
    else:
        kwargs["order_type"] = OrderType.ORDER_TYPE_LIMIT
        kwargs["price"] = f2q(req.price)
        if req.keep:
            kwargs["time_in_force"] = TimeInForceType.TIME_IN_FORCE_DAY
        else:
            #после стопа остаток висеть не должен
            kwargs["time_in_force"] = TimeInForceType.TIME_IN_FORCE_FILL_AND_KILL

    resp = None
    for i in range(attempts):
        try:
            resp = await client.orders.post_order(**kwargs)
            break
        except AioRequestError as e:
            code = getattr(e.code, "name", str(e.code))
            log.warning("post_order %s попытка %d: %s %s", req.ticker, i + 1, code, e.details)
            if code not in RETRY_CODES or i == attempts - 1:
                return OrderResult(req.local_id, False, req.qty, status=code,
                                   message=_api_message(e), request_id=req.request_id)
            await asyncio.sleep(0.3)  #повтор с тем же request_id,дубля не будет

    res = OrderResult(req.local_id, True, resp.lots_requested, resp.lots_executed,
                      status=_short_status(resp.execution_report_status),
                      message=resp.message or "", order_id=resp.order_id,
                      request_id=req.request_id)

    if req.keep and not req.market:
        return res

    # ответ приходит раньше исполнения
    for _ in range(4):
        if res.status in ("FILL", "REJECTED", "CANCELLED"):
            break
        await asyncio.sleep(0.5)
        try:
            await _update_state(client, account_id, res)
        except Exception as e:
            log.warning("не получил статус заявки %s: %s", res.order_id, e)

    if res.status == "REJECTED":
        res.ok = False
    elif res.status in ("FILL", "PARTIALLYFILL") and res.avg_price is None:
        try:
            await _update_state(client, account_id, res)
        except Exception:
            pass
    return res


async def _update_state(client, account_id, res):
    from t_tech.invest.schemas import PriceType

    st = await client.orders.get_order_state(account_id=account_id, order_id=res.order_id,
                                             price_type=PriceType.PRICE_TYPE_POINT)
    res.status = _short_status(st.execution_report_status)
    res.lots_executed = st.lots_executed
    avg = q2f(st.average_position_price)
    if avg:
        res.avg_price = avg


def _api_message(e):
    details = getattr(e, "details", "") or ""
    meta = getattr(e, "metadata", None)
    msg = getattr(meta, "message", "") if meta else ""
    return (msg or details or str(e)).strip()
