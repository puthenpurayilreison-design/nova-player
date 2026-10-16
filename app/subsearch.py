"""Cerca una frase nei sottotitoli (Ctrl+F) e salta a quel punto del film.

Legge i sottotitoli di testo: file esterni (.srt/.ass/.vtt) subito, quelli dentro il file (MKV/MP4)
estraendoli con ffmpeg in background a priorità bassa (il film non rallenta). I sottotitoli a immagine
(PGS/VobSub dei Blu-ray) non contengono testo e non si possono cercare.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import unicodedata

from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QLabel, QLayout

from . import icons
from .config import tool, human_time
from .theme import theme
from .widgets import label

TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text", "microdvd", "subviewer"}
_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d+:)?\d{2}:\d{2}[,.]\d{1,3}")
_TS_SHORT = re.compile(r"(\d{2}):(\d{2})[.](\d{3})\s*-->")
_TAGS = re.compile(r"\{[^}]*\}|<[^>]+>")
_CACHE: dict[tuple, list] = {}


def _clean(t: str) -> str:
    t = _TAGS.sub("", t).replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
    return re.sub(r"\s+", " ", t).strip()


def parse(text: str) -> list[tuple[float, str]]:
    """[(secondi, testo)] da SRT, VTT o ASS."""
    out: list[tuple[float, str]] = []
    if "[Events]" in text or text.lstrip().startswith("[Script Info]"):
        for line in text.splitlines():
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            m = re.match(r"(\d+):(\d+):(\d+)[.](\d+)", parts[1].strip())
            if not m:
                continue
            h, mi, s, cs = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s) + int(cs) / (10 ** len(cs))
            txt = _clean(parts[9])
            if txt:
                out.append((t, txt))
        out.sort()
        return out
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for b in blocks:
        lines = b.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                h, mi, s, ms = m.group(1), m.group(2), m.group(3), m.group(4)
                t = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
            else:
                m = _TS_SHORT.search(line)
                if not m:
                    continue
                t = int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000
            txt = _clean(" ".join(lines[i + 1:]))
            if txt:
                out.append((t, txt))
            break
    return out


def fold(s: str) -> str:
    """minuscolo e senza accenti: 'perché' trova anche 'perche'."""
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def search(cues: list[tuple[float, str]], query: str, limit: int = 200) -> list[tuple[float, str]]:
    q = fold(query.strip())
    if not q:
        return []
    words = q.split()
    res = [(t, x) for t, x in cues if all(w in fold(x) for w in words)]
    return res[:limit]


def _read(path: str) -> str:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


class Loader(QObject):
    done = Signal(object, str)     # (cues | None, messaggio)

    def load(self, src: str, track: dict):
        key = (src, track.get("id"), track.get("external-filename"))
        if key in _CACHE:
            self.done.emit(_CACHE[key], "")
            return
        threading.Thread(target=self._work, args=(src, track, key), daemon=True).start()

    def _work(self, src, track, key):
        try:
            ext = track.get("external-filename")
            if ext and os.path.isfile(ext):
                cues = parse(_read(ext))
            else:
                codec = (track.get("codec") or "").lower()
                if codec and codec not in TEXT_CODECS:
                    self.done.emit(None, "These subtitles are images (Blu-ray/DVD): they have no text to search.")
                    return
                if not os.path.isfile(src):
                    self.done.emit(None, "Search works with files on the PC and external subtitles (for links it would need to download the whole movie).")
                    return
                idx = track.get("ff-index")
                mp = f"0:{idx}" if idx is not None else "0:s:0"
                flags = 0
                if sys.platform == "win32":
                    flags = 0x08000000 | 0x00004000      # niente finestra, priorità sotto il normale
                r = subprocess.run([tool("ffmpeg"), "-v", "error", "-nostdin", "-i", src, "-map", mp,
                                    "-vn", "-an", "-dn", "-f", "srt", "-"],
                                   capture_output=True, timeout=600, creationflags=flags)
                cues = parse(r.stdout.decode("utf-8", "replace"))
            if not cues:
                self.done.emit(None, "No text found in these subtitles.")
                return
            _CACHE[key] = cues
            self.done.emit(cues, "")
        except Exception as e:
            self.done.emit(None, f"Can't read the subtitles: {e}")


class SubSearch(QFrame):
    """Pannello: scrivi una frase, scegli il punto, il film salta lì."""

    def __init__(self, page):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.page = page
        self.cues: list = []
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSizeConstraint(QLayout.SetFixedSize)      # il pannello segue sempre il contenuto
        box = QFrame()
        box.setObjectName("panel")
        box.setStyleSheet(f"#panel{{background:{theme.surface2};border:1px solid {theme.border};border-radius:14px;}}")
        outer.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)
        h = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("search", theme.text2, 18))
        h.addWidget(ic)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search a sentence in the subtitles…")
        self.edit.setClearButtonEnabled(True)
        h.addWidget(self.edit, 1)
        v.addLayout(h)
        self.info = label("Reading the subtitles…", "faint")
        v.addWidget(self.info)
        self.list = QListWidget()
        self.list.setStyleSheet(f"QListWidget{{background:transparent;border:none;}}"
                                f"QListWidget::item{{padding:7px 6px;border-radius:8px;}}"
                                f"QListWidget::item:selected{{background:{theme.surface3};color:{theme.text};}}"
                                f"QListWidget::item:hover{{background:{theme.surface3};}}")
        self.list.setWordWrap(True)
        self.list.hide()
        v.addWidget(self.list)
        box.setFixedWidth(560)
        self._t = QTimer(self, singleShot=True, interval=140)
        self._t.timeout.connect(self._run)
        self.edit.textChanged.connect(lambda: self._t.start())
        self.edit.returnPressed.connect(self._enter)
        self.list.itemActivated.connect(self._jump)
        self.list.itemClicked.connect(self._jump)
        self.loader = Loader(self)
        self.loader.done.connect(self._loaded)

    def start(self, src: str, track: dict | None):
        if not track:
            self.info.setText("This video has no subtitles. Add one (drop an .srt on the player) and try again.")
        else:
            self.loader.load(src, track)
        g = self.page.mapToGlobal(self.page.rect().topLeft())
        self.move(g.x() + (self.page.width() - 560) // 2, g.y() + 70)
        self.adjustSize()
        self.show()
        self.edit.setFocus()

    def _loaded(self, cues, msg):
        if cues is None:
            self.info.setText(msg)
            return
        self.cues = cues
        self.info.setText(f"{len(cues)} lines ready · Enter jumps to the first result")
        self._run()

    def _run(self):
        q = self.edit.text()
        self.list.clear()
        if not self.cues:
            return
        res = search(self.cues, q)
        if not q.strip():
            self.list.hide()
            self.info.setText(f"{len(self.cues)} lines ready · Enter jumps to the first result")
        else:
            self.info.setText(f"{len(res)} results" if res else "No results")
            for t, x in res:
                it = QListWidgetItem(f"{human_time(t)}    {x}")
                it.setData(Qt.UserRole, t)
                self.list.addItem(it)
            self.list.setVisible(bool(res))
            self.list.setFixedHeight(min(380, 40 * max(1, len(res)) + 8))
            if res:
                self.list.setCurrentRow(0)
        self.adjustSize()

    def _enter(self):
        it = self.list.currentItem()
        if it:
            self._jump(it)

    def _jump(self, it):
        t = float(it.data(Qt.UserRole))
        self.page.seek_to(max(0.0, t - 1.0), text=it.text().split("    ", 1)[-1])
        self.close()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up) and self.list.isVisible():
            self.list.keyPressEvent(e)
            return
        super().keyPressEvent(e)
