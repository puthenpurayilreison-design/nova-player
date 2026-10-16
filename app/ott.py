"""Home e schede in stile piattaforma OTT, con lo stile di NOVA.

- Spotlight: i film da riprendere e gli ultimi visti, a rotazione, con logo del titolo, voto, durata, generi.
- Righe che scorrono: Continua a guardare, La mia lista, Serie, Film, per lingua, per genere, da rivedere.
- Scheda completa: sfondo grande, trama, cast con foto, regia, trailer, episodi, simili nella tua libreria.

Regola d'oro: niente deve pesare sul film. Le immagini si caricano solo quando servono (e restano in memoria),
le animazioni continue si fermano da sole quando il player è in riproduzione o la Home non si vede.
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import (Qt, Signal, QRectF, QPointF, QVariantAnimation, QTimer, QUrl, QPropertyAnimation,
                            QEasingCurve, QSize)
from PySide6.QtGui import (QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont, QPixmap,
                           QDesktopServices, QFontMetrics, QPen)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel,
                               QGraphicsOpacityEffect, QSizePolicy)

from . import icons
from .config import history, cover_path, human_time
from .catalog import item_title, is_expired
from .theme import theme
from .widgets import label, button, ease

LANG_NAMES = {"ml": "Malayalam", "ta": "Tamil", "te": "Telugu", "hi": "Hindi", "kn": "Kannada", "en": "Inglese",
              "it": "Italiano", "ko": "Coreano", "ja": "Giapponese", "es": "Spagnolo", "fr": "Francese",
              "de": "Tedesco", "zh": "Cinese", "bn": "Bengali", "mr": "Marathi", "pt": "Portoghese"}

# ---------------------------------------------------------------- immagini (cache)
_IMG: dict = {}
_PIX: dict = {}


def image(path: str | None) -> QImage | None:
    if not path or not os.path.exists(path):
        return None
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _IMG.get(path)
    if c and c[0] == mt:
        return c[1]
    im = QImage(path)
    if im.isNull():
        return None
    if len(_IMG) > 400:
        _IMG.clear()
        _PIX.clear()
    _IMG[path] = (mt, im)
    return im


def fitted(path: str | None, w: int, h: int, dpr: float = 1.0) -> QPixmap | None:
    """Immagine ritagliata a riempire w×h, già scalata (disegnarla costa quasi zero)."""
    if not path:
        return None
    k = (path, w, h, round(dpr, 2))
    if k in _PIX:
        return _PIX[k]
    im = image(path)
    if im is None:
        return None
    W, H = max(1, int(w * dpr)), max(1, int(h * dpr))
    s = im.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (s.width() - W) // 2, max(0, (s.height() - H) // 4)     # leggermente in alto: volti e titoli
    pm = QPixmap.fromImage(s.copy(x, y, W, H))
    pm.setDevicePixelRatio(dpr)
    _PIX[k] = pm
    return pm


# ---------------------------------------------------------------- dati del titolo
def details_of(it: dict) -> dict | None:
    from .tmdb import cached_details
    return cached_details(it.get("tmdb_kind") or it.get("mkind") or "movie", it.get("tmdb"))


def want_details(it: dict):
    if it.get("tmdb"):
        from .tmdb import loader
        loader().want(it["url"], it.get("tmdb_kind") or it.get("mkind") or "movie", it["tmdb"])


def poster_of(it: dict) -> str | None:
    d = details_of(it) or {}
    for p in (it.get("poster"), d.get("poster_file")):
        if p and os.path.exists(p):
            return p
    return None


def backdrop_of(it: dict) -> str | None:
    d = details_of(it) or {}
    for p in (d.get("backdrop_file"), it.get("backdrop")):
        if p and os.path.exists(p):
            return p
    c = cover_path(it["url"])
    return str(c) if c.exists() else None


def frame_of(it: dict) -> str | None:
    """Per le card orizzontali: il fotogramma del punto in cui eri, altrimenti lo sfondo TMDB."""
    c = cover_path(it["url"])
    if c.exists():
        return str(c)
    return backdrop_of(it)


def show_title(it: dict) -> str:
    d = details_of(it) or {}
    if it.get("mkind") == "tv":
        return d.get("title") or it.get("tmdb_title") or (item_title(it).split(" · ")[0])
    return d.get("title") or item_title(it).rsplit(" (", 1)[0]


def year_of(it: dict) -> str:
    d = details_of(it) or {}
    return str(d.get("year") or it.get("tmdb_year") or it.get("year") or "")


def runtime_text(it: dict, d: dict | None) -> str:
    d = d or {}
    if it.get("mkind") == "tv" or d.get("kind") == "tv":
        n = d.get("seasons")
        return f"{n} {'stagione' if n == 1 else 'stagioni'}" if n else "Serie"
    m = d.get("runtime") or int((it.get("dur") or 0) // 60)
    if not m:
        return ""
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"


def chips(it: dict, d: dict | None = None) -> list[tuple[str, str]]:
    """[(testo, stile)] stile: star | box | plain | badge"""
    d = d if d is not None else details_of(it)
    d = d or {}
    out = []
    if d.get("vote"):
        out.append((f"{d['vote']:.1f}", "star"))
    y = year_of(it)
    if y:
        out.append((y, "plain"))
    rt = runtime_text(it, d)
    if rt:
        out.append((rt, "plain"))
    if d.get("cert"):
        out.append((d["cert"], "box"))
    lang = (it.get("langs") or [None])[0] or LANG_NAMES.get(d.get("lang") or "", "")
    if lang:
        out.append((lang, "plain"))
    res = {"2160p": "4K", "1080p": "HD", "720p": "HD"}.get(it.get("res") or "")
    if res:
        out.append((res, "badge"))
    return out


def chips_widget(items: list[tuple[str, str]], light=True) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(10)
    fg = "rgba(255,255,255,0.86)" if light else theme.text2
    for i, (t, kind) in enumerate(items):
        if kind == "star":
            ic = QLabel()
            ic.setPixmap(icons.pixmap("star", "#F5C518", 15))
            h.addWidget(ic)
            l = QLabel(t)
            l.setStyleSheet("color:#F5C518;font-weight:700;")
        elif kind == "box":
            l = QLabel(t)
            l.setStyleSheet(f"color:{fg};border:1px solid rgba(255,255,255,0.45);border-radius:4px;"
                            "padding:0px 5px;font-size:11px;font-weight:600;")
        elif kind == "badge":
            l = QLabel(t)
            l.setStyleSheet("color:#111;background:rgba(255,255,255,0.88);border-radius:4px;padding:0px 5px;"
                            "font-size:11px;font-weight:800;")
        else:
            l = QLabel(t)
            l.setStyleSheet(f"color:{fg};font-weight:500;")
        h.addWidget(l)
        if i < len(items) - 1 and kind in ("plain",) and items[i + 1][1] == "plain":
            dot = QLabel("·")
            dot.setStyleSheet(f"color:{fg};")
            h.addWidget(dot)
    h.addStretch()
    return w


def player_busy(w: QWidget) -> bool:
    """True se un film è in riproduzione: le animazioni continue si fermano."""
    try:
        p = w.window().player
        return bool(p.player) and not p.get_prop("pause", True) and not p.get_prop("idle-active", True)
    except Exception:
        return False


def ghost_style() -> str:
    return ("QPushButton{background:rgba(255,255,255,0.14);border:1px solid rgba(255,255,255,0.22);color:white;"
            "padding:8px 16px;border-radius:10px;font-weight:600;}"
            "QPushButton:hover{background:rgba(255,255,255,0.26);}")


def primary_big() -> str:
    return ("QPushButton{background:white;color:#0B0B0F;border:none;padding:9px 20px;border-radius:10px;"
            "font-weight:700;} QPushButton:hover{background:rgba(255,255,255,0.86);}")


# ---------------------------------------------------------------- card
class TitleCard(QWidget):
    """Locandina verticale (o orizzontale con wide=True) con zoom, luce e info al passaggio del mouse.
    Clic = scheda, doppio clic o ▶ = guarda subito."""
    open = Signal(dict)
    play = Signal(dict)
    menu = Signal(dict, object)

    PAD = 8

    def __init__(self, it: dict, w: int, wide=False, rank: int | None = None, sub: str = ""):
        super().__init__()
        self.it = it
        self.wide = wide
        self.rank = rank
        self.sub = sub
        self.cw = w
        self.ch = int(w * 9 / 16) if wide else int(w * 1.5)
        self.setFixedSize(w + 2 * self.PAD, self.ch + 2 * self.PAD + (44 if wide else 0))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self._h = 0.0
        self._play_hover = False
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._a.setEasingCurve(QEasingCurve.OutCubic)
        self._a.valueChanged.connect(self._tick)
        self.expired = is_expired(it)
        self.setToolTip(item_title(it))

    def _tick(self, v):
        self._h = v
        self.update()

    def _source(self):
        if getattr(self, "_src", None) is None:
            self._src = (frame_of(self.it) if self.wide else (poster_of(self.it) or backdrop_of(self.it))) or ""
            self._has_poster = bool(not self.wide and poster_of(self.it))
        return self._src or None

    def enterEvent(self, e):
        self._src = None                 # la scheda può essere arrivata nel frattempo
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(220)))
        self._a.setStartValue(self._h)
        self._a.setEndValue(1.0)
        self._a.start()
        want_details(self.it)

    def leaveEvent(self, e):
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(260)))
        self._a.setStartValue(self._h)
        self._a.setEndValue(0.0)
        self._a.start()
        self._play_hover = False

    def _play_rect(self) -> QRectF:
        d = 38
        x = self.PAD + 10
        y = self.PAD + self.ch - d - 12
        return QRectF(x, y, d, d)

    def mouseMoveEvent(self, e):
        ph = self._play_rect().contains(e.position())
        if ph != self._play_hover:
            self._play_hover = ph
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            if self._play_rect().contains(e.position()) or self.wide:
                self.play.emit(self.it)
            else:
                self.open.emit(self.it)
        elif e.button() == Qt.RightButton:
            self.menu.emit(self.it, self.mapToGlobal(e.position().toPoint()))

    def mouseDoubleClickEvent(self, e):
        self.play.emit(self.it)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        h = self._h
        z = 1.0 + 0.045 * h
        cw, ch = self.cw * z, self.ch * z
        x0 = self.PAD + (self.cw - cw) / 2
        y0 = self.PAD + (self.ch - ch) / 2 - 3 * h
        r = QRectF(x0, y0, cw, ch)
        rad = 12
        # ombra e alone nel colore d'accento
        if h > 0.01:
            for i in range(4):
                c = QColor(theme.accent)
                c.setAlphaF(0.07 * h * (4 - i) / 4)
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawRoundedRect(r.adjusted(-2 - i * 2, -1 - i, 2 + i * 2, 4 + i * 2.5), rad + i, rad + i)
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.save()
        p.setClipPath(path)
        src = self._source()
        pm = fitted(src, int(cw), int(ch), self.devicePixelRatioF())
        has_poster = self._has_poster
        if pm is not None:
            p.drawPixmap(r.topLeft(), pm)
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            a = QColor(theme.accent)
            g.setColorAt(0, a.darker(240))
            g.setColorAt(1, QColor("#0B0B10"))
            p.fillRect(r, g)
            p.drawPixmap(QPointF(r.center().x() - 16, r.center().y() - 16 - (20 if not self.wide else 0)),
                         icons.pixmap("film", "rgba(255,255,255,0.35)", 32))
        # titolo scritto sopra quando non c'è la locandina ufficiale
        show_text = not has_poster or h > 0.01 or self.wide
        if show_text:
            g = QLinearGradient(0, r.top() + r.height() * (0.35 if not self.wide else 0.3), 0, r.bottom())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(1, QColor(0, 0, 0, int(225 if (not has_poster or self.wide) else 225 * h)))
            p.fillRect(r, g)
        if not self.wide:
            alpha = 1.0 if not has_poster else h
            if alpha > 0.01:
                p.setOpacity(alpha)
                f = QFont(self.font())
                f.setPointSizeF(theme.fs(10.5))
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor(255, 255, 255))
                tb = r.adjusted(12, 12, -12, -(58 if h > 0.01 else 14))
                p.drawText(tb, Qt.AlignBottom | Qt.AlignLeft | Qt.TextWordWrap, show_title(self.it))
                if h > 0.01:
                    f2 = QFont(self.font())
                    f2.setPointSizeF(theme.fs(8.5))
                    p.setFont(f2)
                    d = details_of(self.it) or {}
                    bits = []
                    if d.get("vote"):
                        bits.append(f"★ {d['vote']:.1f}")
                    if year_of(self.it):
                        bits.append(year_of(self.it))
                    if d.get("genres"):
                        bits.append(d["genres"][0])
                    p.setPen(QColor(255, 255, 255, 200))
                    iw = int(r.width() - 64)
                    txt = "  ·  ".join(bits)
                    while bits and p.fontMetrics().horizontalAdvance(txt) > iw:
                        bits.pop()
                        txt = "  ·  ".join(bits)
                    p.drawText(QRectF(r.left() + 56, r.bottom() - 46, iw, 36), Qt.AlignVCenter | Qt.AlignLeft, txt)
                p.setOpacity(1.0)
        # badge
        f = QFont(self.font())
        f.setPointSizeF(theme.fs(7))
        f.setBold(True)
        p.setFont(f)
        bx = r.left() + 8
        badges = []
        if self.expired:
            badges.append(("LINK SCADUTO", theme.danger, "white"))
        if self.it.get("res") == "2160p":
            badges.append(("4K", "rgba(0,0,0,0.65)", "white"))
        if self.it.get("fav"):
            badges.append(("IN LISTA", theme.accent, theme.on_accent))
        for t, bg, fg in badges:
            tw = p.fontMetrics().horizontalAdvance(t) + 10
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(QRectF(bx, r.top() + 8, tw, 17), 4, 4)
            p.setPen(QColor(fg))
            p.drawText(QRectF(bx, r.top() + 8, tw, 17), Qt.AlignCenter, t)
            bx += tw + 5
        # pulsante play
        if h > 0.01 or self.wide:
            pr = self._play_rect()
            pr.translate(0, -3 * h)
            op = h if not self.wide else max(0.0, h)
            if op > 0.01:
                p.setOpacity(op)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.accent) if self._play_hover else QColor(255, 255, 255, 235))
                p.drawEllipse(pr)
                isz = 16
                p.drawPixmap(QPointF(pr.center().x() - isz / 2 + 1.5, pr.center().y() - isz / 2),
                             icons.pixmap("play", theme.on_accent if self._play_hover else "#0B0B0F", isz))
                p.setOpacity(1.0)
        # avanzamento
        d, pos = self.it.get("dur") or 0, self.it.get("pos") or 0
        if d and pos > 10 and (self.wide or pos < d * 0.95):
            bh = 4
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRect(QRectF(r.left(), r.bottom() - bh, r.width(), bh))
            p.setBrush(QColor(theme.accent))
            p.drawRect(QRectF(r.left(), r.bottom() - bh, r.width() * min(1.0, pos / d), bh))
        p.restore()
        # bordo luminoso al passaggio
        if h > 0.01:
            c = QColor(255, 255, 255)
            c.setAlphaF(0.22 * h)
            p.setPen(QPen(c, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        # testo sotto le card orizzontali
        if self.wide:
            f = QFont(self.font())
            f.setPointSizeF(theme.fs(9.5))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.text))
            fm = QFontMetrics(f)
            ty = self.PAD + self.ch + 8
            p.drawText(QRectF(self.PAD, ty, self.cw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(item_title(self.it), Qt.ElideRight, self.cw))
            f2 = QFont(self.font())
            f2.setPointSizeF(theme.fs(8.5))
            p.setFont(f2)
            p.setPen(QColor(theme.text3))
            p.drawText(QRectF(self.PAD, ty + 19, self.cw, 18), Qt.AlignLeft | Qt.AlignVCenter, self.sub)


# ---------------------------------------------------------------- riga scorrevole
class _Arrow(QWidget):
    clicked = Signal()

    def __init__(self, icon, parent):
        super().__init__(parent)
        self.icon = icon
        self.setFixedSize(44, 44)
        self.setCursor(Qt.PointingHandCursor)
        self._hov = False

    def enterEvent(self, e):
        self._hov = True
        self.update()

    def leaveEvent(self, e):
        self._hov = False
        self.update()

    def mouseReleaseEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 240) if self._hov else QColor(20, 20, 26, 220))
        p.drawEllipse(QRectF(2, 2, 40, 40))
        p.drawPixmap(QPointF(12, 12), icons.pixmap(self.icon, "#0B0B0F" if self._hov else "#FFFFFF", 20))


class Row(QWidget):
    """Riga: titolo + card che scorrono di lato (rotella, frecce o trascinamento della barra)."""
    see_all = Signal(str)

    def __init__(self, title: str, cards: list[QWidget], subtitle: str = "", key: str = ""):
        super().__init__()
        self.key = key
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(theme.s(28) + TitleCard.PAD - 8, 0, theme.s(28), 0)
        t = label(title)
        t.setStyleSheet(f"font-size:{theme.fs(13.5)}pt;font-weight:700;")
        head.addWidget(t)
        if subtitle:
            s = label(subtitle, "faint")
            head.addSpacing(8)
            head.addWidget(s, 0, Qt.AlignBottom)
        head.addStretch()
        v.addLayout(head)
        self.sc = QScrollArea()
        self.sc.setWidgetResizable(True)
        self.sc.setFrameShape(QFrame.NoFrame)
        self.sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sc.setStyleSheet("QScrollArea{background:transparent;}")
        host = QWidget()
        host.setStyleSheet("background:transparent;")
        h = QHBoxLayout(host)
        h.setContentsMargins(theme.s(28) - 8, 0, theme.s(28), 0)
        h.setSpacing(theme.s(6))
        for c in cards:
            h.addWidget(c)
        h.addStretch()
        self.sc.setWidget(host)
        self.sc.setFixedHeight(max(c.height() for c in cards) + 2 if cards else 100)
        v.addWidget(self.sc)
        self.left = _Arrow("chev_left", self)
        self.right = _Arrow("chev_right", self)
        self.left.clicked.connect(lambda: self.page(-1))
        self.right.clicked.connect(lambda: self.page(1))
        self.left.hide()
        self.right.hide()
        self._anim = QPropertyAnimation(self.sc.horizontalScrollBar(), b"value", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.sc.horizontalScrollBar().valueChanged.connect(self._arrows)

    def page(self, d):
        bar = self.sc.horizontalScrollBar()
        target = max(0, min(bar.maximum(), bar.value() + d * int(self.sc.viewport().width() * 0.85)))
        self._anim.stop()
        self._anim.setDuration(max(1, theme.dur(420)))
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(target)
        self._anim.start()

    def _arrows(self, *_):
        if not self.underMouse():
            self.left.hide()
            self.right.hide()
            return
        bar = self.sc.horizontalScrollBar()
        self.left.setVisible(bar.value() > 4)
        self.right.setVisible(bar.value() < bar.maximum() - 4)

    def resizeEvent(self, e):
        y = self.sc.geometry().center().y() - 22
        self.left.move(10, y)
        self.right.move(self.width() - 54, y)

    def enterEvent(self, e):
        self._arrows()
        self.left.raise_()
        self.right.raise_()

    def leaveEvent(self, e):
        self.left.hide()
        self.right.hide()

    def wheelEvent(self, e):
        # rotella verticale = scorre la pagina; con Shift o touchpad laterale = scorre la riga
        dx = e.angleDelta().x() or (e.angleDelta().y() if e.modifiers() & Qt.ShiftModifier else 0)
        if dx:
            bar = self.sc.horizontalScrollBar()
            bar.setValue(bar.value() - dx)
            e.accept()
        else:
            e.ignore()


# ---------------------------------------------------------------- spotlight
class Spotlight(QWidget):
    """In cima alla Home: i titoli in evidenza a rotazione, con dissolvenza e un lento movimento di camera."""
    open = Signal(dict)
    play = Signal(dict)

    INTERVAL = 9000

    def __init__(self, items: list[dict]):
        super().__init__()
        self.items = items
        self.idx = 0
        self.prev = None
        self.fade = 1.0
        self.kb = 0.0
        self.t0 = time.time()
        self.setFixedHeight(theme.s(470))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._fa = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._fa.setEasingCurve(QEasingCurve.InOutCubic)
        self._fa.valueChanged.connect(lambda v: (setattr(self, "fade", v), self.update()))
        self._fa.finished.connect(lambda: setattr(self, "prev", None))
        self.anim = QTimer(self, interval=33)        # movimento lento dello sfondo (solo se si vede)
        self.anim.timeout.connect(self._frame)
        self.rot = QTimer(self, interval=self.INTERVAL)
        self.rot.timeout.connect(lambda: self.go(self.idx + 1))
        self.content = QWidget(self)
        self.content.setAttribute(Qt.WA_TranslucentBackground)
        self.eff = QGraphicsOpacityEffect(self.content)
        self.content.setGraphicsEffect(self.eff)
        self._ca = QPropertyAnimation(self.eff, b"opacity", self)
        self._phase = ""
        self._ca.finished.connect(self._ca_done)
        self._build()
        for it in items:
            want_details(it)
        from .tmdb import loader
        loader().ready.connect(self._details_ready)

    # ---- contenuto (testi e pulsanti) ----
    def _build(self):
        old = self.content.layout()
        if old:
            while old.count():
                w = old.takeAt(0).widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old)
        it = self.items[self.idx]
        d = details_of(it) or {}
        v = QVBoxLayout(self.content)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.s(10))
        v.addStretch()
        kick = "CONTINUA A GUARDARE" if _unfinished(it) else ("LA TUA SERIE" if it.get("mkind") == "tv"
                                                                else "IN EVIDENZA PER TE")
        k = label(kick)
        k.setStyleSheet(f"color:{theme.accent};font-weight:800;letter-spacing:3px;font-size:{theme.fs(8.5)}pt;")
        v.addWidget(k)
        logo = d.get("logo_file")
        lim = image(logo) if logo else None
        if lim is not None:
            l = QLabel()
            mw, mh = theme.s(380), theme.s(130)
            pm = QPixmap.fromImage(lim.scaled(int(mw * self.devicePixelRatioF()), int(mh * self.devicePixelRatioF()),
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation))
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            l.setPixmap(pm)
            v.addWidget(l)
        else:
            t = label(show_title(it), wrap=True)
            t.setStyleSheet(f"color:white;font-size:{theme.fs(30)}pt;font-weight:800;")
            t.setMaximumWidth(theme.s(640))
            v.addWidget(t)
        if it.get("mkind") == "tv" and it.get("episode") is not None:
            ep = label(f"Stagione {it.get('season') or 1} · Episodio {it['episode']}")
            ep.setStyleSheet("color:rgba(255,255,255,0.9);font-weight:600;")
            v.addWidget(ep)
        v.addWidget(chips_widget(chips(it, d)))
        if d.get("genres"):
            g = label("  ·  ".join(d["genres"][:3]))
            g.setStyleSheet("color:rgba(255,255,255,0.7);")
            v.addWidget(g)
        ov = d.get("overview") or it.get("overview") or ""
        if ov:
            o = label(_clip(ov, 230), wrap=True)
            o.setStyleSheet(f"color:rgba(255,255,255,0.82);font-size:{theme.fs(10)}pt;")
            o.setMaximumWidth(theme.s(560))
            v.addWidget(o)
        if _unfinished(it):
            row = QHBoxLayout()
            row.setSpacing(10)
            bar = _Bar(min(1.0, (it.get("pos") or 0) / max(1, it.get("dur") or 1)))
            bar.setFixedWidth(theme.s(220))
            row.addWidget(bar, 0, Qt.AlignVCenter)
            left = max(0, (it.get("dur") or 0) - (it.get("pos") or 0))
            rl = label(f"{int(left // 3600)}h {int(left % 3600 // 60):02d}m rimanenti" if left >= 3600
                       else f"{int(left // 60)} min rimanenti")
            rl.setStyleSheet("color:rgba(255,255,255,0.75);")
            row.addWidget(rl)
            row.addStretch()
            v.addLayout(row)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        b1 = button(f"Riprendi da {human_time(it.get('pos'))}" if _unfinished(it) else "Guarda", None, None,
                    lambda: self.play.emit(it))
        b1.setIcon(icons.icon("play", "#0B0B0F", 18))
        b1.setStyleSheet(primary_big())
        btns.addWidget(b1)
        b2 = button("Dettagli", None, None, lambda: self.open.emit(it))
        b2.setIcon(icons.icon("info", "#FFFFFF", 18))
        b2.setStyleSheet(ghost_style())
        btns.addWidget(b2)
        if d.get("trailer"):
            b3 = button("Trailer", None, None, lambda: open_trailer(d["trailer"]))
            b3.setIcon(icons.icon("trailer", "#FFFFFF", 18))
            b3.setStyleSheet(ghost_style())
            btns.addWidget(b3)
        btns.addStretch()
        v.addSpacing(theme.s(4))
        v.addLayout(btns)
        v.addSpacing(theme.s(56))
        self._place()

    def _place(self):
        m = theme.s(28) + TitleCard.PAD
        self.content.setGeometry(m, 0, min(self.width() - 2 * m, theme.s(700)), self.height())

    def resizeEvent(self, e):
        self._place()

    def _details_ready(self, key, d):
        try:
            if self.items and self.items[self.idx]["url"] == key:
                self._build()
                self.update()
        except RuntimeError:
            pass

    # ---- rotazione ----
    def go(self, i):
        if len(self.items) < 2:
            return
        i %= len(self.items)
        if i == self.idx:
            return
        self.prev = self.idx
        self.idx = i
        self.kb = 0.0
        self.t0 = time.time()
        self._fa.stop()
        self._fa.setDuration(max(1, theme.dur(900)))
        self._fa.start()
        self._ca.stop()
        self._ca.setDuration(max(1, theme.dur(160)))
        self._ca.setStartValue(1.0)
        self._ca.setEndValue(0.0)
        self._phase = "out"
        self._ca.start()
        self.rot.start()

    def _ca_done(self):
        if self._phase == "out":
            self._phase = "in"
            self._swap_in()

    def _swap_in(self):
        self._build()
        self._ca.setDuration(max(1, theme.dur(420)))
        self._ca.setStartValue(0.0)
        self._ca.setEndValue(1.0)
        self._ca.start()

    def _frame(self):
        if not self.isVisible() or player_busy(self):
            self.anim.stop()
            self.rot.stop()
            return
        self.kb = min(1.0, (time.time() - self.t0) / (self.INTERVAL / 1000 + 1))
        self.update()

    def showEvent(self, e):
        self.resume()

    def hideEvent(self, e):
        self.anim.stop()
        self.rot.stop()

    def resume(self):
        if player_busy(self):
            return
        if theme.motion:
            self.anim.start()
        if len(self.items) > 1:
            self.rot.start()

    def mouseReleaseEvent(self, e):
        # pallini in basso a destra
        for i, rr in enumerate(self._dots()):
            if rr.adjusted(-6, -8, 6, 8).contains(e.position()):
                self.go(i)
                return

    def _dots(self):
        n = len(self.items)
        out = []
        x = self.width() - theme.s(28) - TitleCard.PAD
        y = self.height() - theme.s(64)
        for i in reversed(range(n)):
            w = 26 if i == self.idx else 8
            x -= w
            out.insert(0, QRectF(x, y, w, 8))
            x -= 8
        return out

    # ---- disegno ----
    def _bg(self, i):
        return backdrop_of(self.items[i]) if self.items else None

    def _draw_bg(self, p, i, alpha, kb):
        path = self._bg(i)
        W, H = self.width(), self.height()
        over = 0.05
        pm = fitted(path, int(W * (1 + over)), int(H * (1 + over)), self.devicePixelRatioF()) if path else None
        p.setOpacity(alpha)
        if pm is not None:
            # lento movimento di camera: scorre di qualche pixel verso sinistra/in alto
            dx = -W * over * (0.15 + 0.7 * kb)
            dy = -H * over * 0.5 * (0.2 + 0.6 * kb)
            p.drawPixmap(QPointF(dx, dy), pm)
        else:
            g = QLinearGradient(0, 0, W, H)
            a = QColor(theme.accent)
            g.setColorAt(0, a.darker(200))
            g.setColorAt(1, QColor("#07070A"))
            p.fillRect(self.rect(), g)
        p.setOpacity(1.0)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.bg))
        if self.items:
            if self.prev is not None:
                self._draw_bg(p, self.prev, 1.0, 1.0)
            self._draw_bg(p, self.idx, self.fade if self.prev is not None else 1.0, self.kb)
        # sfumature: a sinistra per il testo, in basso verso il colore della pagina
        g = QLinearGradient(0, 0, W, 0)
        g.setColorAt(0, QColor(0, 0, 0, 215))
        g.setColorAt(0.42, QColor(0, 0, 0, 120))
        g.setColorAt(0.75, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), g)
        bgc = QColor(theme.bg)
        g2 = QLinearGradient(0, H * 0.55, 0, H)
        c0 = QColor(bgc)
        c0.setAlpha(0)
        g2.setColorAt(0, c0)
        g2.setColorAt(1, bgc)
        p.fillRect(self.rect(), g2)
        g3 = QLinearGradient(0, 0, 0, H * 0.18)
        g3.setColorAt(0, QColor(0, 0, 0, 90))
        g3.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, W, H * 0.18), g3)
        # pallini
        if len(self.items) > 1:
            p.setRenderHint(QPainter.Antialiasing)
            for i, rr in enumerate(self._dots()):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.accent) if i == self.idx else QColor(255, 255, 255, 110))
                p.drawRoundedRect(rr, 4, 4)
                if i == self.idx and self.rot.isActive():
                    # avanzamento verso la prossima
                    frac = min(1.0, (time.time() - self.t0) / (self.INTERVAL / 1000))
                    p.setBrush(QColor(255, 255, 255, 120))
                    p.drawRoundedRect(QRectF(rr.left(), rr.top(), rr.width() * frac, rr.height()), 4, 4)


class _Bar(QWidget):
    def __init__(self, frac):
        super().__init__()
        self.frac = frac
        self.setFixedHeight(5)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(QRectF(self.rect()), 2.5, 2.5)
        p.setBrush(QColor(theme.accent))
        p.drawRoundedRect(QRectF(0, 0, self.width() * self.frac, self.height()), 2.5, 2.5)


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def _unfinished(it) -> bool:
    d, p = it.get("dur") or 0, it.get("pos") or 0
    return d > 60 and 10 < p < d * 0.95


def open_trailer(key: str):
    if key:
        QDesktopServices.openUrl(QUrl(f"https://www.youtube.com/watch?v={key}"))


# ---------------------------------------------------------------- scheda completa
class _Avatar(QWidget):
    def __init__(self, c: dict):
        super().__init__()
        self.c = c
        self.setFixedSize(104, 150)
        self.setToolTip(f"{c.get('name', '')}\n{c.get('role', '')}")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(12, 0, 80, 80)
        path = QPainterPath()
        path.addEllipse(r)
        p.save()
        p.setClipPath(path)
        pm = fitted(self.c.get("photo_file"), 80, 80, self.devicePixelRatioF())
        if pm is not None:
            p.drawPixmap(r.topLeft(), pm)
        else:
            p.fillRect(r, QColor(theme.surface3))
            f = QFont(self.font())
            f.setPointSizeF(18)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.text2))
            ini = "".join(w[:1] for w in (self.c.get("name") or "?").split()[:2])
            p.drawText(r, Qt.AlignCenter, ini)
        p.restore()
        p.setPen(QColor(theme.text))
        f = QFont(self.font())
        f.setPointSizeF(theme.fs(8.5))
        f.setBold(True)
        p.setFont(f)
        fm = QFontMetrics(f)
        p.drawText(QRectF(0, 86, 104, 18), Qt.AlignHCenter, fm.elidedText(self.c.get("name", ""), Qt.ElideRight, 104))
        f2 = QFont(self.font())
        f2.setPointSizeF(theme.fs(8))
        p.setFont(f2)
        p.setPen(QColor(theme.text3))
        fm2 = QFontMetrics(f2)
        p.drawText(QRectF(0, 104, 104, 34), Qt.AlignHCenter | Qt.TextWordWrap,
                   fm2.elidedText(self.c.get("role", ""), Qt.ElideRight, 200))


class _Backdrop(QWidget):
    """Sfondo grande della scheda: immagine nitida a destra che sfuma nel colore della pagina."""

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.setFixedHeight(theme.s(520))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(theme.bg))
        pm = fitted(self.path, W, H, self.devicePixelRatioF())
        if pm is not None:
            p.drawPixmap(0, 0, pm)
        g = QLinearGradient(0, 0, W, 0)
        g.setColorAt(0, QColor(0, 0, 0, 225))
        g.setColorAt(0.45, QColor(0, 0, 0, 130))
        g.setColorAt(0.8, QColor(0, 0, 0, 20))
        p.fillRect(self.rect(), g)
        bgc = QColor(theme.bg)
        c0 = QColor(bgc)
        c0.setAlpha(0)
        g2 = QLinearGradient(0, H * 0.5, 0, H)
        g2.setColorAt(0, c0)
        g2.setColorAt(1, bgc)
        p.fillRect(self.rect(), g2)


class DetailsView(QFrame):
    """Scheda di un film o di una serie, sopra le pagine (si chiude con Indietro o Esc)."""
    play = Signal(dict)
    closed = Signal()

    def __init__(self, it: dict, win, parent):
        super().__init__(parent)
        self.it = it
        self.win = win
        self.setObjectName("details")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#details{{background:{theme.bg};}}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.lay.addWidget(self.scroll)
        self.back = button("Indietro", None, None, self.close_anim)
        self.back.setParent(self)
        self.back.setIcon(icons.icon("back", "#FFFFFF", 18))
        self.back.setStyleSheet("QPushButton{background:rgba(12,12,16,0.78);border:1px solid rgba(255,255,255,0.18);"
                                "color:white;padding:8px 16px;border-radius:10px;font-weight:600;}"
                                "QPushButton:hover{background:rgba(40,40,52,0.92);}")
        self.back.adjustSize()
        self.back.move(theme.s(24), theme.s(20))
        self._build()
        want_details(it)
        from .tmdb import loader
        loader().ready.connect(self._ready)
        history.listeners.append(self._hist)
        fn = self._hist
        self.destroyed.connect(lambda *_, fn=fn: fn in history.listeners and history.listeners.remove(fn))
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self._a = QPropertyAnimation(self.eff, b"opacity", self)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.parent() and ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    # ---- apertura / chiusura ----
    def open_anim(self, origin: QRectF | None = None):
        self.show()
        self.raise_()
        self.back.raise_()
        self.setFocus()
        self._a.setDuration(max(1, theme.dur(280)))
        self._a.setStartValue(0.0)
        self._a.setEndValue(1.0)
        self._a.setEasingCurve(QEasingCurve.OutCubic)
        self._a.start()
        # i contenuti salgono leggermente mentre compaiono
        host = self.scroll.widget()
        if host and theme.motion:
            m = QPropertyAnimation(host, b"pos", self)
            m.setDuration(max(1, theme.dur(420)))
            m.setStartValue(QPointF(0, 26).toPoint())
            m.setEndValue(QPointF(0, 0).toPoint())
            m.setEasingCurve(QEasingCurve.OutCubic)
            m.start(QPropertyAnimation.DeleteWhenStopped)

    def close_anim(self):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self._a.stop()
        self._a.setDuration(max(1, theme.dur(200)))
        self._a.setStartValue(self.eff.opacity())
        self._a.setEndValue(0.0)
        self._a.finished.connect(self._finish)
        self._a.start()

    def _finish(self):
        try:
            self.parent().removeEventFilter(self)
        except RuntimeError:
            pass
        if self._hist in history.listeners:
            history.listeners.remove(self._hist)
        self.closed.emit()
        self.deleteLater()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Escape, Qt.Key_Backspace):
            self.close_anim()
            return
        super().keyPressEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.BackButton:
            self.close_anim()
            return
        super().mousePressEvent(e)

    def _ready(self, key, d):
        try:
            if key == self.it["url"]:
                pos = self.scroll.verticalScrollBar().value()
                self._build()
                QTimer.singleShot(0, self, lambda: self.scroll.verticalScrollBar().setValue(pos))
        except RuntimeError:
            pass

    def _hist(self):
        try:
            it = history.get(self.it["url"])
            if it and (it.get("fav") != self.it.get("fav")):
                self.it = it
                QTimer.singleShot(0, self, self._build)
        except RuntimeError:
            pass

    # ---- contenuto ----
    def _build(self):
        it = history.get(self.it["url"]) or self.it
        self.it = it
        d = details_of(it) or {}
        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(0, 0, 0, theme.s(40))
        root.setSpacing(0)
        top = _Backdrop(backdrop_of(it))
        tl = QVBoxLayout(top)
        m = theme.s(48)
        tl.setContentsMargins(m, theme.s(80), m, theme.s(24))
        tl.setSpacing(theme.s(10))
        tl.addStretch()
        hrow = QHBoxLayout()
        hrow.setSpacing(theme.s(28))
        pst = poster_of(it)
        if pst:
            pl = QLabel()
            pw, ph = theme.s(190), int(theme.s(190) * 1.5)
            pm = fitted(pst, pw, ph, self.devicePixelRatioF())
            if pm is not None:
                rounded = QPixmap(pm.size())
                rounded.fill(Qt.transparent)
                rounded.setDevicePixelRatio(pm.devicePixelRatio())
                qp = QPainter(rounded)
                qp.setRenderHint(QPainter.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(QRectF(0, 0, pw, ph), 14, 14)
                qp.setClipPath(path)
                qp.drawPixmap(0, 0, pm)
                qp.end()
                pl.setPixmap(rounded)
                pl.setFixedSize(pw, ph)
                hrow.addWidget(pl, 0, Qt.AlignBottom)
        info = QVBoxLayout()
        info.setSpacing(theme.s(10))
        info.addStretch()
        logo = image(d.get("logo_file")) if d.get("logo_file") else None
        if logo is not None:
            l = QLabel()
            dpr = self.devicePixelRatioF()
            px = QPixmap.fromImage(logo.scaled(int(theme.s(420) * dpr), int(theme.s(140) * dpr), Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation))
            px.setDevicePixelRatio(dpr)
            l.setPixmap(px)
            info.addWidget(l)
        else:
            t = label(show_title(it), wrap=True)
            t.setStyleSheet(f"color:white;font-size:{theme.fs(30)}pt;font-weight:800;")
            info.addWidget(t)
        if d.get("original") and d["original"] != d.get("title"):
            o = label(d["original"])
            o.setStyleSheet("color:rgba(255,255,255,0.6);")
            info.addWidget(o)
        info.addWidget(chips_widget(chips(it, d)))
        if d.get("genres"):
            g = label("  ·  ".join(d["genres"]))
            g.setStyleSheet("color:rgba(255,255,255,0.75);font-weight:500;")
            info.addWidget(g)
        if d.get("tagline"):
            tg = label(f"«{d['tagline']}»", wrap=True)
            tg.setStyleSheet(f"color:rgba(255,255,255,0.85);font-style:italic;font-size:{theme.fs(11)}pt;")
            info.addWidget(tg)
        # pulsanti
        btns = QHBoxLayout()
        btns.setSpacing(10)
        unf = _unfinished(it)
        b1 = button(f"Riprendi da {human_time(it.get('pos'))}" if unf else "Guarda", None, None,
                    lambda: self.play.emit(it))
        b1.setIcon(icons.icon("play", "#0B0B0F", 18))
        b1.setStyleSheet(primary_big())
        btns.addWidget(b1)
        if unf:
            b = button("Dall'inizio", None, None, lambda: self.play.emit({**it, "restart": True}))
            b.setIcon(icons.icon("retry", "#FFFFFF", 18))
            b.setStyleSheet(ghost_style())
            btns.addWidget(b)
        if d.get("trailer"):
            b = button("Trailer", None, None, lambda: open_trailer(d["trailer"]))
            b.setIcon(icons.icon("trailer", "#FFFFFF", 18))
            b.setStyleSheet(ghost_style())
            btns.addWidget(b)
        fav = bool(it.get("fav"))
        b = button("Nella mia lista" if fav else "La mia lista", None, None, self._toggle_fav)
        b.setIcon(icons.icon("bookmark_on" if fav else "bookmark", "#FFFFFF", 18))
        b.setStyleSheet(ghost_style())
        btns.addWidget(b)
        b = button("Altro", None, None, None)
        b.setIcon(icons.icon("menu", "#FFFFFF", 18))
        b.setStyleSheet(ghost_style())
        b.clicked.connect(lambda: self._more(b))
        btns.addWidget(b)
        btns.addStretch()
        info.addSpacing(theme.s(6))
        info.addLayout(btns)
        if unf:
            row = QHBoxLayout()
            bar = _Bar(min(1.0, (it.get("pos") or 0) / max(1, it.get("dur") or 1)))
            bar.setFixedWidth(theme.s(260))
            row.addWidget(bar, 0, Qt.AlignVCenter)
            left = max(0, (it.get("dur") or 0) - (it.get("pos") or 0))
            rl = label(f"{human_time(it.get('pos'))} di {human_time(it.get('dur'))}  ·  "
                       f"{int(left // 60)} min rimanenti")
            rl.setStyleSheet("color:rgba(255,255,255,0.75);")
            row.addSpacing(10)
            row.addWidget(rl)
            row.addStretch()
            info.addLayout(row)
        hrow.addLayout(info, 1)
        tl.addLayout(hrow)
        root.addWidget(top)

        body = QVBoxLayout()
        body.setContentsMargins(m, theme.s(16), m, 0)
        body.setSpacing(theme.s(22))
        cols = QHBoxLayout()
        cols.setSpacing(theme.s(40))
        left = QVBoxLayout()
        left.setSpacing(theme.s(10))
        ov = d.get("overview") or it.get("overview") or ""
        left.addWidget(_section("Trama"))
        o = label(ov or "Trama non disponibile. Collega TMDB (Libreria) per trama, cast e trailer.", wrap=True)
        o.setStyleSheet(f"font-size:{theme.fs(10.5)}pt;line-height:150%;color:{theme.text2};")
        o.setMaximumWidth(theme.s(720))
        left.addWidget(o)
        left.addStretch()
        cols.addLayout(left, 3)
        facts = QVBoxLayout()
        facts.setSpacing(theme.s(6))
        facts.addWidget(_section("Informazioni"))
        rows = []
        if d.get("director"):
            rows.append(("Regia" if d.get("kind") != "tv" else "Ideata da", d["director"]))
        if d.get("music"):
            rows.append(("Musiche", d["music"]))
        if d.get("lang"):
            rows.append(("Lingua originale", LANG_NAMES.get(d["lang"], d["lang"])))
        if d.get("votes"):
            rows.append(("Voto TMDB", f"{d['vote']:.1f} su 10 · {d['votes']:,} voti".replace(",", ".")))
        if d.get("kind") == "tv" and d.get("episodes"):
            rows.append(("Episodi", f"{d['episodes']} in {d.get('seasons') or '?'} stagioni"))
        if d.get("status") and d.get("kind") == "tv":
            rows.append(("Stato", {"Returning Series": "In corso", "Ended": "Conclusa", "Canceled": "Cancellata"}
                         .get(d["status"], d["status"])))
        src = {"link": "Link (streaming)", "torrent": "Torrent", "file": "File sul PC"}.get(it.get("kind"), "")
        if src:
            rows.append(("Fonte", src + (" · scaduto" if is_expired(it) else "")))
        if it.get("langs"):
            rows.append(("Audio del file", ", ".join(it["langs"])))
        if it.get("res"):
            rows.append(("Qualità del file", {"2160p": "4K"}.get(it["res"], it["res"])))
        if it.get("size"):
            rows.append(("Dimensione", f"{it['size'] / 1e9:.2f} GB"))
        for k, val in rows:
            r = QHBoxLayout()
            kl = label(k, "faint")
            kl.setFixedWidth(theme.s(130))
            r.addWidget(kl, 0, Qt.AlignTop)
            vl = label(val, wrap=True)
            r.addWidget(vl, 1)
            facts.addLayout(r)
        facts.addStretch()
        cols.addLayout(facts, 2)
        body.addLayout(cols)
        root.addLayout(body)
        # episodi della serie (dalla tua cronologia)
        eps = _episodes_of(it)
        if eps:
            root.addSpacing(theme.s(18))
            cards = []
            for e in eps:
                c = TitleCard(e, theme.s(260), wide=True,
                              sub=_ep_sub(e))
                c.play.connect(self.play.emit)
                c.open.connect(self.play.emit)
                cards.append(c)
            root.addWidget(Row("Episodi", cards, f"{len(eps)} nella tua libreria"))
        # cast
        cast = d.get("cast") or []
        if cast:
            root.addSpacing(theme.s(18))
            cr = QVBoxLayout()
            cr.setContentsMargins(m, 0, m, 0)
            cr.addWidget(_section("Cast"))
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            sc.setFixedHeight(170)
            h2 = QWidget()
            hl = QHBoxLayout(h2)
            hl.setContentsMargins(0, 6, 0, 0)
            hl.setSpacing(6)
            for c in cast[:12]:
                hl.addWidget(_Avatar(c))
            hl.addStretch()
            sc.setWidget(h2)
            cr.addWidget(sc)
            root.addLayout(cr)
        # simili nella tua libreria
        sim = _similar(it, d)
        if sim:
            root.addSpacing(theme.s(10))
            cards = []
            for s in sim:
                c = TitleCard(s, theme.s(150))
                c.open.connect(lambda x: self.win.open_details(x))
                c.play.connect(self.play.emit)
                cards.append(c)
            root.addWidget(Row("Simili nella tua libreria", cards))
        root.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(host)
        if old:
            old.deleteLater()
        self.back.raise_()

    def _toggle_fav(self):
        history.update_meta(self.it["url"], {"fav": not self.it.get("fav"), "fav_t": time.time()})

    def _more(self, anchor):
        from PySide6.QtWidgets import QMenu
        lib = self.win.page("library")
        m = QMenu(self)
        it = self.it
        m.addAction("Correggi titolo / poster…", lambda: lib.fix_title(it))
        if it.get("kind") == "link":
            m.addAction("Rinnova link…", lambda: lib.renew(it))
            from PySide6.QtWidgets import QApplication
            m.addAction("Copia link", lambda: QApplication.clipboard().setText(it["url"]))
        elif os.path.exists(it["url"]):
            from .downloads import reveal
            m.addAction("Mostra nella cartella", lambda: reveal(it["url"]))
        if (it.get("kind") == "link" and not is_expired(it)) or os.path.isfile(it["url"]):
            from .downloads import start_phone
            m.addAction("Versione per telefono (max 1,4 GB)", lambda: start_phone(lib, it["url"], item_title(it)))
        m.addSeparator()
        m.addAction("Rimuovi dalla libreria", lambda: (history.remove(it["url"]), self.close_anim()))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


def _section(t):
    l = label(t)
    l.setStyleSheet(f"font-size:{theme.fs(12.5)}pt;font-weight:700;")
    return l


def _ep_sub(e):
    parts = []
    if e.get("episode") is not None:
        parts.append(f"S{e.get('season') or 1:02d} E{e['episode']:02d}")
    d, p = e.get("dur") or 0, e.get("pos") or 0
    if d:
        parts.append("Visto" if d - p < 60 else (f"{int((d - p) // 60)} min rimanenti" if p > 10 else
                                                f"{int(d // 60)} min"))
    return "  ·  ".join(parts)


def _episodes_of(it) -> list[dict]:
    if it.get("mkind") != "tv" or not it.get("show"):
        return []
    eps = [i for i in history.items if i.get("show") == it["show"]]
    eps.sort(key=lambda i: (i.get("season") or 1, i.get("episode") or 0))
    return eps if len(eps) > 1 or it.get("episode") is not None else []


def _similar(it, d) -> list[dict]:
    g = set((d or {}).get("genres") or [])
    langs = set(it.get("langs") or [])
    out = []
    seen = {it.get("show") or it["url"]}
    for i in history.items:
        k = i.get("show") or i["url"]
        if k in seen:
            continue
        di = details_of(i) or {}
        score = 2 * len(g & set(di.get("genres") or [])) + len(langs & set(i.get("langs") or []))
        if score >= 2:
            out.append((score, i))
            seen.add(k)
    out.sort(key=lambda x: -x[0])
    return [i for _, i in out[:14]]
