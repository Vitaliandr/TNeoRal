import winsound

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon():
    #рисуем сами, чтобы не таскать файл иконки
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    shield = QPainterPath()
    shield.moveTo(32, 4)
    shield.lineTo(58, 14)
    shield.cubicTo(58, 40, 46, 54, 32, 60)
    shield.cubicTo(18, 54, 6, 40, 6, 14)
    shield.closeSubpath()
    p.fillPath(shield, QColor("#1e2a38"))
    p.setClipPath(shield)
    p.fillRect(QRectF(0, 30, 32, 34), QColor("#3ddc97"))
    p.fillRect(QRectF(32, 22, 32, 42), QColor("#ff6b7a"))
    p.setClipping(False)
    p.setPen(QColor("#e1e7ef"))
    p.drawPath(shield)
    p.drawLine(QPointF(32, 8), QPointF(32, 58))
    p.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    def __init__(self, window):
        super().__init__(make_icon(), window)
        self.window = window
        self.setToolTip("TNeoRal")

        menu = QMenu()
        show = QAction("Открыть", menu)
        show.triggered.connect(self.show_window)
        menu.addAction(show)
        menu.addSeparator()
        quit_ = QAction("Выход", menu)
        quit_.triggered.connect(window.really_quit)
        menu.addAction(quit_)
        self.setContextMenu(menu)
        self._menu = menu  # иначе меню съест сборщик мусора

        self.activated.connect(self._on_click)

    def _on_click(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self):
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def notify(self, title, text, sound=True):
        self.showMessage(title, text, QSystemTrayIcon.Information, 8000)
        if sound:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
