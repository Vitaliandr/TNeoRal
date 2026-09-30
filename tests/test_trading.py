import asyncio
from types import SimpleNamespace

import grpc
from t_tech.invest import Quotation
from t_tech.invest.exceptions import AioRequestError
from t_tech.invest.schemas import OrderExecutionReportStatus as S
from t_tech.invest.schemas import TimeInForceType

from tneoral.broker.trading import OrderRequest, f2q, send_order


def resp(status, executed=0, requested=10):
    return SimpleNamespace(order_id="ord1", execution_report_status=status,
                           lots_requested=requested, lots_executed=executed, message="")


class FakeOrders:
    def __init__(self, answers, states=()):
        self.answers = list(answers)   #что вернуть (или кинуть) на post_order
        self.states = list(states)     #что вернуть на get_order_state
        self.calls = []

    async def post_order(self, **kw):
        self.calls.append(kw)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a

    async def get_order_state(self, **kw):
        return self.states.pop(0)


def run(orders, req):
    client = SimpleNamespace(orders=orders)
    return asyncio.run(send_order(client, "acc", req))


def req(**kw):
    base = dict(local_id=7, uid="u1", ticker="RDDTperpA", side="sell", qty=10, market=True,
                request_id="11111111-1111-1111-1111-111111111111")
    base.update(kw)
    return OrderRequest(**base)


def state(status, executed, avg):
    return SimpleNamespace(execution_report_status=status, lots_executed=executed,
                           average_position_price=Quotation(units=int(avg), nano=int(round(avg % 1 * 1e9))))


def test_f2q():
    q = f2q(151.12)
    assert (q.units, q.nano) == (151, 120_000_000)


def test_market_fill():
    o = FakeOrders([resp(S.EXECUTION_REPORT_STATUS_FILL, 10)],
                   [state(S.EXECUTION_REPORT_STATUS_FILL, 10, 149.8)])
    r = run(o, req())
    assert r.ok and r.lots_executed == 10 and r.local_id == 7
    assert r.avg_price == 149.8
    assert o.calls[0]["quantity"] == 10
    assert "price" not in o.calls[0]


def test_retry_same_request_id():
    err = AioRequestError(grpc.StatusCode.UNAVAILABLE, "no connection", None)
    o = FakeOrders([err, resp(S.EXECUTION_REPORT_STATUS_FILL, 10)],
                   [state(S.EXECUTION_REPORT_STATUS_FILL, 10, 150.0)])
    r = run(o, req())
    assert r.ok
    assert len(o.calls) == 2
    # повтор с тем же id,биржа не исполнит дважды
    assert o.calls[0]["order_id"] == o.calls[1]["order_id"]


def test_rejected_by_api_no_retry():
    err = AioRequestError(grpc.StatusCode.INVALID_ARGUMENT, "not enough lots", None)
    o = FakeOrders([err])
    r = run(o, req())
    assert not r.ok
    assert len(o.calls) == 1
    assert "not enough" in r.message


def test_rejected_status():
    o = FakeOrders([resp(S.EXECUTION_REPORT_STATUS_REJECTED)])
    r = run(o, req())
    assert not r.ok and r.status == "REJECTED"


def test_new_then_filled():
    o = FakeOrders([resp(S.EXECUTION_REPORT_STATUS_NEW)],
                   [state(S.EXECUTION_REPORT_STATUS_FILL, 10, 149.5)])
    r = run(o, req())
    assert r.ok and r.status == "FILL" and r.lots_executed == 10 and r.avg_price == 149.5


def test_manual_limit_stays_in_book():
    # ручная лимитка, на весь день, статус не доспрашиваем
    o = FakeOrders([resp(S.EXECUTION_REPORT_STATUS_NEW)])
    r = run(o, req(market=False, price=150.0, keep=True, side="buy", qty=2))
    assert o.calls[0]["time_in_force"] == TimeInForceType.TIME_IN_FORCE_DAY
    assert r.ok and r.status == "NEW" and r.lots_executed == 0
    assert r.request_id == "11111111-1111-1111-1111-111111111111"


def test_limit_fill_and_kill():
    o = FakeOrders([resp(S.EXECUTION_REPORT_STATUS_PARTIALLYFILL, 6)],
                   [state(S.EXECUTION_REPORT_STATUS_CANCELLED, 6, 150.6)])
    r = run(o, req(market=False, price=150.66))
    call = o.calls[0]
    assert call["time_in_force"] == TimeInForceType.TIME_IN_FORCE_FILL_AND_KILL
    assert (call["price"].units, call["price"].nano) == (150, 660_000_000)
    # исполнилось 6 из 10, остаток снят
    assert r.lots_executed == 6 and r.status == "CANCELLED"
