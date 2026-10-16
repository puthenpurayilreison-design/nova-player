"""Componenti UI riutilizzabili con animazioni."""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import (Qt, QRectF, QPointF, QPoint, QSize, QTimer, Signal, Property,
                            QPropertyAnimation, QVariantAnimation, QEasingCurve,
                            QParallelAnimationGroup, QAbstractAnimation)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QLinearGradient, QFont,
                           QFontMetrics, QBrush)
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout,
                               QGraphicsOpacityEffect, QStackedWidget, QFrame, QSizePolicy,
                               QButtonGroup, QAbstractButton)

from . import icons
from .theme import theme


def ease(curve=QEasingCurve.OutCubic) -> QEasingCurve:
    return QEasingCurve(curve)


def animate_in(w: QWidget, delay: int = 0, dy: int = 14):
    """Ingresso morbido (fade + slide) di un widget; l'effetto viene rimosso alla fine."""
    if not theme.rich_motion or not w.isVisible() and w.parent() is None:
        return
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)

    def start():
        if w.graphicsEffect() is not eff:
            return
        a = QPropertyAnimation(eff, b"opacity", w)
        a.setDuration(theme.dur(260))
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setEasingCurve(ease())
        base = w.pos()
        m = QPropertyAnimation(w, b"pos", w)
        m.setDuration(theme.dur(300))
        m.setStartValue(base + QPoint(0, dy))
        m.setEndValue(base)
        m.setEasingCurve(ease())
        g = QParallelAnimationGroup(w)
        g.addAnimation(a)
        g.addAnimation(m)

        def done():
            try:
                w.setGraphicsEffect(None)
            except RuntimeError:
                pass
        g.finished.connect(done)
        g.start(QAbstractAnimation.DeleteWhenStopped)
    QTimer.singleShot(int(delay * theme.anim_factor), w, start)


class IconButton(QAbstractButton):
    """Pulsante a icona con hover animato e micro-scale alla pressione."""

    def __init__(self, icon_name: str, tooltip: str = "", size: int = 36, icon_size: int = 20,
                 parent=None, color: str | None = None, on_dark: bool = False, filled: bool = False):
        super().__init__(parent)
        self.filled = filled
        self.accent = None          # colore personalizzato (es. preso dal film)
        self.icon_name = icon_name
        self.icon_size = icon_size
        self.color = color
        self.on_dark = on_dark
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self._hover = 0.0
        self._press = 0.0
        self._ha = QVariantAnimation(self, duration=140, startValue=0.0, endValue=1.0)
        self._ha.valueChanged.connect(self._set_hover)
        self._pa = QVariantAnimation(self, duration=110)
        self._pa.valueChanged.connect(self._set_press)

    def set_icon(self, name: str):
        self.icon_name = name
        self.update()

    def _set_hover(self, v):
        self._hover = v
        self.update()

    def _set_press(self, v):
        self._press = v
        self.update()

    def enterEvent(self, e):
        self._ha.setDuration(max(1, theme.dur(140)))
        self._ha.setDirection(QAbstractAnimation.Forward)
        self._ha.start()

    def leaveEvent(self, e):
        self._ha.setDirection(QAbstractAnimation.Backward)
        self._ha.start()

    def mousePressEvent(self, e):
        self._pa.stop()
        self._pa.setDuration(max(1, theme.dur(90)))
        self._pa.setStartValue(self._press)
        self._pa.setEndValue(1.0)
        self._pa.start()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._pa.stop()
        self._pa.setStartValue(self._press)
        self._pa.setEndValue(0.0)
        self._pa.start()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        scale = 1.0 - 0.08 * self._press
        p.translate(r.center())
        p.scale(scale, scale)
        p.translate(-r.center())
        if self.filled:
            g = QLinearGradient(0, 0, r.width(), r.height())
            ac = QColor(self.accent or theme.accent)
            g.setColorAt(0, ac.lighter(118 + int(12 * self._hover)))
            g.setColorAt(1, ac.darker(105 - int(5 * self._hover)))
            p.setPen(Qt.NoPen)
            if self._hover > 0:
                glow = QColor(self.accent or theme.accent)
                glow.setAlphaF(0.25 * self._hover)
                p.setBrush(glow)
                p.drawEllipse(r.adjusted(-0.5, -0.5, 0.5, 0.5))
            p.setBrush(g)
            p.drawEllipse(r.adjusted(3, 3, -3, -3))
            on = theme.on_accent if not self.accent else ("#111111" if QColor(self.accent).lightnessF() > 0.62 else "#FFFFFF")
            pm = icons.pixmap(self.icon_name, on, self.icon_size)
            off = 1.5 if self.icon_name == "play" else 0
            p.drawPixmap(QPointF((self.width() - self.icon_size) / 2 + off, (self.height() - self.icon_size) / 2), pm)
            return
        if self._hover > 0 or self.isChecked():
            c = QColor("#FFFFFF" if (self.on_dark or theme.dark) else "#000000")
            c.setAlphaF(0.10 * max(self._hover, 0.8 if self.isChecked() else 0))
            if self.isChecked():
                c = QColor(theme.accent)
                c.setAlphaF(0.22)
            p.setBrush(c)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.height() / 2.6, r.height() / 2.6)
        col = self.color or ("#FFFFFF" if self.on_dark else theme.text)
        if not self.isEnabled():
            col = theme.text3
        pm = icons.pixmap(self.icon_name, col, self.icon_size)
        x = (self.width() - self.icon_size) / 2
        y = (self.height() - self.icon_size) / 2
        p.drawPixmap(QPointF(x, y), pm)

    def sizeHint(self):
        return self.size()


class AnimatedProgress(QWidget):
    """Barra di progresso fluida: il valore viene interpolato, mai a scatti."""

    def __init__(self, parent=None, height: int = 6):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._value = 0.0
        self._target = 0.0
        self.color = theme.accent
        self.indeterminate = False
        self._phase = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(ease(QEasingCurve.OutQuad))
        self._anim.valueChanged.connect(self._on)
        self._timer = QTimer(self, interval=16)
        self._timer.timeout.connect(self._tick)

    def _on(self, v):
        self._value = v
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.012) % 1.4
        self.update()

    def set_indeterminate(self, on: bool):
        self.indeterminate = on
        if on and theme.motion:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_value(self, v: float, color: str | None = None):
        v = max(0.0, min(1.0, v or 0.0))
        if color:
            self.color = color
        if abs(v - self._target) < 1e-5:
            return
        self._target = v
        if not theme.motion or v < self._value:
            self._anim.stop()
            self._on(v)
            return
        self._anim.stop()
        self._anim.setDuration(theme.dur(480))
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(v)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        rad = r.height() / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.surface3))
        p.drawRoundedRect(r, rad, rad)
        if self.indeterminate:
            w = r.width() * 0.3
            x = (self._phase - 0.3) * r.width()
            seg = QRectF(x, 0, w, r.height()).intersected(r)
            p.setBrush(QColor(self.color))
            p.drawRoundedRect(seg, rad, rad)
            return
        if self._value > 0:
            fw = max(r.height(), r.width() * self._value)
            g = QLinearGradient(0, 0, fw, 0)
            c = QColor(self.color)
            g.setColorAt(0, c.lighter(125))
            g.setColorAt(1, c)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, fw, r.height()), rad, rad)


class Sparkline(QWidget):
    """Mini grafico della velocità (ultimi N campioni)."""

    def __init__(self, n=60, parent=None):
        super().__init__(parent)
        self.data = deque([0.0] * n, maxlen=n)
        self.color = theme.accent
        self.setFixedSize(120, 34)

    def push(self, v: float):
        self.data.append(float(v or 0))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        mx = max(max(self.data), 1.0)
        w, h = self.width(), self.height() - 2
        n = len(self.data)
        pts = [QPointF(i * w / (n - 1), 1 + h - (v / mx) * (h - 2)) for i, v in enumerate(self.data)]
        path = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):
            mid = (a.x() + b.x()) / 2
            path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
        fill = QPainterPath(path)
        fill.lineTo(w, h + 1)
        fill.lineTo(0, h + 1)
        fill.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        c = QColor(self.color)
        c.setAlphaF(0.35)
        g.setColorAt(0, c)
        c.setAlphaF(0.0)
        g.setColorAt(1, c)
        p.fillPath(fill, g)
        p.setPen(QPen(QColor(self.color), 1.6))
        p.drawPath(path)


class Toggle(QAbstractButton):
    """Interruttore animato stile Windows 11."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 22)
        self._pos = 1.0 if checked else 0.0
        self._a = QVariantAnimation(self)
        self._a.setEasingCurve(ease(QEasingCurve.OutBack))
        self._a.valueChanged.connect(self._set)
        self.toggled.connect(self._anim)

    def _set(self, v):
        self._pos = v
        self.update()

    def _anim(self, on):
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(220)))
        self._a.setStartValue(self._pos)
        self._a.setEndValue(1.0 if on else 0.0)
        self._a.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self._pos
        bg = QColor(theme.accent) if on > 0.5 else QColor(theme.surface3)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + on * (r.width() - d - 6)
        p.setBrush(QColor(theme.on_accent) if on > 0.5 else QColor(theme.text2))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class Segmented(QWidget):
    """Controllo segmentato (scelta singola) con indicatore animato."""
    changed = Signal(str)

    def __init__(self, options: list[tuple[str, str]], value: str, parent=None):
        super().__init__(parent)
        self.options = options
        self.value = value
        self.setFixedHeight(34)
        self.setCursor(Qt.PointingHandCursor)
        fm = QFontMetrics(self.font())
        self.widths = [fm.horizontalAdvance(lbl) + 30 for _, lbl in options]
        self.setFixedWidth(sum(self.widths) + 6)
        self._x = self._xof(value)
        self._a = QVariantAnimation(self)
        self._a.setEasingCurve(ease())
        self._a.valueChanged.connect(self._set)

    def _xof(self, val):
        x = 3
        for (k, _), w in zip(self.options, self.widths):
            if k == val:
                return float(x)
            x += w
        return 3.0

    def _wof(self):
        x = 3
        for w in self.widths:
            if abs(x - self._x) < w / 2:
                return w
            x += w
        return self.widths[0]

    def _set(self, v):
        self._x = v
        self.update()

    def set_value(self, val, emit=False):
        self.value = val
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(240)))
        self._a.setStartValue(self._x)
        self._a.setEndValue(self._xof(val))
        self._a.start()
        if emit:
            self.changed.emit(val)

    def mousePressEvent(self, e):
        x = 3
        for (k, _), w in zip(self.options, self.widths):
            if x <= e.position().x() < x + w:
                if k != self.value:
                    self.set_value(k, emit=True)
                return
            x += w

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(QPen(QColor(theme.border), 1))
        p.setBrush(QColor(theme.surface2))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        # indicatore
        idx_w = self.widths[[k for k, _ in self.options].index(self.value)] if self.value in [k for k, _ in self.options] else self.widths[0]
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.accent))
        p.drawRoundedRect(QRectF(self._x, 3, idx_w, r.height() - 6), 8, 8)
        x = 3
        for (k, lbl), w in zip(self.options, self.widths):
            p.setPen(QColor(theme.on_accent) if k == self.value else QColor(theme.text2))
            p.drawText(QRectF(x, 0, w, r.height()), Qt.AlignCenter, lbl)
            x += w


class NavItem:
    def __init__(self, key, icon, label):
        self.key, self.icon, self.label = key, icon, label


class Sidebar(QWidget):
    """Barra laterale con indicatore che scorre tra le voci."""
    selected = Signal(str)
    refresh = Signal()

    def __init__(self, items: list[NavItem], parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.items = items
        self.current = items[0].key
        self.item_h = 44
        self.top = 84
        self._y = float(self.top)
        self._hover = -1
        self.badges: dict[str, str] = {}
        self.setFixedWidth(208)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._a = QVariantAnimation(self)
        self._a.setEasingCurve(ease(QEasingCurve.OutBack if theme.anim_level == "full" else QEasingCurve.OutCubic))
        self._a.valueChanged.connect(self._set)
        self._rot = 0.0
        self._ref_hover = False
        self._ra = QVariantAnimation(self, startValue=0.0, endValue=360.0, duration=650)
        self._ra.setEasingCurve(QEasingCurve.OutCubic)
        self._ra.valueChanged.connect(lambda v: (setattr(self, "_rot", v), self.update(self._ref_rect().toAlignedRect())))

    def _ref_rect(self):
        return QRectF(self.width() - 50, 26, 32, 32)

    def spin(self):
        self._ra.stop()
        self._ra.start()

    def _set(self, v):
        self._y = v
        self.update()

    def _ypos(self, i):
        if self.items[i].key == "settings":
            return self.height() - 20 - self.item_h
        return self.top + i * (self.item_h + 4)

    def select(self, key: str, emit=True):
        idx = [i.key for i in self.items].index(key)
        self.current = key
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(320)))
        self._a.setStartValue(self._y)
        self._a.setEndValue(float(self._ypos(idx)))
        self._a.start()
        if emit:
            self.selected.emit(key)

    def set_badge(self, key, text):
        if self.badges.get(key) != text:
            self.badges[key] = text
            self.update()

    def resizeEvent(self, e):
        idx = [i.key for i in self.items].index(self.current)
        self._y = float(self._ypos(idx))

    def _hit(self, y):
        for i in range(len(self.items)):
            yy = self._ypos(i)
            if yy <= y < yy + self.item_h:
                return i
        return -1

    def mouseMoveEvent(self, e):
        rh = self._ref_rect().contains(e.position())
        if rh != self._ref_hover:
            self._ref_hover = rh
            self.setToolTip("Aggiorna questa scheda (F5)" if rh else "")
            self.update()
        h = self._hit(e.position().y())
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self._ref_hover = False
        self.update()

    def mousePressEvent(self, e):
        if self._ref_rect().contains(e.position()):
            self.spin()
            self.refresh.emit()
            return
        h = self._hit(e.position().y())
        if h >= 0 and self.items[h].key != self.current:
            self.select(self.items[h].key)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.sidebar))
        p.setPen(QColor(theme.border))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        # logo
        p.drawPixmap(QPointF(22, 28), icons.app_icon().pixmap(28, 28))
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.35)
        f.setWeight(QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        p.setFont(f)
        p.setPen(QColor(theme.text))
        p.drawText(QRectF(60, 26, 100, 32), Qt.AlignVCenter, "NOVA")
        # pulsante Aggiorna
        rr = self._ref_rect()
        if self._ref_hover:
            hc = QColor(theme.text)
            hc.setAlphaF(0.07)
            p.setPen(Qt.NoPen)
            p.setBrush(hc)
            p.drawRoundedRect(rr, 9, 9)
        p.save()
        p.translate(rr.center())
        p.rotate(self._rot)
        p.drawPixmap(QPointF(-9, -9), icons.pixmap("retry", theme.accent if self._ref_hover else theme.text2, 18))
        p.restore()
        # indicatore
        x0, w = 12, self.width() - 24
        p.setPen(Qt.NoPen)
        ac = QColor(theme.accent)
        ac.setAlpha(40)
        p.setBrush(ac)
        p.drawRoundedRect(QRectF(x0, self._y, w, self.item_h), 10, 10)
        p.setBrush(QColor(theme.accent))
        p.drawRoundedRect(QRectF(x0, self._y + 12, 3.5, self.item_h - 24), 2, 2)
        f2 = QFont(self.font())
        f2.setWeight(QFont.DemiBold)
        for i, it in enumerate(self.items):
            y = self._ypos(i)
            if i == self._hover and it.key != self.current:
                c = QColor(theme.text)
                c.setAlphaF(0.05)
                p.setBrush(c)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(x0, y, w, self.item_h), 10, 10)
            active = it.key == self.current
            col = theme.accent if active else theme.text2
            p.drawPixmap(QPointF(30, y + (self.item_h - 20) / 2), icons.pixmap(it.icon, col, 20))
            p.setFont(f2 if active else self.font())
            p.setPen(QColor(theme.text if active else theme.text2))
            p.drawText(QRectF(62, y, 110, self.item_h), Qt.AlignVCenter, it.label)
            b = self.badges.get(it.key)
            if b:
                fm = QFontMetrics(self.font())
                bw = max(20, fm.horizontalAdvance(b) + 12)
                br = QRectF(self.width() - 24 - bw, y + (self.item_h - 20) / 2, bw, 20)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.accent))
                p.drawRoundedRect(br, 10, 10)
                p.setPen(QColor(theme.on_accent))
                p.setFont(self.font())
                p.drawText(br, Qt.AlignCenter, b)


class PageStack(QStackedWidget):
    """Stack di pagine con transizione fade + slide."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.no_anim: set[QWidget] = set()
        self._overlay = None
        self.setAutoFillBackground(True)

    def addWidget(self, w):
        w.setAutoFillBackground(True)          # ogni pagina dipinge il suo sfondo scuro, anche al primo frame
        return super().addWidget(w)

    def paintEvent(self, e):
        QPainter(self).fillRect(self.rect(), QColor(theme.bg))

    def switch(self, w: QWidget):
        """Dissolvenza disegnata da un unico strato opaco sopra lo stack: la pagina nuova resta coperta
        finché non ha finito di disegnarsi (niente lampi bianchi o vuoti al primo frame)."""
        old = self.currentWidget()
        if old is w:
            return
        if not theme.motion or w in self.no_anim or old in self.no_anim or old is None:
            self.setCurrentWidget(w)
            return
        if self._overlay is not None:
            try:
                self._overlay.deleteLater()
            except RuntimeError:
                pass
        a = old.grab()
        w.resize(self.size())
        w.ensurePolished()
        if w.layout():
            w.layout().activate()
        b = w.grab()                     # la pagina nuova disegnata fuori schermo, già completa
        ov = _CrossFade(self, a, b)
        self._overlay = ov
        ov.setGeometry(self.rect())
        ov.show()
        ov.raise_()
        self.setCurrentWidget(w)
        ov.raise_()
        an = QVariantAnimation(ov, startValue=0.0, endValue=1.0, duration=max(1, theme.dur(170)))
        an.setEasingCurve(ease())
        an.valueChanged.connect(ov.set_t)
        an.finished.connect(ov.deleteLater)
        an.start(QAbstractAnimation.DeleteWhenStopped)


class _CrossFade(QWidget):
    def __init__(self, parent, a, b):
        super().__init__(parent)
        self.a, self.b, self.t = a, b, 0.0
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_t(self, v):
        self.t = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.bg))
        p.drawPixmap(0, 0, self.a)
        p.setOpacity(self.t)
        dy = int(10 * (1 - self.t))
        p.drawPixmap(0, dy, self.b)


class Card(QFrame):
    def __init__(self, parent=None, flat=False):
        super().__init__(parent)
        self.setObjectName("cardFlat" if flat else "card")
        self.setAttribute(Qt.WA_StyledBackground, True)


def label(text: str, obj: str | None = None, wrap=False) -> QLabel:
    l = QLabel(text)
    if obj:
        l.setObjectName(obj)
    l.setWordWrap(wrap)
    return l


def button(text: str, kind: str | None = None, icon_name: str | None = None, cb=None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    b.setCursor(Qt.PointingHandCursor)
    if icon_name:
        col = theme.on_accent if kind == "primary" else (theme.danger if kind == "danger" else theme.text)
        b.setIcon(icons.icon(icon_name, col, 18))
        b.setIconSize(QSize(18, 18))
    if cb:
        b.clicked.connect(cb)
    return b


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        v.addWidget(label(title, "pageTitle"))
        if subtitle:
            v.addWidget(label(subtitle, "pageSub"))
        self.row = QHBoxLayout()
        v.addLayout(self.row)


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, action: QPushButton | None = None, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        ic = QLabel()
        ic.setAlignment(Qt.AlignCenter)
        ic.setFixedSize(76, 76)
        ic.setStyleSheet(f"background:{theme.accent_soft}; border-radius:38px;")
        ic.setPixmap(icons.pixmap(icon_name, theme.accent, 34))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(ic)
        row.addStretch()
        v.addLayout(row)
        t = label(title, "sectionTitle")
        t.setAlignment(Qt.AlignCenter)
        d = label(text, "muted", wrap=True)
        d.setAlignment(Qt.AlignCenter)
        d.setMaximumWidth(380)
        v.addWidget(t)
        dr = QHBoxLayout()
        dr.addStretch()
        dr.addWidget(d)
        dr.addStretch()
        v.addLayout(dr)
        if action:
            ar = QHBoxLayout()
            ar.addStretch()
            ar.addWidget(action)
            ar.addStretch()
            v.addSpacing(6)
            v.addLayout(ar)


class Toast(QFrame):
    """Notifica in-app (in basso a destra) con azioni opzionali."""

    def __init__(self, host: QWidget, title: str, text: str = "", actions=None, kind="info", timeout=5000):
        super().__init__(host)
        self.setObjectName("card")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#card{{background:{theme.surface2};border:1px solid {theme.border};border-radius:14px;}}")
        col = {"info": theme.accent, "ok": theme.success, "err": theme.danger, "warn": theme.warning}[kind]
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 10, 12)
        h.setSpacing(12)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background:{col};border-radius:4px;")
        h.addWidget(dot, 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(2)
        t = label(title, "sectionTitle")
        v.addWidget(t)
        if text:
            d = label(text, "muted", wrap=True)
            d.setMaximumWidth(300)
            v.addWidget(d)
        if actions:
            ar = QHBoxLayout()
            ar.setSpacing(6)
            for i, (txt, cb) in enumerate(actions):
                b = button(txt, "primary" if i == 0 else None)
                b.clicked.connect(lambda _=False, c=cb: (c(), self.close_anim()))
                ar.addWidget(b)
            ar.addStretch()
            v.addSpacing(6)
            v.addLayout(ar)
        h.addLayout(v, 1)
        x = IconButton("x", "Chiudi", 26, 14)
        x.clicked.connect(self.close_anim)
        h.addWidget(x, 0, Qt.AlignTop)
        self.setFixedWidth(360)
        self.adjustSize()
        if timeout:
            QTimer.singleShot(timeout, self.close_anim)

    def close_anim(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        if not theme.motion:
            self.deleteLater()
            return
        a = QPropertyAnimation(self, b"pos", self)
        a.setDuration(theme.dur(200))
        a.setStartValue(self.pos())
        a.setEndValue(self.pos() + QPoint(400, 0))
        a.setEasingCurve(QEasingCurve.InCubic)
        a.finished.connect(self.deleteLater)
        a.start()


class ToastHost:
    """Gestisce la pila di toast su una finestra."""

    def __init__(self, win: QWidget):
        self.win = win
        self.toasts: list[Toast] = []

    def show(self, title, text="", actions=None, kind="info", timeout=5000):
        t = Toast(self.win, title, text, actions, kind, timeout)
        t.destroyed.connect(lambda *_: self._remove(t))
        self.toasts.append(t)
        t.show()
        t.raise_()
        self.layout(new=t)
        return t

    def _remove(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
        self.layout()

    def layout(self, new=None):
        try:
            y = self.win.height() - 72
        except RuntimeError:
            return
        for t in reversed(self.toasts):
            try:
                t.adjustSize()
                y -= t.height()
                target = QPoint(self.win.width() - t.width() - 20, y)
                if t is new and theme.motion:
                    t.move(target + QPoint(380, 0))
                    a = QPropertyAnimation(t, b"pos", t)
                    a.setDuration(theme.dur(300))
                    a.setStartValue(t.pos())
                    a.setEndValue(target)
                    a.setEasingCurve(ease(QEasingCurve.OutBack if theme.anim_level == "full" else QEasingCurve.OutCubic))
                    a.start(QAbstractAnimation.DeleteWhenStopped)
                elif not getattr(t, "_closing", False):
                    t.move(target)
                y -= 10
            except RuntimeError:
                pass


class SettingRow(QWidget):
    """Riga impostazione: titolo + descrizione a sinistra, controllo a destra."""

    def __init__(self, title: str, desc: str, control: QWidget, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(theme.s(18), theme.s(12), theme.s(18), theme.s(12))
        v = QVBoxLayout()
        v.setSpacing(2)
        v.addWidget(label(title))
        if desc:
            d = label(desc, "faint", wrap=True)
            v.addWidget(d)
        h.addLayout(v, 1)
        h.addSpacing(16)
        h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)


def divider() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{theme.border};")
    return f


class Pill(QLabel):
    """Etichetta di stato colorata."""

    def __init__(self, text="", color=None, parent=None):
        super().__init__(text, parent)
        self.set(text, color or theme.text2)

    def set(self, text, color):
        c = QColor(color)
        self.setText(text)
        self.setStyleSheet(
            f"background: rgba({c.red()},{c.green()},{c.blue()},0.15); color:{color};"
            f"border-radius: 9px; padding: 2px 9px; font-weight:600; font-size:{theme.fs(8.5)}pt;")


class SpeedHero(Card):
    """Pannello velocità totale: numero grande animato + grafico degli ultimi 2 minuti."""

    def __init__(self, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(theme.s(20), theme.s(14), theme.s(20), theme.s(14))
        h.setSpacing(theme.s(22))
        v = QVBoxLayout()
        v.setSpacing(0)
        self.big = QLabel("0.0")
        self.big.setStyleSheet(f"font-size:{theme.fs(26)}pt;font-weight:700;color:{theme.text};")
        self.unit = QLabel("MB/s")
        self.unit.setStyleSheet(f"font-size:{theme.fs(11)}pt;font-weight:600;color:{theme.accent};")
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.big, 0, Qt.AlignBottom)
        row.addWidget(self.unit, 0, Qt.AlignBottom)
        row.addStretch()
        v.addLayout(row)
        self.sub = label("Nessun trasferimento attivo", "faint")
        v.addWidget(self.sub)
        h.addLayout(v)
        self.spark = Sparkline(120)
        self.spark.setFixedSize(QSize(10, 52))
        self.spark.setMinimumWidth(200)
        self.spark.setMaximumWidth(16777215)
        h.addWidget(self.spark, 1)
        self._shown = 0.0
        self._a = QVariantAnimation(self)
        self._a.setEasingCurve(ease())
        self._a.valueChanged.connect(self._set)

    def _set(self, v):
        self._shown = v
        self.big.setText(f"{v / 1048576:.1f}" if v >= 104857.6 or v == 0 else f"{v / 1024:.0f}")
        self.unit.setText("MB/s" if v >= 104857.6 or v == 0 else "KB/s")

    def update_speed(self, bps: float, sub: str):
        self.spark.push(bps)
        self.sub.setText(sub)
        self._a.stop()
        if theme.motion:
            self._a.setDuration(theme.dur(420))
            self._a.setStartValue(self._shown)
            self._a.setEndValue(float(bps))
            self._a.start()
        else:
            self._set(float(bps))


def soft_blur(img, w: int, h: int):
    """Sfocatura veloce: rimpicciolisce molto e riallarga con filtro morbido (2 passaggi)."""
    from PySide6.QtGui import QImage
    if img is None or img.isNull():
        return None
    small = img.scaled(40, 22, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    mid = small.scaled(160, 90, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    tiny = mid.scaled(40, 22, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return tiny.scaled(max(1, w), max(1, h), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)


class CoverBackdrop(QWidget):
    """Sfondo con la copertina del video sfocata e sfumata nel colore del tema."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._img = None
        self._cache = None
        self._fade = 0.0
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._a.valueChanged.connect(lambda v: (setattr(self, "_fade", v), self.update()))

    def set_cover(self, path):
        from PySide6.QtGui import QImage
        import os
        img = QImage(path) if path and os.path.exists(path) else None
        if img is not None and img.isNull():
            img = None
        self._img = img
        self._cache = None
        if img is not None and theme.motion:
            self._a.stop()
            self._a.setDuration(theme.dur(500))
            self._a.start()
        else:
            self._fade = 1.0
        self.update()

    def resizeEvent(self, e):
        self._cache = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.bg))
        if self._img is not None:
            if self._cache is None or self._cache.size() != self.size():
                b = soft_blur(self._img, self.width(), self.height())
                self._cache = b
            if self._cache is not None:
                p.setOpacity(0.85 * self._fade)
                x = (self.width() - self._cache.width()) / 2
                y = (self.height() - self._cache.height()) / 2
                p.drawImage(QPointF(x, y), self._cache)
                p.setOpacity(1.0)
            g = QLinearGradient(0, 0, 0, self.height())
            c1, c2 = QColor(theme.bg), QColor(theme.bg)
            c1.setAlphaF(0.45)
            c2.setAlphaF(0.92)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillRect(self.rect(), g)


def film_color(img) -> QColor | None:
    """Colore dominante 'vivo' di un fotogramma (per tingere i controlli del player come il film)."""
    try:
        from PySide6.QtGui import QImage
        if img is None or img.isNull():
            return None
        small = img.scaled(32, 18, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_RGB32)
        buckets: dict[int, list] = {}
        for y in range(small.height()):
            for x in range(small.width()):
                c = QColor(small.pixel(x, y))
                h, s, v = c.hsvHueF(), c.hsvSaturationF(), c.valueF()
                if h < 0 or s < 0.25 or v < 0.25:
                    continue
                b = int(h * 18) % 18
                w = s * s * v
                e = buckets.setdefault(b, [0.0, 0.0, 0.0, 0.0])
                e[0] += w
                e[1] += h * w
                e[2] += s * w
                e[3] += v * w
        if not buckets:
            return None
        b, (w, hs, ss, vs) = max(buckets.items(), key=lambda kv: kv[1][0])
        if w < 0.6:
            return None
        h = hs / w
        c = QColor.fromHsvF(h, min(0.85, max(0.55, ss / w)), 0.95)
        return c
    except Exception:
        return None
