#sqlite: заявки и журнал. заявка лежит одним json поля ещё меняются

import json
import sqlite3
import time
from dataclasses import asdict, fields
from pathlib import Path

from tneoral.core.orders import VirtualOrder, continue_ids_from
from tneoral.settings import APP_DIR

DB_FILE = APP_DIR / "tneoral.db"

_order_fields = {f.name for f in fields(VirtualOrder)}


class Storage:
    def __init__(self, path=DB_FILE):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""
            create table if not exists orders (
                id integer primary key,
                status text,
                data text
            )""")
        self.db.execute("""
            create table if not exists journal (
                ts real,
                ticker text,
                kind text,
                text text
            )""")
        self.db.commit()

    def save_order(self, o):
        d = asdict(o)
        d.pop("_since", None)
        d.pop("_peak", None)
        self.db.execute("insert or replace into orders (id, status, data) values (?, ?, ?)",
                        (o.id, o.status, json.dumps(d, ensure_ascii=False)))
        self.db.commit()

    def active_orders(self):
        rows = self.db.execute("select data from orders where status = 'active'").fetchall()
        res = []
        for (data,) in rows:
            d = json.loads(data)
            res.append(VirtualOrder(**{k: v for k, v in d.items() if k in _order_fields}))
        last = self.db.execute("select max(id) from orders").fetchone()[0] or 0
        continue_ids_from(last)
        return res

    def stuck_orders(self):
        # висели в отправке, когда приложение закрылось
        rows = self.db.execute("select data from orders where status = 'sending'").fetchall()
        return [VirtualOrder(**{k: v for k, v in json.loads(d).items() if k in _order_fields})
                for (d,) in rows]

    def log(self, ticker, kind, text):
        ts = time.time()
        self.db.execute("insert into journal values (?, ?, ?, ?)", (ts, ticker, kind, text))
        self.db.commit()
        return ts

    def last_journal(self, n=200):
        rows = self.db.execute(
            "select ts, ticker, kind, text from journal order by ts desc limit ?", (n,)).fetchall()
        return list(reversed(rows))

    def close(self):
        self.db.close()
