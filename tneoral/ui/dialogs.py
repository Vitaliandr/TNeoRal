from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout,
)

from PySide6.QtWidgets import QWidget

from tneoral import token_store

from .widgets import with_help, with_steps


class TokenDialog(QDialog):

    def __init__(self, parent=None, error=""):
        super().__init__(parent)
        self.setWindowTitle("Подключение к Т-Инвестициям")
        self.setMinimumWidth(460)
        self.token = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        title = QLabel("Токен API")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        lay.addWidget(title)

        hint = QLabel(
            "Нужен токен с полным доступом, он выпускается в настройках "
            "Т-Инвестиций на один счёт. Токен хранится в диспетчере "
            "учётных данных Windows и никуда не отправляется.")
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        lay.addWidget(hint)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("t.xxxxxxxxxxxxxxxx")
        lay.addWidget(self.edit)

        error = error if isinstance(error, str) else ""
        self.err = QLabel(error)
        self.err.setStyleSheet("color: #ff6b7a;")
        self.err.setWordWrap(True)
        self.err.setVisible(bool(error))
        lay.addWidget(self.err)

        saved = token_store.load_token()
        self.saved_lbl = QLabel()
        self.saved_lbl.setProperty("muted", True)
        lay.addWidget(self.saved_lbl)

        row = QHBoxLayout()
        self.del_btn = QPushButton("Удалить токен")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self.on_delete)
        row.addWidget(self.del_btn)
        row.addStretch()

        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        ok = QPushButton("Подключить")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self.on_ok)
        row.addWidget(ok)
        lay.addLayout(row)

        self._update_saved(saved)

    def _update_saved(self, saved):
        if saved:
            self.saved_lbl.setText(f"Сохранён токен {token_store.mask(saved)}. "
                                   "Оставьте поле пустым, чтобы использовать его")
        else:
            self.saved_lbl.setText("Сохранённого токена нет")
        self.del_btn.setVisible(bool(saved))

    def on_delete(self):
        token_store.delete_token()
        self._update_saved(None)

    def on_ok(self):
        text = self.edit.text().strip()
        if not text:
            text = token_store.load_token()
        if not text:
            self.err.setText("Введите токен")
            self.err.setVisible(True)
            return
        # если токен плохой,окно откроется снова
        token_store.save_token(text)
        self.token = text
        self.accept()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.on_ok()
            return
        super().keyPressEvent(e)


# (поле, подпись, мин, макс, шаг, знаков)
GUARD_FIELDS = [
    ("min_plate", "Плита от, лотов", 1, 100000, 1, 0),
    ("small_step", "Шаг без ожидания, %", 0, 10, 0.1, 2),
    ("requote_wait", "Ожидание перестановки, с", 0, 10, 0.1, 1),
    ("max_spread", "Макс. спред, %", 0.05, 20, 0.1, 2),
    ("wide_warn", "Предупредить о широком спреде через, с", 1, 600, 1, 0),
    ("confirm_time", "Подтверждение, с", 0, 2, 0.1, 1),
    ("open_pause", "Пауза после открытия торгов, с", 0, 300, 1, 0),
]

HELP = {
    "only_this": "Настройки сохранятся только для этого актива. Остальные активы "
                 "продолжат работать по общим настройкам.",
    "min_plate": "Минимальный объём заявки, которую считаем плитой маркетмейкера. "
                 "Заявки меньше (1, 3, 10 лотов) не учитываются: они оголяются, когда робот "
                 "переставляет плиту, и к реальной цене отношения не имеют.",
    "small_step": "Если новая плита хуже прежней не больше чем на этот процент, цена "
                  "принимается сразу - так робот обычно и двигает цену. Если скачок больше, "
                  "программа сначала ждёт, не вернёт ли робот плиту на место "
                  "(см. «Ожидание перестановки»).",
    "requote_wait": "Сколько секунд держать прежнюю цену, если плита пропала или цена "
                    "скакнула сильнее, чем «Шаг без ожидания». Робот за это время ставит "
                    "плиту обратно - и ложного срабатывания не будет. Если не поставил - "
                    "новая цена считается настоящей.",
    "max_spread": "Если спред между плитами покупки и продажи больше этого значения, стакан "
                  "считается «грязным» и не срабатывает ничего - ни стопы, ни тейки, ни "
                  "уведомления. Так бывает, когда маркетмейкер ошибается. В обычном режиме "
                  "спред у неоактивов до 0,5%.",
    "wide_warn": "Если по активу с активными заявками спред шире допустимого держится "
                 "дольше этого времени, придёт уведомление: заявки заблокированы, проверьте "
                 "ситуацию вручную. Когда спред вернётся в норму, придёт второе сообщение.",
    "confirm_time": "Сколько секунд условие должно выполняться без перерыва, прежде чем "
                    "заявка сработает. Отсекает мгновенные скачки. Больше - надёжнее, "
                    "но реакция позже.",
    "open_pause": "Сколько секунд после открытия торгов ничего не срабатывает: в первые "
                  "секунды стакан часто кривой.",
    "sound": "Звуковой сигнал вместе со всплывающим уведомлением Windows.",
    "tray": "Крестик не закрывает приложение, а прячет его в трей, заявки продолжают "
            "проверяться. Полный выход - через меню значка в трее.",
    "confirm_trades": "Перед каждой ручной сделкой на вкладках «Рыночная» и «Лимитная» "
                      "спрашивать подтверждение. Если выключить - сделка уходит сразу по "
                      "нажатию «Купить» / «Продать», как в терминале.",
}


def check_with_help(text, key):
    box = QWidget()
    box.setObjectName("clear")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    chk = QCheckBox(text)
    h.addWidget(chk)
    h.addWidget(with_help("", HELP[key]))
    h.addStretch()
    return box, chk


class GuardDialog(QDialog):

    def __init__(self, settings, ticker=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(420)
        self.settings = settings
        self.ticker = ticker

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)

        title = QLabel("Защита от ложных срабатываний")
        title.setStyleSheet("font-size: 12pt; font-weight: 600;")
        lay.addWidget(title)

        box, self.only_this = check_with_help(
            f"Только для {ticker}" if ticker else "Только для актива", "only_this")
        self.only_this.setEnabled(bool(ticker))
        self.only_this.setChecked(bool(ticker) and ticker in settings.per_asset)
        self.only_this.toggled.connect(self._load_values)
        lay.addWidget(box)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        self.inputs = {}
        for name, cap, lo, hi, step, dec in GUARD_FIELDS:
            w = QSpinBox() if dec == 0 else QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setMinimumWidth(110)
            if dec:
                w.setDecimals(dec)
            self.inputs[name] = w
            form.addRow(with_help(cap, HELP[name]), with_steps(w))
        lay.addLayout(form)

        box, self.sound = check_with_help("Звук при срабатывании", "sound")
        self.sound.setChecked(settings.sound)
        lay.addWidget(box)
        box, self.tray = check_with_help("Крестик сворачивает в трей", "tray")
        self.tray.setChecked(settings.to_tray)
        lay.addWidget(box)
        box, self.confirm = check_with_help("Подтверждать ручные сделки", "confirm_trades")
        self.confirm.setChecked(settings.confirm_trades)
        lay.addWidget(box)

        row = QHBoxLayout()
        self.reset_btn = QPushButton("Сбросить для актива")
        self.reset_btn.clicked.connect(self._reset_asset)
        self.reset_btn.setVisible(bool(ticker) and ticker in settings.per_asset)
        row.addWidget(self.reset_btn)
        row.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("Сохранить")
        ok.setObjectName("primary")
        ok.clicked.connect(self._save)
        row.addWidget(ok)
        lay.addLayout(row)

        self._load_values()

    def _current(self):
        if self.only_this.isChecked():
            return self.settings.per_asset.get(self.ticker, self.settings.guard)
        return self.settings.guard

    def _load_values(self, *_):
        g = self._current()
        for name, w in self.inputs.items():
            w.setValue(getattr(g, name))

    def _reset_asset(self):
        self.settings.per_asset.pop(self.ticker, None)
        self.only_this.setChecked(False)
        self.reset_btn.setVisible(False)
        self._load_values()

    def _save(self):
        values = {name: w.value() for name, w in self.inputs.items()}
        if self.only_this.isChecked():
            base = self.settings.per_asset.get(self.ticker, self.settings.guard)
            self.settings.per_asset[self.ticker] = replace(base, **values)
        else:
            #общий меняем на месте на него ссылаются все активы без своих
            for k, v in values.items():
                setattr(self.settings.guard, k, v)
        self.settings.sound = self.sound.isChecked()
        self.settings.to_tray = self.tray.isChecked()
        self.settings.confirm_trades = self.confirm.isChecked()
        self.settings.save()
        self.accept()