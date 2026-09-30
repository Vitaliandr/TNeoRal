from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import (
    QAbstractSpinBox, QHBoxLayout, QLabel, QMessageBox, QStyledItemDelegate, QToolButton,
    QVBoxLayout, QWidget,
)


class KeepColors(QStyledItemDelegate):
    #иначе в выделенной строке весь текст одного цвета

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        fg = index.data(Qt.ForegroundRole)
        if fg is not None:
            option.palette.setBrush(QPalette.HighlightedText, QBrush(fg))


def ask(parent, title, text, default_yes=True):
    #свои подписи: не загрузится перевод Qt, будут Yes/No
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle(title)
    box.setText(text)
    yes = box.addButton("Да", QMessageBox.YesRole)
    no = box.addButton("Нет", QMessageBox.NoRole)
    box.setDefaultButton(yes if default_yes else no)
    box.setEscapeButton(no)
    box.exec()
    return box.clickedButton() is yes


def with_steps(spin):
    #родные стрелки в стиле Win11 иногда не нажимаются
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    box = QWidget()
    box.setObjectName("stepBox")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(spin, 1)
    col = QVBoxLayout()
    col.setSpacing(2)
    for text, func in (("+", spin.stepUp), ("−", spin.stepDown)):
        b = QToolButton()
        b.setText(text)
        b.setObjectName("stepBtn")
        b.setAutoRepeat(True)
        b.setAutoRepeatDelay(350)
        b.setAutoRepeatInterval(60)
        b.clicked.connect(func)
        col.addWidget(b)
    h.addLayout(col)
    return box


def with_help(text, help_text):
    box = QWidget()
    box.setObjectName("clear")
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(6)
    h.addWidget(QLabel(text))
    q = QLabel("?")
    q.setObjectName("help")
    q.setAlignment(Qt.AlignCenter)
    q.setFixedSize(16, 16)
    #без таблицы с шириной подсказка тянется в одну строку на весь экран
    q.setToolTip(f"<table width='320'><tr><td>{help_text}</td></tr></table>")
    q.setCursor(Qt.WhatsThisCursor)
    h.addWidget(q)
    h.addStretch()
    return box
