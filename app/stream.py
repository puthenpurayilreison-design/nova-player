"""Modulo Stream: riproduzione da link (diretti, HLS, DASH, pagine supportate da yt-dlp)."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QApplication,
                               QScrollArea, QFrame)

from .config import settings, history
from .theme import theme
from .widgets import (PageHeader, Card, label, button, Segmented, IconButton, EmptyState,
                      animate_in)
from . import icons


def looks_like_url(s: str) -> bool:
    s = s.strip()
    return s.startswith(("http://", "https://", "ftp://", "magnet:")) and " " not in s


class LinkRow(QFrame):
    def __init__(self, item, on_play, on_remove):
        super().__init__()
        self.setObjectName("row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#row{{border-radius:10px;}} #row:hover{{background:{theme.surface2};}}")
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 9, 8, 9)
        ic = label("")
        ic.setPixmap(icons.pixmap("link", theme.text2, 18))
        h.addWidget(ic)
        v = QVBoxLayout()
        v.setSpacing(1)
        t = label(item["title"][:90])
        u = label(item["url"][:110], "faint")
        v.addWidget(t)
        v.addWidget(u)
        h.addLayout(v, 1)
        when = time.strftime("%d/%m %H:%M", time.localtime(item["time"]))
        h.addWidget(label(when, "faint"))
        x = IconButton("x", "Remove", 30, 14)
        x.clicked.connect(lambda: on_remove(item["url"]))
        h.addWidget(x)
        self.mousePressEvent = lambda e: on_play(item["url"]) if e.button() == Qt.LeftButton else None


class StreamPage(QWidget):
    play = Signal(str)
    download = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        m = theme.s(28)
        root.setContentsMargins(m, m - 4, m, m)
        root.setSpacing(theme.s(18))
        root.addWidget(PageHeader("Stream", "Paste a link and watch it right away, up to 4K, with an optimised buffer."))

        card = Card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(theme.s(20), theme.s(20), theme.s(20), theme.s(20))
        cv.setSpacing(theme.s(14))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setObjectName("bigInput")
        self.input.setPlaceholderText("https://…  (direct .mkv/.mp4 link, .m3u8, .mpd or video page)")
        self.input.returnPressed.connect(self._play)
        paste = IconButton("clipboard", "Paste", 46, 20)
        paste.clicked.connect(self._paste)
        row.addWidget(self.input, 1)
        row.addWidget(paste)
        cv.addLayout(row)

        q = QHBoxLayout()
        q.addWidget(label("Maximum quality", "muted"))
        cur = settings.get("stream", "max_height")
        self.quality = Segmented([("2160", "4K"), ("1440", "1440p"), ("1080", "1080p"), ("720", "720p")],
                                 str(cur if cur in (2160, 1440, 1080, 720) else 2160))
        self.quality.changed.connect(lambda v: settings.set("stream", "max_height", int(v)))
        q.addWidget(self.quality)
        q.addStretch()
        self.b_dl = button("Download", None, "download", self._download)
        self.b_play = button("Play", "primary", "play", self._play)
        q.addWidget(self.b_dl)
        q.addWidget(self.b_play)
        cv.addLayout(q)
        self.err = label("", wrap=True)
        self.err.setStyleSheet(f"color:{theme.danger};")
        self.err.hide()
        cv.addWidget(self.err)
        root.addWidget(card)

        tips = QHBoxLayout()
        tips.setSpacing(theme.s(12))
        for ic, t, d in (
            ("speed", "Smart buffer", "Up to 1 GB cache and 60 s read-ahead: no stutter even in 4K."),
            ("retry", "Automatic reconnection", "If the network drops, playback resumes by itself."),
            ("film", "HLS and DASH", "Picks the highest quality within the limit you set."),
        ):
            c = Card(flat=True)
            v = QVBoxLayout(c)
            v.setContentsMargins(16, 14, 16, 14)
            il = label("")
            il.setPixmap(icons.pixmap(ic, theme.accent, 20))
            v.addWidget(il)
            v.addWidget(label(t, "sectionTitle"))
            v.addWidget(label(d, "faint", wrap=True))
            tips.addWidget(c, 1)
        root.addLayout(tips)

        hh = QHBoxLayout()
        hh.addWidget(label("Recent links", "sectionTitle"))
        hh.addStretch()
        root.addLayout(hh)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_host = QWidget()
        self.list = QVBoxLayout(self.list_host)
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(2)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll, 1)
        history.listeners.append(self.refresh)
        self.refresh()

    def refresh(self):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        items = [i for i in history.items if i["kind"] == "link"][:40]
        if not items:
            self.list.addWidget(EmptyState("link", "No recent links",
                                           "The links you play will show up here, ready to reopen."))
        for n, it in enumerate(items):
            r = LinkRow(it, self.play.emit, history.remove)
            self.list.addWidget(r)
        self.list.addStretch()

    def _paste(self):
        t = QApplication.clipboard().text().strip()
        if t:
            self.input.setText(t)
            self.input.setFocus()

    def _check(self) -> str | None:
        u = self.input.text().strip()
        if not looks_like_url(u):
            self.err.setText("Enter a valid link starting with http://, https:// or ftp://")
            self.err.show()
            animate_in(self.err, 0, 6)
            return None
        self.err.hide()
        return u

    def _play(self):
        u = self._check()
        if u:
            if u.startswith("magnet:"):
                self.download.emit(u)
            else:
                self.play.emit(u)

    def _download(self):
        u = self._check()
        if u:
            self.download.emit(u)
