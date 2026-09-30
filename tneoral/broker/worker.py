# сетевой поток со своим asyncio. с окном, только сигналами виджеты отсюда трогать нельзя

import asyncio
import logging
import time

from PySide6.QtCore import QThread, Signal

from .instruments import load_neo_assets, load_positions, load_trades, to_book
from .trading import OrderResult, send_order

log = logging.getLogger(__name__)

DEPTH = 20  #API разрешает 1/10/20/30/40/50

NETWORK_CODES = {"UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL", "UNKNOWN"}

GOOD_STATUSES = {
    "SECURITY_TRADING_STATUS_NORMAL_TRADING",
    "SECURITY_TRADING_STATUS_DEALER_NORMAL_TRADING",
}


class BrokerWorker(QThread):
    connected = Signal(str)          #id счёта
    failed = Signal(str)
    assets_loaded = Signal(list)
    book = Signal(str, object)       # uid OrderBook
    trading = Signal(str, bool)
    online = Signal(bool)
    positions = Signal(dict)
    status = Signal(str)
    order_done = Signal(object)
    max_lots = Signal(str, dict)
    history = Signal(list)

    def __init__(self, token, parent=None):
        super().__init__(parent)
        self.token = token
        self.account_id = None
        self.assets = []
        self._stop = False
        self._loop = None
        self._task = None
        self._client = None  # клиент стрима заявки шлём через него же

    def stop(self):
        self._stop = True
        if self._loop and self._task:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self.wait(5000)

    def submit(self, req):
        # зовут из окна то есть из другого потока
        if not self._loop or self._loop.is_closed():
            self.order_done.emit(OrderResult(req.local_id, False, req.qty, status="OFFLINE",
                                             message="нет подключения", request_id=req.request_id))
            return
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._exec(req)))

    def request_history(self, days):
        if self._loop and not self._loop.is_closed() and self._client is not None:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._history(days)))

    async def _history(self, days):
        try:
            assets = {a.uid: a for a in self.assets}
            self.history.emit(await load_trades(self._client, self.account_id, assets, days))
        except Exception as e:
            log.warning("не получил историю сделок: %s", e)

    def request_max_lots(self, uid):
        if self._loop and not self._loop.is_closed() and self._client is not None:
            self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._max_lots(uid)))

    async def _max_lots(self, uid):
        from t_tech.invest.schemas import GetMaxLotsRequest

        try:
            r = await self._client.orders.get_max_lots(
                GetMaxLotsRequest(account_id=self.account_id, instrument_id=uid))
        except Exception as e:
            log.warning("не получил лимиты %s: %s", uid, e)
            return
        self.max_lots.emit(uid, {
            "buy": r.buy_limits.buy_max_lots,
            "buy_margin": r.buy_margin_limits.buy_max_lots,
            "sell": r.sell_limits.sell_max_lots,
            "sell_margin": r.sell_margin_limits.sell_max_lots,
        })

    async def _exec(self, req):
        from t_tech.invest import AsyncClient

        try:
            if self._client is not None:
                res = await send_order(self._client, self.account_id, req)
            else:
                # стрим переподключается
                async with AsyncClient(self.token) as client:
                    res = await send_order(client, self.account_id, req)
        except Exception as e:
            log.exception("заявка не отправилась")
            res = OrderResult(req.local_id, False, req.qty, status="ERROR", message=str(e),
                              request_id=req.request_id)
        self.order_done.emit(res)

        # позицию обновим сразу, не ждём опроса
        try:
            client = self._client
            if client is not None:
                uids = {a.uid for a in self.assets}
                self.positions.emit(await load_positions(client, self.account_id, uids))
        except Exception as e:
            log.warning("не обновил позиции после заявки: %s", e)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._main())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except BaseException as e:
            log.exception("worker упал")
            self.failed.emit(f"Сетевой поток остановился: {e!r}")
        finally:
            self._loop.close()

    async def _main(self):
        from t_tech.invest import AsyncClient
        from t_tech.invest import clients as sdk_clients
        from t_tech.invest.exceptions import AioRequestError

        #SDK шлёт ошибки в sentry банка и на выходе ждёт до 2 сек. настройки нет глушим так
        async def _no_error_hub(client):
            pass
        sdk_clients.async_init_error_hub = _no_error_hub

        # TODO: перечитывать параметры фьючерсов раз в час курс в форме за день устаревает
        # нет сети, не повод спрашивать токен, просто повторяем
        pause = 2
        while not self._stop:
            try:
                async with AsyncClient(self.token) as client:
                    accs = await client.users.get_accounts()
                    if not accs.accounts:
                        self.failed.emit("К токену не привязан ни один счёт")
                        return
                    #токен выпускается на один счёт
                    self.account_id = accs.accounts[0].id
                    self.connected.emit(self.account_id)

                    self.assets = await load_neo_assets(client)
                    self.assets_loaded.emit(self.assets)
                break
            except AioRequestError as e:
                code = getattr(e.code, "name", "")
                if code not in NETWORK_CODES:
                    self.failed.emit(_nice_error(e))
                    return
                log.warning("нет связи с API при подключении: %s", e.details)
                self.status.emit(f"Нет связи с сервером, повтор через {pause} с")
                await asyncio.sleep(pause)
                pause = min(pause * 2, 30)

        if not self.assets:
            self.failed.emit("Неоактивы не найдены")
            return

        pause = 1
        while not self._stop:
            try:
                async with AsyncClient(self.token) as client:
                    self._client = client
                    try:
                        await self._load_statuses(client)
                        await self._stream(client)
                    finally:
                        self._client = None
                pause = 1
            except AioRequestError as e:
                log.warning("стрим оборвался: %s", e)
            except asyncio.CancelledError:
                if self._stop:
                    raise
                #grpc так сообщает об отмене вызова, это не Exception,поток бы умер
                log.warning("стрим отменён")
            except Exception:
                log.exception("стрим оборвался")
            self.online.emit(False)
            if self._stop:
                break
            await asyncio.sleep(pause)
            pause = min(pause * 2, 30)

    async def _load_statuses(self, client):
        uids = [a.uid for a in self.assets]
        resp = await client.market_data.get_trading_statuses(instrument_ids=uids)
        for st in resp.trading_statuses:
            self.trading.emit(st.instrument_uid, st.trading_status.name in GOOD_STATUSES)

    async def _requests(self):
        from t_tech.invest import (
            InfoInstrument, MarketDataRequest, OrderBookInstrument,
            SubscribeInfoRequest, SubscribeOrderBookRequest, SubscriptionAction,
        )
        # из корня пакета OrderBookType почему-то не экспортируется
        from t_tech.invest.schemas import OrderBookType

        sub = SubscriptionAction.SUBSCRIPTION_ACTION_SUBSCRIBE
        yield MarketDataRequest(
            subscribe_order_book_request=SubscribeOrderBookRequest(
                subscription_action=sub,
                instruments=[
                    OrderBookInstrument(instrument_id=a.uid, depth=DEPTH,
                                        order_book_type=OrderBookType.ORDERBOOK_TYPE_ALL)
                    for a in self.assets
                ],
            )
        )
        yield MarketDataRequest(
            subscribe_info_request=SubscribeInfoRequest(
                subscription_action=sub,
                instruments=[InfoInstrument(instrument_id=a.uid) for a in self.assets],
            )
        )
        # генератор живёт вместе со стримом иначе сервер его закроет
        while not self._stop:
            await asyncio.sleep(0.5)

    async def _first_books(self, client):
        # стрим шлёт только изменения, по тихим активам стакан можно ждать долго
        for a in self.assets:
            try:
                ob = await client.market_data.get_order_book(instrument_id=a.uid, depth=DEPTH)
                self.book.emit(a.uid, to_book(ob, time.monotonic()))
            except Exception as e:
                log.warning("не получил стакан %s: %s", a.ticker, e)

    async def _positions_loop(self, client):
        uids = {a.uid for a in self.assets}
        while not self._stop:
            try:
                self.positions.emit(await load_positions(client, self.account_id, uids))
            except Exception as e:
                log.warning("не получил портфель: %s", e)
            await asyncio.sleep(5)

    async def _stream(self, client):
        loader = None
        pos_task = asyncio.create_task(self._positions_loop(client))
        try:
            async for resp in client.market_data_stream.market_data_stream(self._requests()):
                if self._stop:
                    break
                if loader is None:
                    self.online.emit(True)
                    loader = asyncio.create_task(self._first_books(client))
                self._handle(resp)
        finally:
            pos_task.cancel()
            if loader and not loader.done():
                loader.cancel()

    def _handle(self, resp):
        if resp.orderbook:
            ob = resp.orderbook
            self.book.emit(ob.instrument_uid, to_book(ob, time.monotonic()))
        elif resp.trading_status:
            st = resp.trading_status
            self.trading.emit(st.instrument_uid, st.trading_status.name in GOOD_STATUSES)
        elif resp.subscribe_order_book_response:
            bad = [s for s in resp.subscribe_order_book_response.order_book_subscriptions
                   if s.subscription_status.name != "SUBSCRIPTION_STATUS_SUCCESS"]
            if bad:
                log.warning("не подписались на %d стаканов: %s", len(bad),
                            bad[0].subscription_status.name)


def _nice_error(e):
    code = getattr(e, "code", None)
    name = getattr(code, "name", str(code))
    if name == "UNAUTHENTICATED":
        return "Токен не подходит. Проверьте, что он скопирован полностью"
    if name == "PERMISSION_DENIED":
        return "У токена нет доступа. Нужен токен с полным доступом"
    if name == "UNAVAILABLE":
        return "Сервер API недоступен. Проверьте интернет и VPN"
    details = getattr(e, "details", "") or ""
    return f"Ошибка API: {name} {details}".strip()
