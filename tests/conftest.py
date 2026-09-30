import json
import sys
from pathlib import Path

import pytest

#чтобы pytest видел пакет tneoral без установки
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tneoral.core.orderbook import OrderBook  # noqa: E402

SNAP_DIR = Path(__file__).parent / "snapshots"


def load_books(name):
    data = json.loads((SNAP_DIR / name).read_text(encoding="utf-8"))
    books = {}
    for key, val in data.items():
        if key == "comment":
            continue
        books[key] = OrderBook.from_lists(val["bids"], val["asks"])
    return books


@pytest.fixture
def rddt():
    return load_books("rddt_plate_gone.json")
