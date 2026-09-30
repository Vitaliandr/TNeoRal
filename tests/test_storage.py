from tneoral.core.orders import SHORT, STOP, TRAIL, VirtualOrder
from tneoral.storage import Storage


def test_orders_survive_restart(tmp_path):
    db = tmp_path / "t.db"
    s = Storage(db)
    stop = VirtualOrder(uid="u1", ticker="RDDTperpA", kind=STOP, price=150.0, qty=10, oco="ab")
    trail = VirtualOrder(uid="u1", ticker="RDDTperpA", kind=TRAIL, qty=3, direction=SHORT,
                         trail_pct=2.0, extreme=140.5)
    s.save_order(stop)
    s.save_order(trail)
    stop.status = "cancelled"
    s.save_order(stop)
    s.close()

    s2 = Storage(db)
    restored = s2.active_orders()
    assert len(restored) == 1
    t = restored[0]
    assert t.kind == TRAIL and t.direction == SHORT and t.extreme == 140.5
    #новые заявки получают номера дальше старых
    new = VirtualOrder(uid="u1", ticker="X", kind=STOP)
    assert new.id > max(stop.id, trail.id)
    s2.close()


def test_journal(tmp_path):
    s = Storage(tmp_path / "t.db")
    s.log("RDDTperpA", "fire", "стоп сработал")
    s.log("", "info", "подключено")
    rows = s.last_journal()
    assert [r[3] for r in rows] == ["стоп сработал", "подключено"]
    s.close()
