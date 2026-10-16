"""Libreria: poster, titoli puliti "Nome (anno)", serie, link multipli e link scaduti."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QVariantAnimation, QTimer, QUrl
from PySide6.QtGui import QPainter, QColor, QImage, QPainterPath, QLinearGradient, QFont, QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QScrollArea, QFrame, QMenu,
                               QGridLayout, QDialog, QPlainTextEdit, QListWidget, QListWidgetItem, QInputDialog,
                               QApplication)

from . import icons, names
from .catalog import item_title, is_expired
from .config import history, settings, cover_path, human_time
from .theme import theme
from .widgets import label, button, EmptyState, Segmented, IconButton, animate_in, ease, Card
from .downloads import reveal

_IMG: dict = {}


def _img(path: str | None):
    if not path or not os.path.exists(path):
        return None
    mt = os.path.getmtime(path)
    c = _IMG.get(path)
    if c and c[0] == mt:
        return c[1]
    im = QImage(path)
    if im.isNull():
        return None
    _IMG[path] = (mt, im)
    return im


def subtitle_of(it) -> str:
    parts = []
    if it.get("_eps", 0) > 1:
        ep = f"S{it.get('season') or 1:02d}E{it['episode']:02d}" if it.get("episode") is not None else ""
        return f"Serie  ·  {it['_eps']} episodi" + (f"  ·  ultimo {ep}" if ep else "")
    if it.get("mkind") == "tv" and it.get("tmdb_title"):
        parts.append("Serie")
    if it.get("langs"):
        parts.append(" · ".join(it["langs"][:2]))
    if it.get("res"):
        parts.append({"2160p": "4K", "1080p": "1080p", "720p": "720p"}.get(it["res"], it["res"]))
    d, p = it.get("dur") or 0, it.get("pos") or 0
    if d:
        left = max(0, d - p)
        parts.append("Visto" if left < 60 else f"{human_time(left)} rimanenti")
    return "  ·  ".join(parts)


class Poster(QWidget):
    """Locandina 2:3 con badge (4K, Cinema, Link scaduto), avanzamento e play al passaggio.
    Clic = scheda, clic sul ▶ al centro o doppio clic = guarda subito."""
    clicked = Signal()
    play_now = Signal()

    def __init__(self, it, w=160):
        super().__init__()
        self.it = it
        self.setFixedSize(w, int(w * 1.5))
        self.setCursor(Qt.PointingHandCursor)
        self.img = _img(it.get("poster"))
        self.frame = None if self.img else _img(str(cover_path(it["url"])))
        self.expired = is_expired(it)
        self._h = 0.0
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._a.setEasingCurve(ease())
        self._a.valueChanged.connect(lambda v: (setattr(self, "_h", v), self.update()))

    def enterEvent(self, e):
        self._a.setDuration(max(1, theme.dur(200)))
        self._a.setDirection(QVariantAnimation.Forward)
        self._a.start()

    def leaveEvent(self, e):
        self._a.setDirection(QVariantAnimation.Backward)
        self._a.start()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            c = QRectF(self.rect()).center()
            if (e.position() - c).manhattanLength() < 34:
                self.play_now.emit()
            else:
                self.clicked.emit()

    def mouseDoubleClickEvent(self, e):
        self.play_now.emit()

    def _badge(self, p, x, y, text, bg, fg="white", right=False):
        f = QFont(self.font())
        f.setPointSizeF(theme.fs(7.5))
        f.setBold(True)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(text) + 12
        if right:
            x = x - tw
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(bg))
        p.drawRoundedRect(QRectF(x, y, tw, 18), 5, 5)
        p.setPen(QColor(fg))
        p.drawText(QRectF(x, y, tw, 18), Qt.AlignCenter, text)
        return tw

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.setClipPath(path)
        src = self.img or self.frame
        if src is not None:
            z = 1.0 + 0.05 * self._h
            iw, ih = src.width(), src.height()
            s = max(r.width() / iw, r.height() / ih) * z
            dw, dh = iw * s, ih * s
            p.drawImage(QRectF((r.width() - dw) / 2, (r.height() - dh) / 2, dw, dh), src)
            if not self.img:   # fotogramma: titolo sopra, per riconoscerlo
                g = QLinearGradient(0, 0, 0, r.height())
                g.setColorAt(0, QColor(0, 0, 0, 40))
                g.setColorAt(1, QColor(0, 0, 0, 200))
                p.fillRect(r, g)
        else:
            g = QLinearGradient(0, 0, r.width(), r.height())
            a = QColor(theme.accent)
            g.setColorAt(0, a.darker(230))
            g.setColorAt(1, QColor(theme.surface2))
            p.fillRect(r, g)
        if not self.img:
            f = QFont(self.font())
            f.setPointSizeF(theme.fs(11))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 235))
            p.drawText(r.adjusted(12, 12, -12, -22), Qt.AlignBottom | Qt.AlignLeft | Qt.TextWordWrap,
                       item_title(self.it))
        # badge
        y = 8
        if self.expired:
            self._badge(p, 8, y, "LINK SCADUTO", theme.danger)
        if self.it.get("res") == "2160p":
            self._badge(p, r.width() - 8, y, "4K", QColor(0, 0, 0, 170), right=True)
        if self._h > 0:
            p.fillRect(r, QColor(0, 0, 0, int(70 * self._h)))
            d = 48 * (0.85 + 0.15 * self._h)
            c = QColor(theme.accent)
            c.setAlphaF(0.95 * self._h)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(r.center()), d / 2, d / 2)
            p.setOpacity(self._h)
            isz = int(d * 0.42)
            p.drawPixmap(QPointF(r.center().x() - isz / 2 + 2, r.center().y() - isz / 2),
                         icons.pixmap("retry" if self.expired else "play", theme.on_accent, isz))
            p.setOpacity(1.0)
        d, pos = self.it.get("dur") or 0, self.it.get("pos") or 0
        if d and pos > 10:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 60))
            p.drawRect(QRectF(0, r.height() - 4, r.width(), 4))
            p.setBrush(QColor(theme.accent))
            p.drawRect(QRectF(0, r.height() - 4, r.width() * min(1.0, pos / d), 4))


class PosterTile(QWidget):
    def __init__(self, it, page, w=160):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        self.poster = Poster(it, w)
        self.poster.clicked.connect(lambda: page.show_details(it))
        self.poster.play_now.connect(lambda: page.open_item(it))
        v.addWidget(self.poster)
        t = item_title(it)
        if it.get("_eps", 0) > 1:
            t = t.split(" · ")[0]
        tl = label(t if len(t) < 44 else t[:42] + "…", wrap=True)
        tl.setStyleSheet("font-weight:600;")
        tl.setMaximumWidth(w)
        tl.setToolTip(it.get("overview") or t)
        v.addWidget(tl)
        sub = subtitle_of(it)
        if sub:
            sl = label(sub, "faint", wrap=True)
            sl.setMaximumWidth(w)
            v.addWidget(sl)
        v.addStretch()
        self.setFixedWidth(w)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: page.menu(it, self.mapToGlobal(pos)))


class AddLinksDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Aggiungi link alla libreria")
        self.setMinimumSize(560, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(12)
        v.addWidget(label("Aggiungi link", "sectionTitle"))
        v.addWidget(label("Incolla uno o più link, uno per riga. NOVA legge il nome di ogni file, lo pulisce in "
                          "«Nome (anno)» e cerca il poster. Se un film c'è già, il link nuovo sostituisce quello "
                          "scaduto e la ripresa resta uguale.", "muted", wrap=True))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("https://…\nhttps://…")
        clip = QApplication.clipboard().text().strip()
        if clip.startswith(("http://", "https://")):
            self.text.setPlainText(clip + "\n")
        v.addWidget(self.text, 1)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Annulla", None, None, self.reject))
        r.addWidget(button("Aggiungi", "primary", "plus", self.accept))
        v.addLayout(r)


class FixTitleDialog(QDialog):
    """Correggi titolo: risultati TMDB (con anno) oppure un nome scritto a mano."""

    def __init__(self, parent, it):
        super().__init__(parent)
        self.it = it
        self.choice = None
        self.manual = None
        self.setWindowTitle("Correggi titolo")
        self.setMinimumSize(560, 460)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(10)
        v.addWidget(label("Correggi titolo", "sectionTitle"))
        v.addWidget(label(it.get("parsed") or it.get("title") or "", "faint", wrap=True))
        r = QHBoxLayout()
        self.q = QLineEdit(it.get("ptitle") or item_title(it))
        self.q.returnPressed.connect(self.search)
        r.addWidget(self.q, 1)
        r.addWidget(button("Cerca", "primary", "search", self.search))
        v.addLayout(r)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._pick())
        v.addWidget(self.list, 1)
        self.status = label("", "faint")
        v.addWidget(self.status)
        b = QHBoxLayout()
        b.addWidget(button("Usa il testo come nome", None, "edit", self._manual))
        b.addStretch()
        b.addWidget(button("Annulla", None, None, self.reject))
        b.addWidget(button("Usa questo", "primary", "check", self._pick))
        v.addLayout(b)
        self.results = []
        if settings.get("library", "tmdb_key"):
            QTimer.singleShot(50, self.search)
        else:
            self.status.setText("Senza chiave TMDB puoi solo scrivere il nome a mano.")

    def search(self):
        from .tmdb import search
        q = self.q.text().strip()
        info = names.parse(q)
        title, year = info.get("title") or q, info.get("year")
        kind = self.it.get("mkind") or "movie"
        self.status.setText("Cerco…")
        self.list.clear()

        def work():
            try:
                res = search(title, year, kind)
                if not res and kind == "movie":
                    res = search(title, year, "tv")
                QTimer.singleShot(0, self, lambda: self._show(res))
            except Exception as e:
                msg = f"Errore: {e}"
                QTimer.singleShot(0, self, lambda: self.status.setText(msg))
        threading.Thread(target=work, daemon=True).start()

    def _show(self, res):
        self.results = res
        self.list.clear()
        for r in res:
            it = QListWidgetItem(f"{r['title']} ({r['year'] or '?'})" +
                                 (f"  —  {r['original']}" if r['original'] and r['original'] != r['title'] else "") +
                                 ("   · serie" if r["kind"] == "tv" else ""))
            it.setToolTip(r.get("overview", "")[:400])
            self.list.addItem(it)
        if res:
            self.list.setCurrentRow(0)
        self.status.setText(f"{len(res)} risultati" if res else "Nessun risultato: prova senza anno o in inglese.")

    def _pick(self):
        i = self.list.currentRow()
        if 0 <= i < len(self.results):
            self.choice = self.results[i]
            self.accept()

    def _manual(self):
        if self.q.text().strip():
            self.manual = self.q.text().strip()
            self.accept()


class TmdbBanner(Card):
    def __init__(self, page):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 14, 14, 14)
        h.setSpacing(14)
        ic = label("")
        ic.setPixmap(icons.pixmap("film", theme.accent, 22))
        h.addWidget(ic)
        v = QVBoxLayout()
        v.setSpacing(2)
        v.addWidget(label("Poster ufficiali e titoli puliti", "sectionTitle"))
        v.addWidget(label("Serve una chiave TMDB gratuita (2 minuti): account su themoviedb.org › Impostazioni › API. "
                          "Incollala qui e NOVA scarica da solo poster e «Nome (anno)».", "muted", wrap=True))
        h.addLayout(v, 1)
        h.addWidget(button("Apri TMDB", None, "globe",
                           lambda: QDesktopServices.openUrl(QUrl("https://www.themoviedb.org/settings/api"))))
        h.addWidget(button("Incolla chiave", "primary", "plus", page.ask_key))


class LibraryPage(QWidget):
    play = Signal(str)
    play_item = Signal(dict)
    details = Signal(dict)
    toast = Signal(str, str, str)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog
        root = QVBoxLayout(self)
        m = theme.s(28)
        root.setContentsMargins(m, m - 4, m, m)
        root.setSpacing(theme.s(14))
        head = QHBoxLayout()
        hv = QVBoxLayout()
        hv.setSpacing(2)
        hv.addWidget(label("Libreria", "pageTitle"))
        self.sub = label("I tuoi film e serie con poster, pronti a ripartire da dove eri.", "pageSub")
        hv.addWidget(self.sub)
        head.addLayout(hv, 1)
        head.addWidget(button("Aggiungi link", "primary", "plus", self.add_links), 0, Qt.AlignBottom)
        root.addLayout(head)
        self.banner = TmdbBanner(self)
        root.addWidget(self.banner)
        r = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca un titolo…")
        self.search.textChanged.connect(lambda: self.refresh(force=True))
        self.filter = Segmented([("all", "Tutti"), ("movie", "Film"), ("tv", "Serie"), ("link", "Link"),
                                 ("file", "File")], "all")
        self.filter.changed.connect(lambda _: self.refresh(force=True))
        r.addWidget(self.search, 1)
        r.addWidget(self.filter)
        root.addLayout(r)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(0, 4, 4, 4)
        self.grid.setHorizontalSpacing(theme.s(18))
        self.grid.setVerticalSpacing(theme.s(20))
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)
        history.listeners.append(self.refresh)
        catalog.links_added.connect(self._links_added)
        self._cols = 0
        self._sig = None
        self.refresh(force=True)

    def showEvent(self, e):
        self.refresh(anim=True, force=True)

    def resizeEvent(self, e):
        cols = self._columns()
        if cols != self._cols:
            QTimer.singleShot(0, self, lambda: self.refresh(force=True))

    def _columns(self):
        w = max(300, self.scroll.viewport().width() - 8)
        return max(2, (w + theme.s(18)) // (160 + theme.s(18)))

    def items(self):
        q = self.search.text().lower().strip()
        f = self.filter.value
        out = []
        for i in history.items:
            mk = i.get("mkind") or "movie"
            if f == "movie" and mk != "movie":
                continue
            if f == "tv" and mk != "tv":
                continue
            if f == "link" and i["kind"] != "link":
                continue
            if f == "file" and i["kind"] == "link":
                continue
            if q and q not in item_title(i).lower() and q not in (i.get("title") or "").lower():
                continue
            out.append(i)
        if not q:
            # una locandina per serie (l'episodio più recente); gli episodi sono nella scheda
            seen, grouped = {}, []
            for i in out:
                sk = i.get("show") if i.get("mkind") == "tv" and i.get("show") else None
                if sk is None:
                    grouped.append(i)
                elif sk in seen:
                    seen[sk]["_eps"] += 1
                else:
                    g = dict(i, _eps=1)
                    seen[sk] = g
                    grouped.append(g)
            out = grouped
        return out

    def refresh(self, *_, anim=False, force=False):
        from .catalog import month_summary
        ms = month_summary()
        self.sub.setText(ms or "I tuoi film e serie con poster, pronti a ripartire da dove eri.")
        self.banner.setVisible(not settings.get("library", "tmdb_key") and bool(history.items))
        if not self.isVisible() and not force:
            return
        items = self.items()[:240]
        cols = self._columns()
        sig = (cols, tuple((i["url"], i.get("poster"), i.get("clean"), int(i.get("pos") or 0) // 60,
                            is_expired(i)) for i in items))
        if sig == self._sig and not anim:
            return
        self._sig = sig
        self._cols = cols
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not items:
            q = self.search.text().strip()
            self.grid.addWidget(EmptyState("library", "Nessun risultato" if q else "Libreria vuota",
                                           "I film che guardi compaiono qui con il poster e il punto in cui ti sei "
                                           "fermato. Puoi anche aggiungere tanti link insieme.",
                                           None if q else button("Aggiungi link", "primary", "plus",
                                                                 self.add_links)), 0, 0, 1, cols)
            return
        for n, it in enumerate(items):
            t = PosterTile(it, self)
            self.grid.addWidget(t, n // cols, n % cols, Qt.AlignTop)
            if anim and n < 18:
                animate_in(t, n * 22)

    # ---------- azioni ----------
    def show_details(self, it):
        self.details.emit(it)

    def open_item(self, it):
        if is_expired(it):
            self.renew(it)
            return
        self.play_item.emit(it)

    def add_links(self):
        d = AddLinksDialog(self)
        if d.exec():
            self.toast.emit("Controllo i link…", "Leggo nome e dimensione di ogni file.", "info")
            self.catalog.add_links(d.text.toPlainText())

    def _links_added(self, added, renewed):
        if not added and not renewed:
            self.toast.emit("Nessun link nuovo", "I link erano già in libreria o non validi.", "warn")
            return
        txt = []
        if added:
            txt.append(f"{added} aggiunti")
        if renewed:
            txt.append(f"{renewed} rinnovati (stesso film, link nuovo)")
        self.toast.emit("Libreria aggiornata", " · ".join(txt), "ok")

    def ask_key(self):
        from .tmdb import check_key
        clip = QApplication.clipboard().text().strip()
        key, ok = QInputDialog.getText(self, "Chiave TMDB", "Incolla la API Key (o il Read Access Token):",
                                       text=clip if 20 <= len(clip) <= 400 and " " not in clip else "")
        if not ok or not key.strip():
            return
        good, msg = check_key(key)
        if good:
            settings.set("library", "tmdb_key", key.strip())
            self.toast.emit("TMDB collegato", msg, "ok")
            self.refresh(force=True)
        else:
            self.toast.emit("Chiave TMDB", msg, "err")

    def renew(self, it):
        src = it.get("source")
        if src:
            QDesktopServices.openUrl(QUrl(src))
        clip = QApplication.clipboard().text().strip()
        url, ok = QInputDialog.getText(
            self, "Link scaduto",
            ("Ho aperto la pagina del sito: copia il link nuovo e incollalo qui.\n" if src else
             "Incolla il link nuovo dello stesso film (la ripresa resta uguale):\n") + item_title(it),
            text=clip if clip.startswith(("http://", "https://")) and clip != it["url"] else "")
        if ok and url.strip().startswith(("http://", "https://")):
            new = url.strip()
            history.rekey(it["url"], new)
            history.update_meta(new, {"dead": False})
            self.play_item.emit(history.get(new))

    def set_source(self, it):
        url, ok = QInputDialog.getText(self, "Pagina del sito", "Link della pagina da cui prendi il film "
                                       "(quando il link scade, NOVA la riapre per te):", text=it.get("source", ""))
        if ok:
            history.update_meta(it["url"], {"source": url.strip()})

    def fix_title(self, it):
        d = FixTitleDialog(self, it)
        if d.exec():
            if d.choice:
                self.catalog.choose(it["url"], d.choice)
            elif d.manual:
                self.catalog.set_title(it["url"], d.manual)

    def rename_file(self, it):
        p = Path(it["url"])
        new_name = item_title(it)
        for ch in '<>:"/\\|?*':
            new_name = new_name.replace(ch, " " if ch != ":" else " -")
        new_name = " ".join(new_name.split()) + p.suffix
        dest = p.with_name(new_name)
        if dest == p:
            return
        if dest.exists():
            self.toast.emit("Rinomina", "Esiste già un file con questo nome.", "warn")
            return
        try:
            p.rename(dest)
            for ext in (".srt", ".ass", ".en.srt", ".eng.srt"):
                s = p.with_suffix(ext)
                if s.exists():
                    s.rename(dest.with_suffix(ext))
        except OSError as e:
            self.toast.emit("Rinomina", f"Non riesco (file in uso?): {e}", "err")
            return
        history.rekey(str(p), str(dest))
        history.update_meta(str(dest), {"fname": dest.name})
        self.toast.emit("File rinominato", dest.name, "ok")

    def menu(self, it, gpos):
        m = QMenu(self)
        m.addAction("Riproduci", lambda: self.open_item(it))
        m.addAction("Dettagli", lambda: self.show_details(it))
        m.addAction("Togli dalla mia lista" if it.get("fav") else "Aggiungi alla mia lista",
                    lambda: history.update_meta(it["url"], {"fav": not it.get("fav"), "fav_t": time.time()}))
        if it.get("dur") and (it.get("pos") or 0) > 10:
            m.addAction("Ricomincia dall'inizio", lambda: self.play_item.emit({**it, "restart": True}))
        m.addSeparator()
        m.addAction("Correggi titolo / poster…", lambda: self.fix_title(it))
        if it["kind"] == "link":
            m.addAction("Rinnova link…", lambda: self.renew(it))
            m.addAction("Imposta pagina del sito…", lambda: self.set_source(it))
            if it.get("source"):
                m.addAction("Apri pagina del sito", lambda: QDesktopServices.openUrl(QUrl(it["source"])))
            m.addAction("Copia link", lambda: QApplication.clipboard().setText(it["url"]))
        elif os.path.exists(it["url"]):
            m.addAction("Mostra nella cartella", lambda: reveal(it["url"]))
            if os.path.isfile(it["url"]) and it.get("clean"):
                m.addAction(f"Rinomina file come «{item_title(it)}»", lambda: self.rename_file(it))
        if (it["kind"] == "link" and not is_expired(it)) or os.path.isfile(it["url"]):
            from .downloads import start_phone
            m.addAction("Versione per telefono (max 1,4 GB)", lambda: start_phone(self, it["url"], item_title(it)))
        m.addSeparator()
        m.addAction("Rimuovi dalla libreria", lambda: history.remove(it["url"]))
        m.exec(gpos)
