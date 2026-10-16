"""Home: 'Continua a guardare' con copertine prese dai tuoi video (nessun servizio esterno)."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QMenu

from . import icons
from .config import history, cover_path, human_time
from .catalog import item_title
from .theme import theme
from .widgets import label, button, AnimatedProgress, animate_in, soft_blur, ease

_IMG_CACHE: dict = {}


def load_cover(key: str):
    p = cover_path(key)
    if not p.exists():
        it = history.get(key)
        b = (it or {}).get("backdrop")      # nessun fotogramma ancora: usa l'immagine TMDB del film
        if b and os.path.exists(b):
            img = QImage(b)
            return None if img.isNull() else img
        return None
    mt = p.stat().st_mtime
    c = _IMG_CACHE.get(key)
    if c and c[0] == mt:
        return c[1]
    img = QImage(str(p))
    if img.isNull():
        return None
    _IMG_CACHE[key] = (mt, img)
    return img


def remaining(it) -> str:
    left = max(0, (it.get("dur") or 0) - (it.get("pos") or 0))
    if left < 60:
        return "Finito"
    h, m = int(left // 3600), int(left % 3600 // 60)
    return f"{h}h {m:02d}m rimanenti" if h else f"{m} min rimanenti"


def is_unfinished(it) -> bool:
    d, p = it.get("dur") or 0, it.get("pos") or 0
    return d > 60 and 10 < p < d * 0.95


class CoverImage(QWidget):
    """Copertina arrotondata con barra di avanzamento, zoom e pulsante play al passaggio del mouse."""
    clicked = Signal()

    def __init__(self, it: dict, w: int, h: int, big=False):
        super().__init__()
        self.it = it
        self.big = big
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.img = load_cover(it["url"])
        self._hover = 0.0
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._a.setEasingCurve(ease())
        self._a.valueChanged.connect(lambda v: (setattr(self, "_hover", v), self.update()))

    def enterEvent(self, e):
        self._a.setDuration(max(1, theme.dur(220)))
        self._a.setDirection(QVariantAnimation.Forward)
        self._a.start()

    def leaveEvent(self, e):
        self._a.setDirection(QVariantAnimation.Backward)
        self._a.start()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        rad = 14 if self.big else 12
        path.addRoundedRect(r, rad, rad)
        p.setClipPath(path)
        if self.img is not None:
            z = 1.0 + 0.05 * self._hover
            iw, ih = self.img.width(), self.img.height()
            s = max(r.width() / iw, r.height() / ih) * z
            dw, dh = iw * s, ih * s
            p.drawImage(QRectF((r.width() - dw) / 2, (r.height() - dh) / 2, dw, dh), self.img)
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            a = QColor(theme.accent)
            g.setColorAt(0, a.darker(260))
            g.setColorAt(1, QColor(theme.surface2))
            p.fillRect(r, g)
            sz = 44 if self.big else 30
            p.drawPixmap(QPointF((r.width() - sz) / 2, (r.height() - sz) / 2),
                         icons.pixmap("film" if self.it.get("kind") != "link" else "link", theme.text3, sz))
        # sfumatura in basso per la leggibilità
        g = QLinearGradient(0, r.height() * 0.45, 0, r.height())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 170))
        p.fillRect(r, g)
        if self._hover > 0:
            p.fillRect(r, QColor(0, 0, 0, int(60 * self._hover)))
            d = (54 if self.big else 44) * (0.85 + 0.15 * self._hover)
            c = QColor(theme.accent)
            c.setAlphaF(0.95 * self._hover)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(r.center()), d / 2, d / 2)
            p.setOpacity(self._hover)
            isz = int(d * 0.42)
            p.drawPixmap(QPointF(r.center().x() - isz / 2 + 2, r.center().y() - isz / 2),
                         icons.pixmap("play", theme.on_accent, isz))
            p.setOpacity(1.0)
        d, pos = self.it.get("dur") or 0, self.it.get("pos") or 0
        if d:
            frac = min(1.0, pos / d)
            bh = 4
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRect(QRectF(0, r.height() - bh, r.width(), bh))
            p.setBrush(QColor(theme.accent))
            p.drawRect(QRectF(0, r.height() - bh, r.width() * frac, bh))


class PosterCard(QWidget):
    def __init__(self, it, page, w=272):
        super().__init__()
        self.it = it
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.cover = CoverImage(it, w, int(w * 9 / 16))
        self.cover.clicked.connect(lambda: page.play_item.emit(it))
        v.addWidget(self.cover)
        tt = item_title(it)
        t = label(tt if len(tt) < 38 else tt[:36] + "…")
        t.setStyleSheet("font-weight:600;")
        t.setToolTip(tt)
        v.addWidget(t)
        v.addWidget(label(remaining(it) if it.get("dur") else time.strftime("%d/%m %H:%M", time.localtime(it["time"])),
                          "faint"))
        self.setFixedWidth(w)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: page.menu(it, self.mapToGlobal(pos)))


class Hero(QFrame):
    """Il video da cui riprendere, in grande, con la sua copertina."""

    def __init__(self, it, page):
        super().__init__()
        self.it = it
        self.page = page
        self.setFixedHeight(theme.s(300))
        self.img = load_cover(it["url"])
        self._blur = None
        h = QHBoxLayout(self)
        m = theme.s(32)
        h.setContentsMargins(m, m, m, m)
        v = QVBoxLayout()
        v.setSpacing(theme.s(8))
        v.addStretch()
        kicker = label("CONTINUA A GUARDARE")
        kicker.setStyleSheet(f"color:{theme.accent};font-weight:700;letter-spacing:2px;font-size:{theme.fs(8.5)}pt;")
        v.addWidget(kicker)
        t = label(item_title(it), wrap=True)
        t.setStyleSheet(f"font-size:{theme.fs(22)}pt;font-weight:700;color:white;")
        t.setMaximumWidth(560)
        v.addWidget(t)
        meta = f"{human_time(it.get('pos'))} di {human_time(it.get('dur'))}  ·  {remaining(it)}"
        ml = label(meta)
        ml.setStyleSheet("color:rgba(255,255,255,0.75);")
        v.addWidget(ml)
        bar = AnimatedProgress(height=5)
        bar.setFixedWidth(360)
        QTimer.singleShot(250, bar, lambda: bar.set_value(min(1.0, (it.get("pos") or 0) / max(1, it.get("dur") or 1))))
        v.addWidget(bar)
        row = QHBoxLayout()
        row.setSpacing(10)
        b1 = button(f"Riprendi da {human_time(it.get('pos'))}", "primary", "play", lambda: page.play_item.emit(it))
        b2 = button("Ricomincia", None, "retry", lambda: page.play_item.emit({**it, "restart": True}))
        b2.setStyleSheet("QPushButton{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.18);"
                         "color:white;} QPushButton:hover{background:rgba(255,255,255,0.2);}")
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        v.addSpacing(theme.s(6))
        v.addLayout(row)
        h.addLayout(v, 1)
        if it.get("poster") and os.path.exists(it["poster"]):
            from .library import Poster
            ps = Poster(it, theme.s(150))
            ps.clicked.connect(lambda: page.play_item.emit(it))
            h.addWidget(ps, 0, Qt.AlignVCenter)
        self.setCursor(Qt.PointingHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.page.play_item.emit(self.it)

    def resizeEvent(self, e):
        self._blur = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)
        if self.img is not None:
            if self._blur is None:
                self._blur = soft_blur(self.img, self.width(), self.height())
            if self._blur is not None:
                p.drawImage(QPointF((r.width() - self._blur.width()) / 2, (r.height() - self._blur.height()) / 2),
                            self._blur)
            # copertina nitida a destra, che sfuma verso sinistra
            ih = r.height()
            iw = ih * self.img.width() / self.img.height()
            x0 = r.width() - iw
            p.drawImage(QRectF(x0, 0, iw, ih), self.img)
            shade = QColor(0, 0, 0, 175)
            g = QLinearGradient(x0, 0, x0 + iw * 0.6, 0)
            g.setColorAt(0, shade)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(x0 - 1, 0, iw * 0.6 + 1, ih), g)
            p.fillRect(QRectF(0, 0, max(0, x0), ih), shade)
            g2 = QLinearGradient(0, 0, r.width(), 0)
            g2.setColorAt(0, QColor(0, 0, 0, 120))
            g2.setColorAt(0.6, QColor(0, 0, 0, 0))
            p.fillRect(r, g2)
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            a = QColor(theme.accent)
            g.setColorAt(0, a.darker(170))
            g.setColorAt(1, QColor("#0A0A0E"))
            p.fillRect(r, g)


class Welcome(QFrame):
    def __init__(self, page):
        super().__init__()
        self.setFixedHeight(theme.s(260))
        v = QVBoxLayout(self)
        m = theme.s(36)
        v.setContentsMargins(m, m, m, m)
        v.addStretch()
        t = label("Benvenuto in NOVA")
        t.setStyleSheet(f"font-size:{theme.fs(24)}pt;font-weight:700;color:white;")
        v.addWidget(t)
        d = label("Apri un file, incolla un link o un magnet: i video che guardi compariranno qui, "
                  "con il punto da cui riprendere.", wrap=True)
        d.setStyleSheet("color:rgba(255,255,255,0.75);")
        d.setMaximumWidth(520)
        v.addWidget(d)
        row = QHBoxLayout()
        row.addWidget(button("Apri file", "primary", "folder", page.open_file.emit))
        for txt, ic, key in (("Incolla un link", "link", "stream"), ("Torrent", "magnet", "torrent")):
            b = button(txt, None, ic, lambda _=False, k=key: page.go.emit(k))
            b.setStyleSheet("QPushButton{background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.18);"
                            "color:white;} QPushButton:hover{background:rgba(255,255,255,0.2);}")
            row.addWidget(b)
        row.addStretch()
        v.addSpacing(10)
        v.addLayout(row)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, r.width(), r.height())
        a = QColor(theme.accent)
        g.setColorAt(0, a.darker(150))
        g.setColorAt(0.55, a.darker(300))
        g.setColorAt(1, QColor("#08080B"))
        p.fillRect(r, g)
        p.setOpacity(0.10)
        p.drawPixmap(QPointF(r.width() - 260, r.height() / 2 - 130), icons.pixmap("nova", "#FFFFFF", 260))


class Shelf(QWidget):
    """Riga orizzontale scorrevole di copertine."""

    def __init__(self, title, items, page):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.s(10))
        v.addWidget(label(title, "sectionTitle"))
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollBar:horizontal{height:8px;background:transparent;}"
                         f"QScrollBar::handle:horizontal{{background:{theme.surface3};border-radius:4px;}}")
        host = QWidget()
        h = QHBoxLayout(host)
        h.setContentsMargins(0, 0, 0, 6)
        h.setSpacing(theme.s(16))
        self.cards = []
        for it in items:
            c = PosterCard(it, page)
            self.cards.append(c)
            h.addWidget(c)
        h.addStretch()
        sc.setWidget(host)
        sc.setFixedHeight(int(272 * 9 / 16) + 70)
        v.addWidget(sc)

    def wheelEvent(self, e):
        sc = self.findChild(QScrollArea)
        sc.horizontalScrollBar().setValue(sc.horizontalScrollBar().value() - e.angleDelta().y())


class HomePage(QWidget):
    """Home in stile piattaforma: spotlight in alto e righe di titoli che scorrono."""
    play_item = Signal(dict)
    open_item = Signal(dict)
    open_file = Signal()
    go = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll)
        self._dirty = True
        self.spot = None
        history.listeners.append(self._mark)

    def _mark(self):
        self._dirty = True
        if self.isVisible():
            QTimer.singleShot(0, self, self._rebuild_keep)

    def _rebuild_keep(self):
        pos = self.scroll.verticalScrollBar().value()
        self.rebuild()
        QTimer.singleShot(0, self, lambda: self.scroll.verticalScrollBar().setValue(pos))

    def showEvent(self, e):
        if self._dirty:
            self.rebuild(anim=True)
        elif self.spot:
            self.spot.resume()

    # ---------- contenuti ----------
    @staticmethod
    def _groups(items):
        """Un elemento per serie (l'episodio più recente), i film come sono."""
        seen, out = set(), []
        for i in items:
            k = i.get("show") if i.get("mkind") == "tv" and i.get("show") else i["url"]
            if k in seen:
                continue
            seen.add(k)
            out.append(i)
        return out

    def _card(self, it, w, wide=False, sub=""):
        from .ott import TitleCard
        c = TitleCard(it, w, wide=wide, sub=sub)
        c.open.connect(self.open_item.emit)
        c.play.connect(self.play_item.emit)
        c.menu.connect(lambda i, g: self.menu(i, g))
        return c

    def rebuild(self, anim=False):
        from .ott import Spotlight, Row, details_of, want_details, _ep_sub
        self._dirty = False
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 0, 0, theme.s(30))
        v.setSpacing(theme.s(18))
        items = [i for i in history.items if not str(i.get("url", "")).startswith("zip+")]
        groups = self._groups(items)
        cont = self._groups([i for i in items if is_unfinished(i)])
        blocks = []
        if not items:
            w = QWidget()
            wl = QVBoxLayout(w)
            m = theme.s(28)
            wl.setContentsMargins(m, m, m, 0)
            wl.addWidget(Welcome(self))
            blocks.append(w)
            self.spot = None
        else:
            # in evidenza: prima i film da riprendere, poi gli ultimi con un'immagine bella
            feat = cont[:3] + [i for i in groups if i not in cont[:3] and (i.get("backdrop") or i.get("tmdb")
                                                                           or cover_path(i["url"]).exists())]
            feat = feat[:6] or groups[:1]
            self.spot = Spotlight(feat)
            self.spot.open.connect(self.open_item.emit)
            self.spot.play.connect(self.play_item.emit)
            blocks.append(self.spot)
        w_wide, w_post = theme.s(300), theme.s(158)
        rows = []
        if cont:
            rows.append(("Continua a guardare", [self._card(i, w_wide, True, _ep_sub(i) if i.get("mkind") == "tv"
                                                            else remaining(i)) for i in cont[:20]], ""))
        favs = sorted([i for i in groups if i.get("fav")], key=lambda i: -(i.get("fav_t") or 0))
        if favs:
            rows.append(("La mia lista", [self._card(i, w_post) for i in favs[:30]], ""))
        shows = [i for i in groups if i.get("mkind") == "tv" and i.get("show")]
        if shows:
            rows.append(("Le tue serie", [self._card(i, w_post) for i in shows[:30]], ""))
        movies = [i for i in groups if i.get("mkind") != "tv"]
        if movies:
            rows.append(("Film", [self._card(i, w_post) for i in movies[:30]], ""))
        # per lingua (dal nome del file)
        by_lang: dict = {}
        for i in groups:
            for lg in (i.get("langs") or [])[:1]:
                by_lang.setdefault(lg, []).append(i)
        for lg, lst in sorted(by_lang.items(), key=lambda x: -len(x[1]))[:3]:
            if len(lst) >= 3:
                rows.append((f"In {lg}", [self._card(i, w_post) for i in lst[:30]], ""))
        # per genere (dalle schede TMDB già scaricate)
        by_gen: dict = {}
        for i in groups[:120]:
            d = details_of(i)
            if not d:
                if i.get("tmdb") and groups.index(i) < 30:
                    want_details(i)
                continue
            for g in d.get("genres", [])[:2]:
                by_gen.setdefault(g, []).append(i)
        for g, lst in sorted(by_gen.items(), key=lambda x: -len(x[1]))[:3]:
            if len(lst) >= 3:
                rows.append((g, [self._card(i, w_post) for i in lst[:30]], ""))
        again = [i for i in groups if i.get("finished") or ((i.get("dur") or 0) > 60 and
                                                            (i.get("pos") or 0) >= (i.get("dur") or 0) * 0.95)]
        if again:
            rows.append(("Da rivedere", [self._card(i, w_post) for i in again[:30]], ""))
        for title, cards, sub in rows:
            if cards:
                blocks.append(Row(title, cards, sub))
        for b in blocks:
            v.addWidget(b)
        v.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(host)
        if old:
            old.deleteLater()
        if anim:
            for n, b in enumerate(blocks[1:] if self.spot else blocks):
                animate_in(b, 120 + n * 70, 22)

    def menu(self, it, gpos):
        m = QMenu(self)
        m.addAction("Riproduci", lambda: self.play_item.emit(it))
        m.addAction("Dettagli", lambda: self.open_item.emit(it))
        if it.get("dur"):
            m.addAction("Ricomincia dall'inizio", lambda: self.play_item.emit({**it, "restart": True}))
        m.addAction("Togli dalla mia lista" if it.get("fav") else "Aggiungi alla mia lista",
                    lambda: history.update_meta(it["url"], {"fav": not it.get("fav"), "fav_t": time.time()}))
        m.addSeparator()
        m.addAction("Rimuovi", lambda: history.remove(it["url"]))
        m.exec(gpos)
