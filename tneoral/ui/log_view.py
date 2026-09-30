import html
import time

from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QVBoxLayout

COLORS = {
    "fire": "#3ddc97",    #сработало
    "filter": "#f2c14e",  #защита что-то отсеяла / держит цену
    "info": "#8e9bab",
    "error": "#ff6b7a",
}


class LogView(QFrame):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.title = QLabel("  Журнал")
        self.title.setObjectName("panelTitle")
        self.title.setFixedHeight(28)
        lay.addWidget(self.title)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setObjectName("journal")
        self.text.setMaximumBlockCount(1000)
        lay.addWidget(self.text)

    def add(self, ts, ticker, kind, text):
        t = time.strftime("%H:%M:%S", time.localtime(ts))
        color = COLORS.get(kind, COLORS["info"])
        self.text.appendHtml(
            f'<span style="color:#6f7d8f">{t}</span>&nbsp;&nbsp;'
            f'<span style="color:{color}">{html.escape(ticker or "")}</span>&nbsp;&nbsp;'
            f'{html.escape(text)}'
        )
