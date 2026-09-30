#settings.json в %APPDATA%\TNeoRal

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path

from tneoral.core.guard import GuardSettings

APP_DIR = Path(os.getenv("APPDATA", Path.home())) / "TNeoRal"
FILE = APP_DIR / "settings.json"

log = logging.getLogger(__name__)


def _guard_from(d):
    #лишние ключи из старых версий просто пропускаем
    names = {f.name for f in fields(GuardSettings)}
    return GuardSettings(**{k: v for k, v in (d or {}).items() if k in names})


class Settings:
    def __init__(self):
        self.guard = GuardSettings()
        self.per_asset = {}            #ticker -> свои GuardSettings
        self.to_tray = True
        self.sound = True
        self.live = False              # боевой режим
        self.trading = False           # вкладки рыночная/лимитная
        self.confirm_trades = True

    def guard_for(self, ticker):
        return self.per_asset.get(ticker, self.guard)

    def load(self):
        if not FILE.exists():
            return self
        try:
            d = json.loads(FILE.read_text(encoding="utf-8"))
        except Exception:
            log.exception("settings.json битый, беру настройки по умолчанию")
            return self
        self.guard = _guard_from(d.get("guard"))
        self.per_asset = {t: _guard_from(g) for t, g in d.get("per_asset", {}).items()}
        self.to_tray = d.get("to_tray", True)
        self.sound = d.get("sound", True)
        self.live = d.get("live", False)
        self.trading = d.get("trading", False)
        self.confirm_trades = d.get("confirm_trades", True)
        return self

    def save(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        d = {
            "guard": asdict(self.guard),
            "per_asset": {t: asdict(g) for t, g in self.per_asset.items()},
            "to_tray": self.to_tray,
            "sound": self.sound,
            "live": self.live,
            "trading": self.trading,
            "confirm_trades": self.confirm_trades,
        }
        FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
