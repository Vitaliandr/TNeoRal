#стакан рисуем через QPainter таблицей медленно

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

BG = QColor("#1e2a38")
LINE = QColor("#26333f")
TEXT = QColor("#e1e7ef")
MUTED = QColor("#6f7d8f")
GREEN = QColor("#3ddc97")
RED = QColor("#ff6b7a")
GREEN_BAR = QColor("#1b5a44")
RED_BAR = QColor("#5a2d3a")
GREEN_AREA = QColor(27, 77, 62)
RED_AREA = QColor(58, 42, 56)
HOLD = QColor("#f2c14e")


def fmt(x, decimals=2):
    if x is None:
        return "—"
    return f"{x:,.{decimals}f}".replace(",", " ").replace(".", ",")


class OrderBookView(QWidget):
    ROW_H = 26
    CHART_H = 110
    HEAD_H = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.book = None
        self.quote = None
        self.min_plate = 20
        self.decimals = 2
        self.setMinimumWidth(300)
        self.setMinimumHeight(self.CHART_H + self.HEAD_H + self.ROW_H * 8)

    def set_data(self, book, quote, min_plate, decimals=2):
        self.book = book
        self.quote = quote
        self.min_plate = min_plate
        self.decimals = decimals
        self.update()

    def clear(self):
        self.book = None
        self.quote = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)

        if not self.book:
            p.setPen(MUTED)
            p.drawText(self.rect(), Qt.AlignCenter, "Выберите неоактив слева")
            return

        w = self.width()
        self._draw_chart(p, QRectF(0, 0, w, self.CHART_H))
        self._draw_head(p, QRectF(0, self.CHART_H, w, self.HEAD_H))
        self._draw_rows(p, self.CHART_H + self.HEAD_H)

    def _draw_chart(self, p, r):
        bids, asks = self.book.bids, self.book.asks
        if not bids and not asks:
            return
        lo = bids[-1].price if bids else asks[0].price
        hi = asks[-1].price if asks else bids[0].price
        if hi <= lo:
            hi = lo + 1

        total = max(sum(l.qty for l in bids), sum(l.qty for l in asks), 1)
        top = r.top() + 22
        h = r.bottom() - top

        def x_of(price):
            return r.left() + (price - lo) / (hi - lo) * r.width()

        def y_of(vol):
            return r.bottom() - vol / total * h

        for levels, area, line in ((bids, GREEN_AREA, GREEN), (asks, RED_AREA, RED)):
            if not levels:
                continue
            path = QPainterPath(QPointF(x_of(levels[0].price), r.bottom()))
            cum = 0
            for lvl in levels:
                x = x_of(lvl.price)
                path.lineTo(x, y_of(cum))
                cum += lvl.qty
                path.lineTo(x, y_of(cum))
            edge = r.left() if levels is bids else r.right()
            path.lineTo(edge, y_of(cum))

            fill = QPainterPath(path)
            fill.lineTo(edge, r.bottom())
            fill.closeSubpath()
            p.fillPath(fill, area)
            p.setPen(QPen(line, 2))
            p.drawPath(path)

        p.setPen(MUTED)
        p.drawText(QRectF(r.left() + 8, r.top() + 2, 100, 18), Qt.AlignLeft,
                   str(sum(l.qty for l in bids)))
        p.drawText(QRectF(r.right() - 108, r.top() + 2, 100, 18), Qt.AlignRight,
                   str(sum(l.qty for l in asks)))
        q = self.quote
        if q and q.bid and q.ask:
            p.setPen(TEXT)
            p.drawText(QRectF(r.left(), r.top() + 2, r.width(), 18), Qt.AlignHCenter,
                       f"{fmt((q.bid + q.ask) / 2, self.decimals)} $")

    def _draw_head(self, p, r):
        p.setPen(LINE)
        p.drawLine(r.bottomLeft(), r.bottomRight())

        f = p.font()
        bold = QFont(f)
        bold.setBold(True)
        p.setFont(bold)
        p.setPen(TEXT)
        p.drawText(r.adjusted(8, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "Покупка, $")
        p.drawText(r.adjusted(0, 0, -8, 0), Qt.AlignVCenter | Qt.AlignRight, "Продажа, $")
        p.setFont(f)

        q = self.quote
        if q and q.raw_bid and q.raw_ask:
            diff = q.raw_ask - q.raw_bid
            txt = f"{fmt(diff, self.decimals)} ({fmt(q.spread, 3)}%)"
            p.setPen(MUTED if q.ok else HOLD)
            p.drawText(r, Qt.AlignCenter, txt)

    def _draw_rows(self, p, y0):
        w = self.width()
        half = w / 2
        rows = max(len(self.book.bids), len(self.book.asks))
        rows = min(rows, int((self.height() - y0) / self.ROW_H) + 1)

        vols = [l.qty for l in self.book.bids[:rows]] + [l.qty for l in self.book.asks[:rows]]
        vmax = max(vols) if vols else 1

        for i in range(rows):
            y = y0 + i * self.ROW_H
            p.setPen(LINE)
            p.drawLine(QPointF(0, y + self.ROW_H), QPointF(w, y + self.ROW_H))

            if i < len(self.book.bids):
                lvl = self.book.bids[i]
                bw = lvl.qty / vmax * half
                p.fillRect(QRectF(half - bw, y, bw, self.ROW_H), GREEN_BAR)
                p.setPen(TEXT if lvl.qty >= self.min_plate else MUTED)
                cell = QRectF(8, y, half - 16, self.ROW_H)
                p.drawText(cell, Qt.AlignVCenter | Qt.AlignLeft, fmt(lvl.price, self.decimals))
                p.drawText(cell, Qt.AlignVCenter | Qt.AlignRight, str(lvl.qty))

            if i < len(self.book.asks):
                lvl = self.book.asks[i]
                bw = lvl.qty / vmax * half
                p.fillRect(QRectF(half, y, bw, self.ROW_H), RED_BAR)
                p.setPen(TEXT if lvl.qty >= self.min_plate else MUTED)
                cell = QRectF(half + 8, y, half - 16, self.ROW_H)
                p.drawText(cell, Qt.AlignVCenter | Qt.AlignLeft, str(lvl.qty))
                p.drawText(cell, Qt.AlignVCenter | Qt.AlignRight, fmt(lvl.price, self.decimals))

        p.setPen(LINE)
        p.drawLine(QPointF(half, y0), QPointF(half, y0 + rows * self.ROW_H))
