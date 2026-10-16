"""Finestra principale: sidebar, pagine, mini-barra download, toast, tray, drag&drop, appunti."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPoint, QRect, QSize, QVariantAnimation
from PySide6.QtGui import QKeySequence, QShortcut, QAction, QGuiApplication, QPainter, QColor
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QApplication,
                               QSystemTrayIcon, QMenu, QFrame)

from . import icons, winutil
from .config import settings, history, VIDEO_EXT, AUDIO_EXT, SUB_EXT, human_speed
from .theme import theme, apply_theme
from .widgets import Sidebar, NavItem, PageStack, ToastHost, AnimatedProgress, label, IconButton
from .player import PlayerPage
from .stream import StreamPage, looks_like_url
from .downloads import DownloadManager, DownloadsPage, reveal
from .torrent import TorrentManager, TorrentPage
from .library import LibraryPage
from .home import HomePage
from .settings_page import SettingsPage

NAV = [NavItem("home", "nova", "Home"), NavItem("player", "player", "Player"), NavItem("stream", "link", "Stream"),
       NavItem("downloads", "download", "Download"), NavItem("torrent", "magnet", "Torrent"),
       NavItem("library", "library", "Libreria"), NavItem("settings", "settings", "Impostazioni")]


class MiniBar(QFrame):
    """Barra globale in basso con lo stato dei download attivi (visibile da ogni sezione)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedHeight(46)
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(20, 0, 20, 0)
        h.setSpacing(14)
        self.ic = label("")
        self.ic.setPixmap(icons.pixmap("download", theme.accent, 18))
        self.text = label("")
        self.bar = AnimatedProgress(height=5)
        self.bar.setFixedWidth(220)
        self.speed = label("", "muted")
        h.addWidget(self.ic)
        h.addWidget(self.text)
        h.addStretch()
        h.addWidget(self.speed)
        h.addWidget(self.bar)
        self._h = 0

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.surface))
        p.setPen(QColor(theme.border))
        p.drawLine(0, 0, self.width(), 0)

    def mousePressEvent(self, e):
        self.win.go("torrent" if self._only_torrent else "downloads")

    def update_state(self, dl, tr):
        n1, s1, f1 = dl
        n2, s2 = tr
        self._only_torrent = n1 == 0 and n2 > 0
        n = n1 + n2
        if not n:
            self.setVisible(False)
            return
        parts = []
        if n1:
            parts.append(f"{n1} download")
        if n2:
            parts.append(f"{n2} torrent")
        self.text.setText(" · ".join(parts) + " in corso")
        self.speed.setText(f"↓ {human_speed(s1 + s2)}")
        self.bar.set_value(f1 if n1 else 0)
        self.bar.set_indeterminate(not n1)
        self.setVisible(True)


class Intro(QWidget):
    """Avvio: la stella di NOVA esplode di luce, le lettere salgono una a una, un riflesso le attraversa,
    poi tutto si apre sulla Home. Circa 1,5 secondi; un clic lo salta."""

    def __init__(self, win):
        super().__init__(win)
        self.setGeometry(win.rect())
        self.t = 0.0
        self.a = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=1550)
        self.a.valueChanged.connect(lambda v: (setattr(self, "t", v), self.update()))
        self.a.finished.connect(self.deleteLater)
        import random
        rnd = random.Random(7)
        self.parts = [(rnd.uniform(0, 6.283), rnd.uniform(0.55, 1.0), rnd.uniform(1.2, 3.2), rnd.uniform(0, 0.12))
                      for _ in range(34)]

    def start(self):
        self.show()
        self.raise_()
        self.a.start()

    def mousePressEvent(self, e):
        self.a.stop()
        self.deleteLater()

    @staticmethod
    def _seg(t, a, b):
        return 0.0 if t <= a else 1.0 if t >= b else (t - a) / (b - a)

    def paintEvent(self, e):
        import math
        from PySide6.QtGui import QPainter, QColor, QFont, QRadialGradient, QLinearGradient, QPen, QFontMetricsF
        from PySide6.QtCore import QRectF, QPointF
        t = self.t
        out = self._seg(t, 0.74, 1.0)
        out_e = out * out * (3 - 2 * out)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        bg = QColor(theme.bg)
        bg.setAlphaF(1 - out_e)
        p.fillRect(self.rect(), bg)
        W, H = self.width(), self.height()
        c = QPointF(W / 2, H / 2 - 24)
        ac = QColor(theme.accent)
        # tutto si allontana un po' mentre sparisce
        p.translate(c)
        p.scale(1 + 0.10 * out_e, 1 + 0.10 * out_e)
        p.translate(-c)
        vis = 1 - out_e
        # alone che respira
        g_in = self._seg(t, 0.0, 0.40)
        g_e = 1 - (1 - g_in) ** 3
        glow = QRadialGradient(c, 320 * g_e + 1)
        a1 = QColor(ac)
        a1.setAlphaF(0.42 * vis * g_e)
        glow.setColorAt(0, a1)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)
        # onda d'urto
        sw = self._seg(t, 0.12, 0.62)
        if 0 < sw < 1:
            rr = 30 + 420 * (1 - (1 - sw) ** 2)
            col = QColor(ac)
            col.setAlphaF(0.55 * (1 - sw) * vis)
            p.setPen(QPen(col, 2.2 * (1 - sw) + 0.6))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, rr, rr)
        # scintille che partono dal centro
        sp = self._seg(t, 0.14, 0.78)
        if 0 < sp < 1:
            p.setPen(Qt.NoPen)
            for ang, spd, size, delay in self.parts:
                k = max(0.0, min(1.0, (sp - delay) / (1 - delay)))
                if k <= 0:
                    continue
                d = 40 + 380 * spd * (1 - (1 - k) ** 2)
                col = QColor(255, 255, 255) if size > 2.6 else QColor(ac).lighter(140)
                col.setAlphaF(max(0.0, (1 - k)) * 0.9 * vis)
                p.setBrush(col)
                p.drawEllipse(QPointF(c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d * 0.75), size, size)
        # la stella: entra con un piccolo rimbalzo
        st = self._seg(t, 0.02, 0.42)
        if st > 0:
            back = 1.70158
            s_ = st - 1
            sc = 1 + (back + 1) * s_ ** 3 + back * s_ ** 2
            sz = 78 * sc
            p.setOpacity(min(1.0, st * 2) * vis)
            p.drawPixmap(QPointF(c.x() - sz / 2, c.y() - sz / 2 - 30), icons.pixmap("nova", theme.accent, int(max(4, sz))))
            p.setOpacity(1.0)
        # lettere che salgono una a una
        f = QFont(self.font())
        f.setPointSizeF(34)
        f.setWeight(QFont.Black)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 12)
        p.setFont(f)
        fm = QFontMetricsF(f)
        word = "NOVA"
        total = fm.horizontalAdvance(word)
        x = c.x() - total / 2
        base = c.y() + 64
        for i, ch in enumerate(word):
            k = self._seg(t, 0.20 + i * 0.07, 0.44 + i * 0.07)
            ke = 1 - (1 - k) ** 3
            p.setOpacity(ke * vis)
            p.setPen(QColor(theme.text))
            p.drawText(QPointF(x, base + 22 * (1 - ke)), ch)
            x += fm.horizontalAdvance(ch) + 12
        p.setOpacity(1.0)
        # riflesso di luce che passa solo dentro le lettere
        sh = self._seg(t, 0.50, 0.82)
        if 0 < sh < 1:
            from PySide6.QtGui import QPainterPath
            tp = QPainterPath()
            xx = c.x() - total / 2
            for ch in word:
                tp.addText(QPointF(xx, base), f, ch)
                xx += fm.horizontalAdvance(ch) + 12
            bx = c.x() - total / 2 - 80 + (total + 160) * sh
            lg = QLinearGradient(bx - 45, 0, bx + 45, 0)
            lg.setColorAt(0, QColor(255, 255, 255, 0))
            lg.setColorAt(0.5, QColor(255, 255, 255, int(235 * vis)))
            lg.setColorAt(1, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(tp)
            ac2 = QColor(ac).lighter(160)
            ac2.setAlphaF(0.55 * vis)
            p.fillRect(QRectF(bx - 70, base - fm.ascent() - 4, 140, fm.height() + 8), ac2)
            p.fillRect(QRectF(bx - 45, base - fm.ascent() - 4, 90, fm.height() + 8), lg)
            p.restore()
        # sottotitolo
        sub = self._seg(t, 0.46, 0.66)
        if sub > 0:
            f2 = QFont(self.font())
            f2.setPointSizeF(10.5)
            f2.setLetterSpacing(QFont.AbsoluteSpacing, 5)
            p.setFont(f2)
            col = QColor(theme.text2)
            col.setAlphaF(sub * vis)
            p.setPen(col)
            p.drawText(QRectF(0, base + 22, W, 30), Qt.AlignHCenter | Qt.AlignTop, "IL TUO CINEMA")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NOVA")
        self.setWindowIcon(icons.app_icon())
        self.resize(1360, 860)
        geo = settings.data.get("window", {}).get("geometry")
        if geo:
            try:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except Exception:
                pass
        self.setMinimumSize(980, 640)
        self.setAcceptDrops(True)
        self.dlm = DownloadManager()
        self.tm = TorrentManager()
        from .catalog import Catalog
        self.catalog = Catalog()
        self.tm.suspicious.connect(self._suspicious)
        self.dlm.finished.connect(self._scan_download)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar(NAV)
        self.sidebar.selected.connect(self.go)
        self.sidebar.refresh.connect(self.refresh_current)
        h.addWidget(self.sidebar)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = PageStack()
        right.addWidget(self.stack, 1)
        self.minibar = MiniBar(self)
        self.minibar.hide()
        right.addWidget(self.minibar)
        h.addLayout(right, 1)

        self.player = PlayerPage()
        self.player.request_fullscreen.connect(self.set_fullscreen)
        self.player.request_pip.connect(self.set_pip)
        self.player.request_download.connect(self.download)
        self.player.status.connect(self._player_status)
        self.player.resume_item.connect(self.play_item)
        self.player.link_expired.connect(self._link_expired)
        self.player.episode_ended.connect(self._episode_ended)
        self.player.request_cinema.connect(self.set_cinema)
        self.player.request_palette.connect(self.open_palette)
        self.player.request_refresh.connect(lambda: (self.sidebar.spin(), self.refresh_current()))
        self.player.turbo.renewed.connect(self._link_renewed)
        self.pages: dict[str, QWidget] = {"player": self.player}
        self.stack.addWidget(self.player)
        self.stack.no_anim.add(self.player)
        self.toasts = ToastHost(self)
        self.go("home")
        # Download e Torrent servono anche in background (notifiche, scelta file): li prepara subito
        # dopo la comparsa della finestra, così l'avvio resta istantaneo.
        QTimer.singleShot(0, lambda: (self.page("downloads"), self.page("torrent")))
        QTimer.singleShot(2500, self._check_components)
        QTimer.singleShot(1200, self.player.prewarm)

        self.player.install_shortcuts(self)
        for key, fn in ((Qt.Key_MediaTogglePlayPause, self.player.toggle_pause),
                        (Qt.Key_MediaPlay, self.player.toggle_pause),
                        (Qt.Key_MediaPause, self.player.toggle_pause),
                        (Qt.Key_MediaNext, lambda: self.player.cmd("playlist-next")),
                        (Qt.Key_MediaPrevious, lambda: self.player.cmd("playlist-prev"))):
            s = QShortcut(QKeySequence(key), self)
            s.setContext(Qt.ApplicationShortcut)
            s.activated.connect(fn)

        f5 = QShortcut(QKeySequence("F5"), self)
        f5.setContext(Qt.ApplicationShortcut)
        f5.activated.connect(lambda: (self.sidebar.spin(), self.refresh_current()))
        ks = QShortcut(QKeySequence("Ctrl+K"), self)
        ks.setContext(Qt.ApplicationShortcut)
        ks.activated.connect(self.open_palette)
        self.dlm.finished.connect(lambda *_: self._badges())
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._last_clip = QApplication.clipboard().text()
        QApplication.clipboard().dataChanged.connect(self._clipboard)
        settings.listeners.append(self._on_setting)
        self._setup_tray()
        self._quitting = False
        self._normal_geo = None

    # ---------- pagine (create alla prima apertura) ----------
    def page(self, key) -> QWidget:
        if key not in self.pages:
            self.pages[key] = p = self._make_page(key)
            self.stack.addWidget(p)
        return self.pages[key]

    def _make_page(self, key):
        if key == "home":
            p = HomePage()
            p.play_item.connect(self.play_item)
            p.open_item.connect(self.open_details)
            p.open_file.connect(lambda: (self.go("player"), self.player.open_files()))
            p.go.connect(self.go)
        elif key == "stream":
            p = StreamPage()
            p.play.connect(self.play)
            p.download.connect(self.download)
        elif key == "downloads":
            p = DownloadsPage(self.dlm)
            p.play.connect(self.play)
            p.toast.connect(self.toast)
        elif key == "torrent":
            p = TorrentPage(self.tm)
            p.play.connect(self.play)
            p.download_direct.connect(lambda u: (self.dlm.add(u, force_direct=True), self.go("downloads")))
            p.toast.connect(self.toast)
            p.open_firewall.connect(self._open_firewall)
        elif key == "library":
            p = LibraryPage(self.catalog)
            p.play_item.connect(self.play_item)
            p.details.connect(self.open_details)
            p.toast.connect(self.toast)
        else:
            p = SettingsPage()
            p.appearance_changed.connect(self._appearance_changed)
            p.changed.connect(self._settings_changed)
            p.toast.connect(self.toast)
            p.open_firewall.connect(self._open_firewall)
        return p

    def _build_pages(self):
        """Ricrea le pagine già aperte (dopo un cambio di tema/densità)."""
        cur = self.sidebar.current
        for key in [k for k in self.pages if k != "player"]:
            old = self.pages[key]
            p = self._make_page(key)
            self.pages[key] = p
            idx = self.stack.indexOf(old)
            self.stack.insertWidget(idx, p)
            self.stack.removeWidget(old)
            self._detach(old)
            old.deleteLater()
        self.stack.setCurrentWidget(self.page(cur))

    def _detach(self, page):
        for attr in ("refresh", "_mark"):
            fn = getattr(page, attr, None)
            if fn in history.listeners:
                history.listeners.remove(fn)
        t = getattr(page, "timer", None)
        if t:
            t.stop()

    def open_details(self, it: dict):
        """Scheda completa di un film o di una serie (sopra la pagina attuale)."""
        from .ott import DetailsView
        old = getattr(self, "_details", None)
        if old is not None:
            try:
                old.deleteLater()
            except RuntimeError:
                pass
        dv = DetailsView(it, self, self.stack)
        dv.play.connect(lambda x, dv=dv: (dv.close_anim(), self.play_item(x)))
        dv.closed.connect(lambda dv=dv: setattr(self, "_details", None) if getattr(self, "_details", None) is dv
                          else None)
        self._details = dv
        dv.open_anim()

    def close_details(self):
        dv = getattr(self, "_details", None)
        if dv is not None:
            try:
                dv.close_anim()
            except RuntimeError:
                pass
            self._details = None

    def go(self, key):
        self.close_details()
        if key != "player" and self.player.is_cinema:
            self.set_cinema(False)
        if self.sidebar.current != key:
            self.sidebar.select(key, emit=False)
        self.stack.switch(self.page(key))

    def refresh_current(self):
        """Pulsante Aggiorna / F5: ricarica la scheda aperta."""
        key = self.sidebar.current
        p = self.pages.get(key)
        msg = "Aggiornato"
        try:
            if key == "player":
                if not self.player.reload():
                    msg = "Niente da ricaricare"
                else:
                    msg = "Video ricaricato dallo stesso punto"
            elif key == "home" and p:
                p.rebuild(anim=True)
            elif key == "stream" and p:
                p.refresh()
            elif key == "downloads" and p:
                n = self.dlm.retry_errors()
                for iid, c in list(p.cards.items()):
                    it = self.dlm.items.get(iid)
                    if it:
                        c.refresh(it)
                p.refresh()
                if n:
                    msg = f"Riprovo {n} download non riusciti"
            elif key == "torrent" and p:
                n = self.tm.reannounce_all()
                p.refresh()
                if n:
                    msg = f"Cerco nuovi peer per {n} torrent"
            elif key == "library" and p:
                for it in history.items:
                    it.pop("tmdb_fail", None)
                self.catalog._scan()
                p.refresh(anim=True, force=True)
            elif key == "settings" and p:
                p.build()
        except Exception as e:
            msg = f"Aggiornamento non riuscito: {e}"
        self.toast(msg, "", "info")

    # ---------- azioni globali ----------
    def play(self, url: str):
        """Riproduce un file o un link. I link dello stream torrent vengono legati al file finale,
        così la ripresa e la copertina funzionano anche al riavvio (la porta locale cambia)."""
        self.go("player")
        info = self.tm.resolve_stream(url) if url.startswith("http://127.0.0.1:") else None
        if info:
            tid, idx, path, name = info
            self.player.play(url, title=name, kind="torrent", key=path, hist_extra={"tid": tid, "idx": idx})
        else:
            self.player.play(url)
        self.raise_()
        self.activateWindow()

    def play_item(self, it: dict):
        """Riprende un elemento della cronologia (Home/Libreria), scegliendo la fonte migliore."""
        key = it["url"]
        start = 0.0 if it.get("restart") else None
        if it.get("kind") == "torrent":
            if os.path.isfile(key) and self.tm.is_complete(it.get("tid"), it.get("idx")):
                target = key
            else:
                target = self.tm.stream_url(it.get("tid")) if it.get("tid") in self.tm.items else None
                if not target:
                    target = key if os.path.isfile(key) else None
            if not target:
                self.toast("Non disponibile", "Il torrent è stato rimosso e il file non c'è più.", "warn")
                return
            self.go("player")
            self.player.play(target, title=it.get("title"), kind="torrent", key=key, start=start,
                             hist_extra={"tid": it.get("tid"), "idx": it.get("idx")})
        elif it.get("kind") != "link" and not os.path.exists(key):
            self.toast("File non trovato", "È stato spostato o eliminato.", "warn")
            return
        else:
            self.go("player")
            self.player.play(key, title=it.get("title"), kind=it.get("kind"), start=start)
        self.raise_()
        self.activateWindow()

    def download(self, url: str):
        if url.startswith("magnet:"):
            self.go("torrent")
            self.page("torrent").add_input(url)
        else:
            self.go("downloads")
            self.page("downloads").add_url(url)

    def toast(self, title, text="", kind="info"):
        self.toasts.show(title, text, None, kind)

    def notify(self, title, text, actions=None):
        self.toasts.show(title, text, actions, "ok", timeout=9000)
        if not self.isActiveWindow() and self.tray.isVisible():
            self.tray.showMessage(title, text, icons.app_icon(), 6000)

    def handle_args(self, args: list[str]):
        for a in args:
            if a == "--tray":
                continue
            if a.startswith("magnet:") or a.lower().endswith(".torrent"):
                self.go("torrent")
                self.page("torrent").add_input(a)
            elif os.path.isfile(a) or looks_like_url(a):
                QTimer.singleShot(0, lambda a=a: self.play(a))
        if args:
            self.show_normal()

    def show_normal(self):
        if self.isMinimized() or not self.isVisible():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------- schermo intero / PiP ----------
    def set_fullscreen(self, on: bool):
        if on == self.player.is_fullscreen:
            return
        if on and self.player.is_pip:
            self.set_pip(False)
        self.sidebar.setVisible(not on and not self.player.is_cinema)
        self.minibar.setVisible(False if on else self.minibar.isVisible())
        if on:
            self.go("player")
            self.showFullScreen()
        else:
            self.showNormal()
        self.player.set_fullscreen_mode(on)
        self.player.controls.b_fs.set_icon("exitfs" if on else "fullscreen")

    def set_cinema(self, on: bool):
        """Modalità cinema: solo il film e i controlli, senza menu laterale né intestazione."""
        if on == self.player.is_cinema:
            return
        if on:
            if self.player.is_pip:
                self.set_pip(False)
            self.go("player")
        self.player.set_cinema_mode(on)
        if not self.player.is_fullscreen and not self.player.is_pip:
            self.sidebar.setVisible(not on)
        if on:
            self.minibar.hide()

    def set_pip(self, on: bool):
        if on == self.player.is_pip:
            return
        if on and self.player.is_cinema:
            self.set_cinema(False)
        if on and self.player.is_fullscreen:
            self.set_fullscreen(False)
        self.player.set_pip_mode(on)
        self.sidebar.setVisible(not on)
        if on:
            self.go("player")
            self._normal_geo = self.geometry()
            self.minibar.hide()
            self.setMinimumSize(320, 180)
            scr = self.screen().availableGeometry()
            w, h = 520, 293
            self.setGeometry(scr.right() - w - 24, scr.bottom() - h - 24, w, h)
            winutil.set_topmost(int(self.winId()), True)
        else:
            winutil.set_topmost(int(self.winId()), False)
            self.setMinimumSize(980, 640)
            if self._normal_geo:
                self.setGeometry(self._normal_geo)

    # ---------- tick ----------
    def _tick(self):
        self._badges()
        self._priority()

    def _priority(self):
        """Priorità al film: se guardi qualcosa dalla rete, i download non gli rubano banda."""
        on = bool(settings.get("downloads", "player_priority")) and self.player.watching_network()
        tid = None
        if on and self.player.current_url.startswith("http://127.0.0.1:"):
            info = self.tm.resolve_stream(self.player.current_url)
            tid = info[0] if info else None
        self.dlm.set_player_priority(on)
        self.tm.set_player_priority(on, tid)
        net = self.player.watching_network()
        wifi = bool(settings.get("downloads", "wifi_streaming")) and net
        if wifi != getattr(self, "_wifi_on", False):
            self._wifi_on = wifi
            winutil.wifi_streaming(wifi)
        playing = bool(self.player.player) and not self.player.get_prop("pause", True) \
            and not self.player.get_prop("idle-active", True)
        if playing != getattr(self, "_prio_on", False):
            self._prio_on = playing
            winutil.playback_priority(playing)

    def _check_components(self):
        """Se mancano mpv/aria2/ffmpeg/yt-dlp (es. dopo un'installazione incompleta) li riscarica da sola."""
        if sys.platform != "win32":
            return
        from . import deps
        deps.progress_cb = lambda *a: None
        miss = deps.missing()
        if not miss:
            self._update_ytdlp()
            return
        self.toast("Preparo i componenti", "Scarico " + ", ".join(miss) + " (una volta sola)…", "info")
        import threading

        def work():
            failed = deps.ensure(log=lambda *_: None)
            QTimer.singleShot(0, self, lambda: self.toast(
                "Componenti pronti" if not failed else "Componenti non scaricati",
                "" if not failed else "Controlla la connessione: " + ", ".join(failed), "ok" if not failed else "err"))
        threading.Thread(target=work, daemon=True).start()

    def _update_ytdlp(self):
        """yt-dlp va tenuto aggiornato (i siti cambiano spesso): ogni 3 giorni si aggiorna da solo, in silenzio."""
        import time
        import threading
        meta = settings.data.setdefault("meta", {})
        if time.time() - float(meta.get("ytdlp_checked") or 0) < 3 * 86400:
            return
        meta["ytdlp_checked"] = time.time()
        settings.save()
        from .config import tool
        exe = tool("yt-dlp")
        if not os.path.isabs(exe) or not os.path.exists(exe):
            return

        def work():
            import subprocess
            try:
                subprocess.run([exe, "-U"], capture_output=True, timeout=180, creationflags=0x08000000)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def open_palette(self):
        from .palette import CommandPalette
        if self.player.is_fullscreen:
            self.set_fullscreen(False)
        CommandPalette(self).show()

    def play_intro(self):
        if settings.get("appearance", "intro") and theme.motion:
            Intro(self).start()

    # ---------- sicurezza ----------
    def _suspicious(self, tid, why):
        self.toasts.show("Torrent sospetto", why + " Ti consiglio di eliminarlo.",
                         [("Elimina", lambda: self.tm.remove(tid, delete_files=True)), ("Tienilo", lambda: None)],
                         "err", timeout=0)

    def _scan_download(self, iid):
        """File scaricati che possono contenere programmi (zip, exe…): controllo con Windows Defender."""
        from .safety import needs_scan, defender_scan
        it = self.dlm.items.get(iid) or {}
        path = it.get("path")
        if not path or not os.path.isfile(path) or not needs_scan(path):
            return
        import threading

        def work():
            res, msg = defender_scan(path)
            QTimer.singleShot(0, self, lambda: self._scan_result(Path(path).name, res, msg))
        threading.Thread(target=work, daemon=True).start()

    def _scan_result(self, name, res, msg):
        if res == "threat":
            self.toasts.show("Virus trovato", f"{name}: {msg}. Non aprirlo: eliminalo.", None, "err", timeout=0)
        elif res == "clean":
            self.toast("Controllato con Windows Defender", f"{name}: nessuna minaccia.", "ok")

    # ---------- serie: episodio successivo ----------
    def _episode_ended(self, key):
        if not settings.get("library", "next_episode") or getattr(self, "_next_toast_for", None) == key:
            return
        nxt = self.catalog.next_episode(key)
        if not nxt:
            return
        self._next_toast_for = key
        target, title = nxt
        state = {"cancel": False}

        def go():
            if state["cancel"] or self.player.current_key != key:
                return
            state["cancel"] = True
            it = history.get(target)
            if it:
                self.play_item(it)
            else:
                self.play(target)
        t = self.toasts.show("Prossimo episodio", title + " · parte tra 10 secondi",
                             [("Guarda ora", go), ("No", lambda: state.update(cancel=True))], "info", 10000)
        QTimer.singleShot(10000, go)

    # ---------- link scaduti durante lo streaming ----------
    def _link_expired(self, sid):
        self._awaiting_renew = True
        self.player.set_prop("pause", True)
        self.toasts.show("Link scaduto",
                         "Il film è fermo sul punto giusto. Copia dal sito un link nuovo dello stesso film: "
                         "NOVA lo usa da solo appena lo copi.",
                         [("Usa link copiato", self._renew_from_clipboard), ("Annulla", lambda: None)],
                         "warn", timeout=0)

    def _renew_from_clipboard(self):
        url = QApplication.clipboard().text().strip()
        if not url.startswith(("http://", "https://")):
            self.toast("Nessun link copiato", "Copia prima il link nuovo dal sito.", "warn")
            QTimer.singleShot(300, lambda: self._link_expired(self.player.turbo_sid))
            return
        self.toast("Controllo il link nuovo…", "", "info")
        self.player.renew_link(url)

    def _link_renewed(self, sid, ok, msg):
        if ok:
            self._awaiting_renew = False
            for t in list(self.toasts.toasts):
                t.close_anim()
            self.toast("Link rinnovato", "Si riparte dallo stesso punto.", "ok")
            self.player.set_prop("pause", False)
        else:
            self.toast("Link non valido", msg, "err")
            QTimer.singleShot(400, lambda: self._link_expired(sid))

    def _badges(self):
        dl = self.dlm.stats()
        tr = self.tm.stats() if self.tm.ses else (0, 0)
        self.sidebar.set_badge("downloads", str(dl[0]) if dl[0] else "")
        self.sidebar.set_badge("torrent", str(tr[0]) if tr[0] else "")
        if not self.player.is_fullscreen and not self.player.is_pip and not self.player.is_cinema:
            self.minibar.update_state(dl, tr)
        self.tray.setToolTip(f"NOVA — ↓ {human_speed(dl[1] + tr[1])}" if dl[0] + tr[0] else "NOVA")

    def _player_status(self, text, kind):
        if kind == "err":
            self.toast("Player", text, "err")
        elif kind == "info" and text:
            self.toast("Player", text, "info")

    # ---------- impostazioni ----------
    def _on_setting(self, sec, key):
        pass

    def _open_firewall(self):
        ok = winutil.open_firewall(int(settings.get("torrent", "port")))
        self.toast("Firewall", "Conferma la richiesta di Windows: NOVA aprirà la porta torrent." if ok
                   else "Disponibile solo su Windows.", "info")

    def _appearance_changed(self):
        for t in list(self.toasts.toasts):
            t.deleteLater()
        scroll = self.pages["settings"].scroll.verticalScrollBar().value() if "settings" in self.pages else 0
        apply_theme(QApplication.instance())
        winutil.dark_titlebar(int(self.winId()), theme.dark)
        winutil.dark_background(int(self.winId()), theme.bg)
        winutil.caption_color(int(self.winId()), theme.sidebar)
        QTimer.singleShot(0, lambda: self._rebuild(scroll))

    def _rebuild(self, scroll):
        self._build_pages()
        self.sidebar.update()
        self.player.controls.set_overlay(self.player.is_fullscreen)
        self.player.install_shortcuts(self)
        self.player.bind_keys()
        self.minibar.ic.setPixmap(icons.pixmap("download", theme.accent, 18))
        for w in self.findChildren(QWidget):
            w.update()
        if "settings" in self.pages:
            QTimer.singleShot(30, lambda: self.pages["settings"].scroll.verticalScrollBar().setValue(scroll))

    def _settings_changed(self, sec):
        if sec in ("player", "stream", "advanced", "*"):
            self.player.apply_runtime_settings()
        if sec in ("audio", "player", "*") and self.player.player:
            self.player.set_exclusive(bool(settings.get("audio", "exclusive")))
            self.player._apply_audio(force=True)
        if sec in ("shortcuts", "*"):
            self.player.install_shortcuts(self)
            self.player.bind_keys()
        if sec in ("downloads", "*"):
            self.dlm.apply_global()
        if sec in ("torrent", "*"):
            self.tm.apply_settings()
            self.page("torrent").update_debrid_button()

    # ---------- appunti ----------
    def _clipboard(self):
        t = QApplication.clipboard().text().strip()
        if not t or t == self._last_clip or not settings.get("downloads", "clipboard"):
            self._last_clip = t
            return
        self._last_clip = t
        if t.startswith(("http://", "https://")):
            # download con link scaduto: se copi un link nuovo dello stesso file, lo rinnova da solo
            from urllib.parse import urlparse, unquote
            fname = unquote(Path(urlparse(t).path).name).lower()
            for iid, it in list(self.dlm.items.items()):
                if it.get("expired") and fname and fname == (it.get("name") or "").lower():
                    self.toast("Link nuovo riconosciuto", it["name"] + " · riprendo il download", "info")
                    self.dlm.renew(iid, t)
                    return
        if getattr(self, "_awaiting_renew", False) and t.startswith(("http://", "https://")):
            # link scaduto in streaming: appena copi quello nuovo lo usa da solo
            self._renew_from_clipboard()
            return
        if QApplication.focusWidget() is not None and self.isActiveWindow():
            return  # copiato dentro NOVA
        if t.startswith("magnet:?"):
            m = re.search(r"dn=([^&]+)", t)
            from urllib.parse import unquote_plus
            name = unquote_plus(m.group(1)) if m else "Link magnet"
            self.toasts.show("Magnet copiato", name[:80],
                             [("Aggiungi", lambda: self.download(t)), ("Ignora", lambda: None)], "info", 8000)
        elif looks_like_url(t) and len(t) < 2000:
            self.toasts.show("Link copiato", t[:80],
                             [("Riproduci", lambda: self.play(t)), ("Scarica", lambda: self.download(t))],
                             "info", 8000)

    # ---------- drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasText():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            urls = [u.toString() for u in md.urls() if not u.isLocalFile()]
            media = [f for f in files if Path(f).suffix.lower() in VIDEO_EXT | AUDIO_EXT]
            for f in files:
                ext = Path(f).suffix.lower()
                if ext == ".torrent":
                    self.go("torrent")
                    self.page("torrent").add_torrent_file(f)
                elif ext in SUB_EXT:
                    self.player.drop_file(f)
            if media:
                self.go("player")
                self.player.play(media[0], extra=media[1:])
            for u in urls:
                self.play(u) if not u.startswith("magnet:") else self.download(u)
        elif md.hasText() and looks_like_url(md.text()):
            t = md.text().strip()
            self.download(t) if t.startswith("magnet:") else self.play(t)

    # ---------- tray e chiusura ----------
    def _setup_tray(self):
        self.tray = QSystemTrayIcon(icons.app_icon(), self)
        m = QMenu()
        m.addAction("Mostra NOVA", self.show_normal)
        m.addAction("Download", lambda: (self.show_normal(), self.go("downloads")))
        m.addSeparator()
        m.addAction("Esci", self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_normal() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.messageClicked.connect(self.show_normal)
        self.tray.show()

    def showEvent(self, e):
        super().showEvent(e)
        winutil.dark_titlebar(int(self.winId()), theme.dark)
        winutil.dark_background(int(self.winId()), theme.bg)
        winutil.caption_color(int(self.winId()), theme.sidebar)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "toasts"):
            self.toasts.layout()

    def closeEvent(self, e):
        if self._quitting:
            e.accept()
            return
        busy = self.dlm.stats()[0] + (self.tm.stats()[0] if self.tm.ses else 0)
        if settings.get("downloads", "tray_on_close") and busy and self.tray.isVisible():
            e.ignore()
            self.player.set_prop("pause", True)
            self.hide()
            self.tray.showMessage("NOVA è ancora attivo", "I download continuano in background.",
                                  icons.app_icon(), 4000)
            return
        e.accept()
        self.quit()

    def _save_geometry(self):
        if not self.player.is_fullscreen and not self.player.is_pip:
            settings.data["window"] = {"geometry": bytes(self.saveGeometry().toBase64()).decode()}
            settings.save()

    def quit(self):
        if not self._quitting:
            try:
                self._save_geometry()
            except Exception:
                pass
        if self._quitting:
            return
        self._quitting = True
        if self.player.cast_session:
            # chiude lo stream per la TV (ffmpeg compreso) e ferma la TV
            tv = self.player.casting
            self.player.stop_cast(resume_local=False)
            try:
                from . import lan
                lan.tv_command(tv, "Stop")
            except Exception:
                pass
        self.hide()
        self.tray.hide()
        winutil.wifi_streaming(False)
        self.player.shutdown()
        self.player.thumb_popup.close()
        try:
            self.player.controls.close()
        except Exception:
            pass
        self.dlm.shutdown()
        self.tm.shutdown()
        QApplication.instance().quit()
