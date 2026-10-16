"""Modulo Player: libmpv incorporato, tracce, sottotitoli, 4K/HDR, seekbar con anteprima e buffer."""
from __future__ import annotations

import os
import re
import secrets
import urllib.parse
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import (Qt, QObject, Signal, QTimer, QRectF, QPointF, QPoint, QSize,
                            QVariantAnimation, QEasingCurve, QPropertyAnimation)
from PySide6.QtGui import (QPainter, QColor, QPen, QLinearGradient, QPixmap, QImage, QCursor,
                           QFont, QKeySequence, QShortcut, QGuiApplication)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSlider, QDialog,
                               QFileDialog, QStackedLayout, QSizePolicy, QScrollArea, QApplication)

from . import icons, winutil
from .config import (settings, history, resume_point, tool, DATA, cover_path, VIDEO_EXT, AUDIO_EXT, SUB_EXT,
                     human_time, human_speed)
from .theme import theme
from .widgets import IconButton, EmptyState, button, label, ease, CoverBackdrop, Segmented
from .turbo import TurboServer, link_expiry
from . import audio as snd

YTDL_HOSTS = ("youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "dailymotion.com", "instagram.com",
              "tiktok.com", "facebook.com", "fb.watch", "x.com", "twitter.com", "reddit.com", "bilibili.com")

# Rende trovabile libmpv-2.dll in bin/ prima di importare python-mpv.
# NOVA.exe: bin/ sta accanto all'exe (config.BIN), NON dentro _internal: per questo prima mancava sempre.
from .config import BIN as _BIN  # noqa: E402
mpv = None
MPV_ERROR = None


def load_mpv() -> bool:
    global mpv, MPV_ERROR
    if mpv is not None:
        return True
    for d in (_BIN, Path(sys.executable).resolve().parent, Path(__file__).resolve().parent.parent / "bin"):
        if d.exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(d))
                except OSError:
                    pass
    try:
        import importlib
        mpv = importlib.import_module("mpv")
        MPV_ERROR = None
        return True
    except Exception as e:  # libmpv mancante
        sys.modules.pop("mpv", None)
        mpv = None
        MPV_ERROR = str(e)
        return False


load_mpv()

LANGS = {
    "ita": "Italiano", "it": "Italiano", "eng": "Inglese", "en": "Inglese", "jpn": "Giapponese",
    "ja": "Giapponese", "spa": "Spagnolo", "es": "Spagnolo", "fre": "Francese", "fra": "Francese",
    "fr": "Francese", "ger": "Tedesco", "deu": "Tedesco", "de": "Tedesco", "por": "Portoghese",
    "pt": "Portoghese", "rus": "Russo", "ru": "Russo", "hin": "Hindi", "hi": "Hindi", "mal": "Malayalam",
    "ml": "Malayalam", "tam": "Tamil", "ta": "Tamil", "tel": "Telugu", "te": "Telugu", "kor": "Coreano",
    "ko": "Coreano", "chi": "Cinese", "zho": "Cinese", "zh": "Cinese", "ara": "Arabo", "ar": "Arabo",
    "und": "Sconosciuta",
}
CODECS = {"eac3": "E-AC3", "ac3": "AC3", "dts": "DTS", "truehd": "TrueHD", "aac": "AAC", "flac": "FLAC",
          "opus": "Opus", "mp3": "MP3", "vorbis": "Vorbis", "pcm_s16le": "PCM", "pcm_s24le": "PCM",
          "subrip": "SRT", "ass": "ASS", "hdmv_pgs_subtitle": "PGS", "dvd_subtitle": "VobSub",
          "webvtt": "WebVTT", "mov_text": "MP4 text", "hevc": "HEVC", "h264": "H.264", "av1": "AV1",
          "vp9": "VP9", "mpeg2video": "MPEG-2", "vc1": "VC-1"}


def L_ladder(level: int):
    from .lan import TV_LADDER
    return TV_LADDER[level]


def channels_label(n):
    return {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}.get(n, f"{n}ch" if n else "")


def track_label(t: dict) -> str:
    parts = []
    lang = t.get("lang")
    parts.append(LANGS.get(lang, lang.upper()) if lang else f"Traccia {t.get('id')}")
    if t.get("title") and t.get("title") != lang:
        parts[0] += f" — {t['title']}"
    codec = t.get("codec")
    if codec:
        parts.append(CODECS.get(codec, codec.upper()))
    if t.get("type") == "audio":
        ch = t.get("demux-channel-count")
        if ch:
            parts.append(channels_label(ch))
    if t.get("type") == "video":
        h = t.get("demux-h")
        if h:
            parts.insert(0, f"{h}p")
        br = t.get("demux-bitrate") or t.get("hls-bitrate")
        if br:
            parts.append(f"{br / 1e6:.1f} Mbps")
    if t.get("forced"):
        parts.append("Forzati")
    if t.get("default"):
        parts.append("Default")
    if t.get("external"):
        parts.append("Esterni")
    return " · ".join(parts)


def qt_to_mpv_key(seq: str) -> str:
    """Converte una scorciatoia Qt (es. 'Ctrl+Right') nel formato tasti di mpv."""
    if not seq:
        return ""
    names = {"Space": "SPACE", "Right": "RIGHT", "Left": "LEFT", "Up": "UP", "Down": "DOWN",
             "Return": "ENTER", "Enter": "KP_ENTER", "Esc": "ESC", "Escape": "ESC", "PgUp": "PGUP",
             "PgDown": "PGDWN", "Home": "HOME", "End": "END", "Del": "DEL", "Ins": "INS",
             "Backspace": "BS", "Tab": "TAB"}
    parts = seq.split("+") if seq != "+" else ["+"]
    if seq.endswith("++"):
        parts = seq[:-2].split("+") + ["+"]
    key = parts[-1]
    mods = [m for m in parts[:-1] if m]
    if key in names:
        key = names[key]
    elif len(key) == 1 and key.isalpha():
        key = key.lower() if "Shift" not in mods else key.upper()
        mods = [m for m in mods if m != "Shift"]
    return "+".join(mods + [key])


def refresh_mode() -> str:
    """off | fullscreen | always (compatibile con la vecchia impostazione sì/no)."""
    v = settings.data["player"].get("refresh_mode")
    if v in ("off", "fullscreen", "always"):
        return v
    return "fullscreen" if settings.data["player"].get("refresh_match", True) else "off"


def ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    if sys.platform == "win32":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS()
        m.l = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.total / 1024 ** 3
    return 8.0


def back_cache_mb() -> int:
    """Cache all'indietro: con il valore consigliato e tanta RAM, tieni minuti di video per tornare indietro subito."""
    v = int(settings.get("stream", "back_cache_mb"))
    if v != 256:
        return v
    gb = ram_gb()
    return 1536 if gb >= 14 else 768 if gb >= 7 else 256


def fwd_cache_mb() -> int:
    """Cache in avanti: con 16 GB di RAM tiene ~3 minuti di un 4K da 80 Mbps (copre i cali del Wi-Fi)."""
    v = int(settings.get("stream", "cache_mb"))
    if v != 1024:
        return v
    gb = ram_gb()
    return 2048 if gb >= 14 else 1024


def readahead_s() -> int:
    v = int(settings.get("stream", "readahead_s"))
    return 180 if v == 60 and ram_gb() >= 14 else v


class MpvBridge(QObject):
    """Porta eventi dal thread di mpv al thread della UI."""
    tracks = Signal(list)
    paused = Signal(bool)
    idle = Signal(bool)
    loaded = Signal()
    ended = Signal(int, int)
    key = Signal(str)
    chapters = Signal(list)
    title = Signal(str)
    cover = Signal(str, str)
    audio_params = Signal(object)
    eof = Signal(bool)
    cast_state = Signal(dict, str)
    repaired = Signal(bool)
    intro_found = Signal(str, str, list)
    sync_done = Signal(dict)
    devices = Signal(list)


class MpvWidget(QWidget):
    """Superficie video nativa per libmpv."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(Qt.WA_NativeWindow)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setStyleSheet("background:black;")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(160, 90)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)


class ThumbWorker(QObject):
    """Genera miniature di anteprima con ffmpeg (solo file locali), con cache e debounce."""
    ready = Signal(float, QImage)

    def __init__(self):
        super().__init__()
        self.path = None
        self.cache: dict = {}
        self._want = None
        self._lock = threading.Lock()
        self._ev = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def set_file(self, path):
        self.path = path if path and os.path.isfile(path) else None
        self.cache.clear()

    def request(self, t: float):
        if not self.path:
            return
        key = int(t // 2) * 2
        if key in self.cache:
            self.ready.emit(t, self.cache[key])
            return
        with self._lock:
            self._want = (self.path, key, t)
        self._ev.set()

    def _loop(self):
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        while True:
            self._ev.wait()
            time.sleep(0.09)
            with self._lock:
                job, self._want = self._want, None
                self._ev.clear()
            if not job:
                continue
            path, key, t = job
            try:
                out = subprocess.run(
                    [tool("ffmpeg"), "-v", "quiet", "-hwaccel", "auto", "-ss", str(key), "-i", path,
                     "-frames:v", "1", "-vf", "scale=256:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                    capture_output=True, timeout=6, creationflags=flags).stdout
                img = QImage.fromData(out, "JPG")
                if not img.isNull() and path == self.path:
                    self.cache[key] = img
                    self.ready.emit(t, img)
            except Exception:
                pass


class ThumbPopup(QWidget):
    """Anteprima (miniatura + tempo) sopra la seekbar; finestra top-level per stare sopra al video."""

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.img: QImage | None = None
        self.text = ""
        self.resize(140, 34)

    def set(self, text, img=None):
        self.text = text
        self.img = img
        self.resize(QSize(264, int(264 * img.height() / max(1, img.width())) + 36) if img else QSize(90, 34))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(18, 18, 22, 235))
        p.drawRoundedRect(r, 10, 10)
        y = 4
        if self.img:
            ir = QRectF(4, 4, r.width() - 6, r.height() - 38)
            p.save()
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.addRoundedRect(ir, 7, 7)
            p.setClipPath(path)
            p.drawImage(ir, self.img)
            p.restore()
            y = ir.bottom() + 2
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(0, y, r.width(), r.height() - y), Qt.AlignCenter, self.text)


class SeekBar(QWidget):
    """Barra di avanzamento con buffer visibile, capitoli, hover e anteprima."""
    seek = Signal(float)
    hover = Signal(float, QPoint)
    leave = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.duration = 0.0
        self.pos_ = 0.0
        self.buffered = 0.0
        self.chapters: list[float] = []
        self.ab = (None, None)
        self.on_dark = False
        self.accent = None
        self._hx = -1
        self._grow = 0.0
        self._drag = False
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0)
        self._a.valueChanged.connect(lambda v: (setattr(self, "_grow", v), self.update()))
        self._base, self._base_t, self._rate = 0.0, 0.0, 0.0
        self._smooth = QTimer(self, interval=16, timerType=Qt.PreciseTimer)
        self._smooth.timeout.connect(self._interp)

    def set_state(self, pos, dur, buffered, rate=0.0):
        """Riceve lo stato reale (4 volte al secondo) e lo interpola a 60 fps tra un campione e l'altro."""
        if self._drag:
            return
        self.duration, self.buffered = dur or 0, buffered or 0
        self._base, self._base_t, self._rate = pos or 0, time.perf_counter(), rate
        self.pos_ = self._base
        if rate and theme.motion and self.isVisible():
            if not self._smooth.isActive():
                self._smooth.start()
        else:
            self._smooth.stop()
        self.update()

    def _interp(self):
        if self._drag or not self._rate:
            return
        self.pos_ = min(self.duration or 0, self._base + (time.perf_counter() - self._base_t) * self._rate)
        self.update()

    def _t(self, x):
        return max(0.0, min(1.0, x / max(1, self.width()))) * self.duration

    def enterEvent(self, e):
        self._a.setDuration(max(1, theme.dur(150)))
        self._a.setDirection(QVariantAnimation.Forward)
        self._a.start()

    def leaveEvent(self, e):
        self._hx = -1
        self._a.setDirection(QVariantAnimation.Backward)
        self._a.start()
        self.leave.emit()
        self.update()

    def mouseMoveEvent(self, e):
        self._hx = e.position().x()
        if self.duration:
            self.hover.emit(self._t(self._hx), self.mapToGlobal(QPoint(int(self._hx), 0)))
        if self._drag:
            self.pos_ = self._t(self._hx)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.duration:
            self._drag = True
            self.pos_ = self._t(e.position().x())
            self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.seek.emit(self._t(e.position().x()))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = 4 + 3 * self._grow
        y = (self.height() - h) / 2
        base = QColor(255, 255, 255, 50) if self.on_dark else QColor(theme.surface3)
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(QRectF(0, y, w, h), h / 2, h / 2)
        if self.duration > 0:
            bx = min(1.0, self.buffered / self.duration) * w
            px = min(1.0, self.pos_ / self.duration) * w
            bc = QColor(255, 255, 255, 95) if self.on_dark else QColor(theme.text3)
            if bx > px:
                p.setBrush(bc)
                p.drawRoundedRect(QRectF(0, y, bx, h), h / 2, h / 2)
            a, b = self.ab
            if a is not None:
                ax = a / self.duration * w
                bxx = (b / self.duration * w) if b is not None else ax + 2
                c = QColor(theme.warning)
                c.setAlpha(120)
                p.setBrush(c)
                p.drawRect(QRectF(ax, y - 2, max(2, bxx - ax), h + 4))
            g = QLinearGradient(0, 0, px, 0)
            ac = QColor(self.accent or theme.accent)
            g.setColorAt(0, ac.lighter(130))
            g.setColorAt(1, ac)
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, y, max(h, px), h), h / 2, h / 2)
            # capitoli
            p.setBrush(QColor(0, 0, 0, 160) if self.on_dark else QColor(theme.bg))
            for c in self.chapters:
                if 0 < c < self.duration:
                    cx = c / self.duration * w
                    p.drawRect(QRectF(cx - 1, y, 2, h))
            if self._hx >= 0:
                p.setBrush(QColor(255, 255, 255, 120))
                p.drawRect(QRectF(self._hx - 0.75, y - 2, 1.5, h + 4))
            r = 5 + 3 * self._grow
            p.setBrush(QColor("white"))
            p.drawEllipse(QPointF(px, self.height() / 2), r * self._grow, r * self._grow)


class TrackPanel(QFrame):
    """Pannello popup per tracce audio/sottotitoli/video con regolazioni."""

    def __init__(self, page: "PlayerPage", kind: str):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.page = page
        self.kind = kind
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame()
        box.setObjectName("panel")
        box.setStyleSheet(f"#panel{{background:{theme.surface2};border:1px solid {theme.border};border-radius:14px;}}")
        outer.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(10, 12, 10, 10)
        v.setSpacing(4)
        titles = {"audio": "Audio", "sub": "Sottotitoli", "video": "Qualità video", "speed": "Velocità",
                  "device": "Uscita audio"}
        t = label(titles[kind], "sectionTitle")
        t.setContentsMargins(8, 0, 0, 4)
        v.addWidget(t)
        self.v = v
        if kind == "speed":
            self._speed()
        elif kind == "device":
            self._devices()
        else:
            self._tracks()
        self.setMinimumWidth(320)

    def _head(self, text):
        h = label(text.upper(), "faint")
        h.setStyleSheet("font-size:11px;letter-spacing:1px;font-weight:600;")
        h.setContentsMargins(8, 8, 0, 2)
        self.v.addWidget(h)

    def _row(self, text, checked, cb, sub="", tip=""):
        b = QFrame()
        if tip:
            b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.setObjectName("row")
        b.setStyleSheet(f"#row{{border-radius:8px;}} #row:hover{{background:{theme.surface3};}}")
        h = QHBoxLayout(b)
        h.setContentsMargins(8, 7, 10, 7)
        ic = QLabel()
        ic.setFixedSize(18, 18)
        if checked:
            ic.setPixmap(icons.pixmap("check", theme.accent, 18))
        h.addWidget(ic)
        l = label(text)
        if checked:
            l.setStyleSheet(f"color:{theme.accent};font-weight:600;")
        h.addWidget(l, 1)
        if sub:
            h.addWidget(label(sub, "faint"))
        b.mousePressEvent = lambda e: (cb(), self.close())
        self.v.addWidget(b)

    def _stepper(self, name, value_fn, minus, plus, reset, fmt):
        row = QHBoxLayout()
        row.setContentsMargins(8, 4, 4, 0)
        row.addWidget(label(name, "muted"), 1)
        val = label(fmt(value_fn()))
        val.setMinimumWidth(56)
        val.setAlignment(Qt.AlignCenter)
        bm = IconButton("down", "Diminuisci", 28, 14)
        bp = IconButton("up", "Aumenta", 28, 14)
        br = IconButton("retry", "Reimposta", 28, 14)
        bm.clicked.connect(lambda: (minus(), val.setText(fmt(value_fn()))))
        bp.clicked.connect(lambda: (plus(), val.setText(fmt(value_fn()))))
        br.clicked.connect(lambda: (reset(), val.setText(fmt(value_fn()))))
        for w in (bm, val, bp, br):
            row.addWidget(w)
        self.v.addLayout(row)

    def _tracks(self):
        pl = self.page.player
        typ = {"audio": "audio", "sub": "sub", "video": "video"}[self.kind]
        tracks = [t for t in self.page.track_list if t.get("type") == typ]
        prop = {"audio": "aid", "sub": "sid", "video": "vid"}[self.kind]
        if self.kind == "sub":
            none_sel = not any(t.get("selected") for t in tracks)
            self._row("Disattivati", none_sel, lambda: self.page.set_prop("sid", "no"))
        if not tracks and self.kind != "sub":
            self.v.addWidget(label("  Nessuna traccia", "faint"))
        for t in tracks:
            self._row(track_label(t), bool(t.get("selected")),
                      lambda tid=t["id"]: self.page.set_prop(prop, tid))
        if self.kind == "video":
            return
        self.v.addSpacing(6)
        if self.kind == "audio":
            pg = self.page
            self._head("Suono")
            cur = pg.audio_profile()
            eff = pg.effective_profile()
            for k, name, desc in snd.PROFILES:
                sub = f"ora: {snd.PROFILE_NAMES.get(eff, eff)}" if k == "auto" else ""
                self._row(name, k == cur, lambda k=k: pg.set_audio_profile(k), sub, tip=desc)
            self._head("Uscita")
            self._row(pg.device_desc(), False, lambda: QTimer.singleShot(
                0, lambda: TrackPanel(pg, "device").popup_at(pg.controls.b_audio)), "cambia ›")

            def delay(d):
                pg.add_prop("audio-delay", d) if d else pg.set_prop("audio-delay", 0)
                pg.save_device_delay()
            self._stepper("Ritardo audio (ricordato per questa uscita)", lambda: pg.get_prop("audio-delay", 0),
                          lambda: delay(-0.05), lambda: delay(0.05), lambda: delay(0), lambda v: f"{v:+.2f}s")
        else:
            self._stepper("Ritardo sottotitoli", lambda: self.page.get_prop("sub-delay", 0),
                          lambda: self.page.add_prop("sub-delay", -0.1),
                          lambda: self.page.add_prop("sub-delay", 0.1),
                          lambda: self.page.set_prop("sub-delay", 0), lambda v: f"{v:+.1f}s")
            self._stepper("Dimensione", lambda: self.page.get_prop("sub-scale", 1),
                          lambda: self.page.add_prop("sub-scale", -0.1),
                          lambda: self.page.add_prop("sub-scale", 0.1),
                          lambda: self.page.set_prop("sub-scale", 1.0), lambda v: f"{v * 100:.0f}%")
            self._stepper("Posizione", lambda: self.page.get_prop("sub-pos", 100),
                          lambda: self.page.add_prop("sub-pos", -2),
                          lambda: self.page.add_prop("sub-pos", 2),
                          lambda: self.page.set_prop("sub-pos", 100), lambda v: f"{v:.0f}%")
            b = button("Carica sottotitoli esterni…", None, "file")
            b.clicked.connect(lambda: (self.close(), self.page.load_external_sub()))
            self.v.addSpacing(4)
            self.v.addWidget(b)
            row = QHBoxLayout()
            b2 = button("Sincronizza da solo", None, "retry")
            b2.setToolTip("Ascolta il film e mette i sottotitoli a tempo (anche se sono per un'altra versione).")
            b2.clicked.connect(lambda: (self.close(), self.page.sync_subs()))
            row.addWidget(b2)
            self.v.addLayout(row)

    def _devices(self):
        pg = self.page
        cur = pg.device_name()
        devs = pg._device_list or [{"name": "auto", "description": "Predefinita di Windows"}]
        for d in devs:
            name = d.get("name", "")
            desc = "Predefinita di Windows" if name == "auto" else (d.get("description") or name)
            sub = "FxSound" if snd.is_fxsound(desc) else ("diretta" if name != "auto" else "")
            self._row(desc, name == cur, lambda n=name: pg.set_audio_device(n), sub)
        note = label("Scegli l'uscita diretta (non FxSound) per il suono originale del film. "
                     "Profilo e ritardo vengono ricordati per ogni uscita.", "faint")
        note.setWordWrap(True)
        note.setContentsMargins(8, 6, 8, 0)
        note.setMaximumWidth(340)
        self.v.addWidget(note)

    def _speed(self):
        cur = self.page.get_prop("speed", 1.0)
        for s in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0):
            self._row("Normale" if s == 1 else f"{s:g}x", abs(cur - s) < 0.01,
                      lambda s=s: self.page.set_prop("speed", s))

    def popup_at(self, w: QWidget):
        self.adjustSize()
        g = w.mapToGlobal(QPoint(w.width() // 2, 0))
        x = g.x() - self.width() // 2
        y = g.y() - self.height() - 10
        scr = w.screen().availableGeometry()
        x = max(scr.left() + 8, min(x, scr.right() - self.width() - 8))
        y = max(scr.top() + 8, y)
        self.move(x, y + (12 if theme.motion else 0))
        self.show()
        if theme.motion:
            self.setWindowOpacity(0.0)
            a = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=theme.dur(180))
            a.setEasingCurve(ease())
            a.valueChanged.connect(lambda v: (self.setWindowOpacity(v), self.move(x, int(y + 12 * (1 - v)))))
            a.start()


class CastPanel(TrackPanel):
    """Trasmetti alla TV (DLNA) e telecomando dal telefono."""
    found = Signal(list)

    def __init__(self, page):
        QFrame.__init__(self, None, Qt.Popup | Qt.FramelessWindowHint)
        self.page = page
        self.kind = "cast"
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame()
        box.setObjectName("panel")
        box.setStyleSheet(f"#panel{{background:{theme.surface2};border:1px solid {theme.border};border-radius:14px;}}")
        outer.addWidget(box)
        self.v = QVBoxLayout(box)
        self.v.setContentsMargins(10, 12, 10, 10)
        self.v.setSpacing(4)
        t = label("Trasmetti", "sectionTitle")
        t.setContentsMargins(8, 0, 0, 4)
        self.v.addWidget(t)
        self._head("TV in casa")
        self.wait = label("  Cerco le TV sulla rete…", "faint")
        self.v.addWidget(self.wait)
        self.tv_box = QVBoxLayout()
        self.v.addLayout(self.tv_box)
        if page.casting:
            self._row(f"Ferma la TV ({page.casting['name']})", False, page.stop_cast)
            self._row("Ricollega la TV (stesso punto)", False,
                      lambda: page.cast_pc(page.casting) if page.cast_session else page.cast_to(page.casting))
        self._head("Telefono")
        self._row("Telecomando dal telefono", False, page.show_remote, "QR ›")
        self.setMinimumWidth(330)
        self.found.connect(self._show)
        from . import lan
        threading.Thread(target=lambda: self._emit(lan.discover(2.5)), daemon=True).start()

    def _emit(self, tvs):
        try:
            self.found.emit(tvs)
        except RuntimeError:
            pass

    def _show(self, tvs):
        self.wait.setText("  Nessuna TV trovata: accendila e collegala allo stesso Wi-Fi." if not tvs else "")
        self.wait.setVisible(not tvs)
        v0 = self.v
        self.v = self.tv_box
        for tv in tvs:
            self._row(tv["name"], bool(self.page.casting and self.page.casting.get("control") == tv["control"]),
                      lambda tv=tv: self.page.cast_pc(tv), "il PC fa tutto",
                      "Il PC prepara il film (sottotitoli inclusi) e la TV lo mostra soltanto: niente blocchi "
                      "anche col Wi-Fi debole. Salti e pausa da NOVA o dal telefono.")
        if tvs:
            self._head("Qualità sulla TV")
            cur = settings.get("player", "tv_quality") or "auto"
            for k, name, sub in (("auto", "Automatica", "si adatta al Wi-Fi"),
                                 ("high", "Alta", "1080p · Wi-Fi forte"),
                                 ("medium", "Media", "1080p leggero"),
                                 ("low", "Wi-Fi debole", "720p"),
                                 ("slow", "Wi-Fi molto lento", "720p leggero")):
                self._row(name, k == cur, lambda k=k: self.page.set_tv_quality(k), sub)
            for tv in tvs:
                self._row(f"{tv['name']} · originale", False, lambda tv=tv: self.page.cast_to(tv),
                          "senza ricomprimere", "Manda il file così com'è: massima qualità, ma serve un Wi-Fi forte "
                          "e i salti si fanno dal telecomando della TV.")
        self.v = v0
        self.adjustSize()


class Controls(QWidget):
    """Barra controlli: nella finestra è sotto il video, a schermo intero diventa un overlay sfumato."""

    def __init__(self, page: "PlayerPage"):
        super().__init__()
        self.page = page
        self.overlay = False
        self.setAttribute(Qt.WA_StyledBackground, False)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 8, 18, 12)
        v.setSpacing(4)
        self.seek = SeekBar()
        tr = QHBoxLayout()
        self.t_pos = label("00:00")
        self.t_dur = label("00:00")
        tr.addWidget(self.seek, 1)
        v.addLayout(tr)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.b_prev = IconButton("prev", "Precedente", 36, 18)
        self.b_play = IconButton("play", "Play/Pausa (Spazio)", 46, 22, filled=True)
        self.b_next = IconButton("next", "Successivo", 36, 18)
        self.b_vol = IconButton("volume", "Muto (M)", 36, 20)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 150)
        self.vol.setFixedWidth(96)
        self.vol.setValue(settings.get("player", "volume"))
        self.time = label("00:00 / 00:00")
        self.net = label("", "faint")
        self.b_skip = button("Salta intro  ›", "primary")
        self.b_skip.hide()
        self.b_cam = button("Boost", "chip")
        self.b_cam.setCheckable(True)
        self.b_cam.setToolTip("Migliora i video di bassa qualità (T): meno blocchi e grana, immagine più nitida, voci più chiare")
        self.b_cam.setFixedHeight(30)
        self.b_speed = IconButton("speed", "Velocità", 36, 19)
        self.b_quality = IconButton("film", "Qualità video", 36, 19)
        self.b_audio = IconButton("audio", "Tracce audio", 36, 19)
        self.b_sub = IconButton("subtitles", "Sottotitoli", 36, 19)
        self.b_loop = IconButton("loop", "Loop A-B (L)", 36, 19)
        self.b_stats = IconButton("info", "Statistiche (I)", 36, 19)
        self.b_dl = IconButton("download", "Scarica questo video", 36, 19)
        self.b_pip = IconButton("pip", "Picture-in-picture (P)", 36, 19)
        self.b_cast = IconButton("cast", "Trasmetti alla TV · Telecomando dal telefono", 36, 19)
        self.b_fs = IconButton("fullscreen", "Schermo intero (F)", 36, 19)
        for b in (self.b_prev, self.b_play, self.b_next, self.b_vol):
            row.addWidget(b)
        row.addWidget(self.vol)
        row.addSpacing(10)
        row.addWidget(self.time)
        row.addSpacing(10)
        row.addWidget(self.net)
        row.addStretch()
        row.addWidget(self.b_skip)
        row.addSpacing(8)
        row.addWidget(self.b_cam)
        row.addSpacing(6)
        for b in (self.b_dl, self.b_speed, self.b_quality, self.b_audio, self.b_sub,
                  self.b_loop, self.b_stats, self.b_cast, self.b_pip, self.b_fs):
            row.addWidget(b)
        v.addLayout(row)
        self.buttons = [self.b_prev, self.b_play, self.b_next, self.b_vol, self.b_speed, self.b_quality,
                        self.b_audio, self.b_sub, self.b_loop, self.b_stats, self.b_dl,
                        self.b_cast, self.b_pip, self.b_fs]

    def set_overlay(self, on: bool):
        self.overlay = on
        self.seek.on_dark = on
        for b in self.buttons:
            b.on_dark = on
            b.update()
        col = "white" if on else theme.text
        self.time.setStyleSheet(f"color:{col};")
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        if self.overlay:
            g = QLinearGradient(0, 0, 0, self.height())
            g.setColorAt(0, QColor(0, 0, 0, 0))
            g.setColorAt(0.45, QColor(0, 0, 0, 150))
            g.setColorAt(1, QColor(0, 0, 0, 215))
            p.fillRect(self.rect(), g)
        else:
            p.fillRect(self.rect(), QColor(theme.surface))
            p.setPen(QColor(theme.border))
            p.drawLine(0, 0, self.width(), 0)


class _HeroProxy(QObject):
    """Adatta la Hero della Home al player (stesso aspetto, stessi pulsanti)."""
    play_item = Signal(dict)

    def __init__(self, page):
        super().__init__(page)
        self.play_item.connect(page.resume_item.emit)


class PlayerPage(QWidget):
    resume_item = Signal(dict)
    request_fullscreen = Signal(bool)
    request_pip = Signal(bool)
    request_download = Signal(str)
    status = Signal(str, str)  # titolo, tipo
    link_expired = Signal(str)  # id sorgente Stream Turbo
    episode_ended = Signal(str)  # chiave cronologia del video appena finito
    request_cinema = Signal(bool)
    request_palette = Signal()
    request_refresh = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.bridge = MpvBridge()
        self.track_list: list = []
        self.current_url = ""
        self.current_key = ""
        self.turbo = TurboServer()
        self.turbo.ready.connect(self._turbo_ready)
        self.turbo.state.connect(self._turbo_state)
        self.turbo_sid = None
        self._pending = None
        self._refresh_switched = None   # (monitor, Hz originali)
        self.is_fullscreen = False
        self.is_pip = False
        self.is_cinema = False
        self.lan = None
        self.casting = None
        self.cast_session = None
        self.theatre = False
        self._cam_vf = False
        self._sleep_at = None
        self.intro = None        # (inizio, fine) della sigla
        self.credits = None
        self._intro_skipped = False
        self._jobs = []
        self._last_move = time.time()
        self._last_cursor = QPoint()
        self._ctrl_visible = True
        self._last_hist = 0
        self.thumbs = ThumbWorker()
        self.thumb_popup = ThumbPopup()
        self.thumbs.ready.connect(self._thumb_ready)
        self._hover_t = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # barra titolo
        self.top = self.header = CoverBackdrop()
        th = QHBoxLayout(self.top)
        th.setContentsMargins(24, 18, 18, 12)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.title = label("Player", "pageTitle")
        self.subtitle = label("Apri un file o trascinalo qui", "pageSub")
        tv.addWidget(self.title)
        tv.addWidget(self.subtitle)
        th.addLayout(tv, 1)
        self.b_open = button("Apri file", "primary", "folder", self.open_files)
        th.addWidget(self.b_open, 0, Qt.AlignVCenter)
        root.addWidget(self.top)

        # area video con stato vuoto
        self.video_host = QWidget()
        self.video_stack = QStackedLayout(self.video_host)
        self.empty = QWidget()
        self._empty_lay = QVBoxLayout(self.empty)
        self._empty_lay.setContentsMargins(28, 8, 28, 28)
        self._build_empty()
        self.video = MpvWidget()
        self.video_stack.addWidget(self.empty)
        self.video_stack.addWidget(self.video)
        root.addWidget(self.video_host, 1)

        self.controls = Controls(self)
        root.addWidget(self.controls)
        self._root = root
        self.loading = label("", "faint")

        c = self.controls
        c.b_play.clicked.connect(self.toggle_pause)
        c.b_prev.clicked.connect(lambda: self.cmd("playlist-prev"))
        c.b_next.clicked.connect(lambda: self.cmd("playlist-next"))
        c.b_vol.clicked.connect(self.toggle_mute)
        c.vol.valueChanged.connect(self._vol)
        c.b_speed.clicked.connect(lambda: TrackPanel(self, "speed").popup_at(c.b_speed))
        c.b_quality.clicked.connect(lambda: TrackPanel(self, "video").popup_at(c.b_quality))
        c.b_audio.clicked.connect(lambda: TrackPanel(self, "audio").popup_at(c.b_audio))
        c.b_sub.clicked.connect(lambda: TrackPanel(self, "sub").popup_at(c.b_sub))
        c.b_loop.clicked.connect(self.ab_loop)
        c.b_stats.clicked.connect(self.toggle_stats)
        c.b_pip.clicked.connect(lambda: self.request_pip.emit(not self.is_pip))
        c.b_cast.clicked.connect(lambda: CastPanel(self).popup_at(c.b_cast))
        c.b_skip.clicked.connect(self._skip_clicked)
        c.b_cam.clicked.connect(lambda: self.set_theatre(not self.theatre))
        c.b_fs.clicked.connect(lambda: self.request_fullscreen.emit(not self.is_fullscreen))
        c.b_dl.clicked.connect(self._download_current)
        c.seek.seek.connect(self.seek_abs)
        c.seek.hover.connect(self._seek_hover)
        c.seek.leave.connect(self.thumb_popup.hide)

        b = self.bridge
        b.tracks.connect(self._on_tracks)
        b.paused.connect(self._on_pause)
        b.idle.connect(self._on_idle)
        b.loaded.connect(self._on_loaded)
        b.ended.connect(self._on_end)
        b.key.connect(self._on_key)
        b.chapters.connect(lambda ch: setattr(c.seek, "chapters", ch))
        b.title.connect(self._on_title)
        b.cover.connect(self._on_cover)
        b.audio_params.connect(self._on_audio_params)
        b.devices.connect(self._on_devices)
        b.cast_state.connect(self._cast_state)
        b.repaired.connect(self._repaired)
        b.intro_found.connect(self._intro_found)
        b.sync_done.connect(self._sync_done)
        b.eof.connect(lambda on: on and self.current_key and self.episode_ended.emit(self.current_key))
        self._audio_in = {}
        self._af = None
        self._device_list = []
        self._film_restored = False

        self.timer = QTimer(self, interval=250)
        self.timer.timeout.connect(self._poll)
        self.hide_timer = QTimer(self, interval=200)
        self.hide_timer.timeout.connect(self._autohide)
        self.setAcceptDrops(False)
        self._update_dl_button()

    def _build_empty(self):
        """Senza video: anteprima del film da riprendere (copertina + 'Riprendi'), altrimenti invito ad aprire."""
        from .home import Hero, is_unfinished
        lay = self._empty_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        cont = [i for i in history.items if is_unfinished(i)]
        if cont:
            proxy = _HeroProxy(self)
            lay.addWidget(Hero(cont[0], proxy))
            hint = label("Oppure trascina qui un file, o aprilo da Esplora file.", "faint")
            hint.setAlignment(Qt.AlignCenter)
            lay.addSpacing(10)
            lay.addWidget(hint)
            lay.addStretch()
        else:
            lay.addWidget(EmptyState("player", "Nessun video in riproduzione",
                                     "Trascina un file qui, aprilo da Esplora file o incolla un link nella sezione "
                                     "Stream. Supporta MKV, MP4, AVI, MOV, WEBM, TS, HEVC, AV1, DTS, TrueHD e altro.",
                                     button("Apri file", "primary", "folder", self.open_files)))

    def showEvent(self, e):
        idle = self.video_stack.currentWidget() is self.empty
        if idle:
            self._build_empty()
        if not self.is_fullscreen and not self.is_pip:
            self.controls.setVisible(not idle)

    # ---------- mpv ----------
    def prewarm(self):
        """Prepara mpv in anticipo (pochi secondi dopo l'avvio, in silenzio): il primo film parte subito."""
        if self.player or (mpv is None and not load_mpv()):
            return
        cur = self.video_stack.currentWidget()
        try:
            self.ensure_player()
        except Exception as e:
            self._log("warn", "prewarm", f"{e}\n")
        if cur is not None and self.get_prop("idle-active", True):
            self.video_stack.setCurrentWidget(cur)

    def ensure_player(self) -> bool:
        if self.player:
            return True
        if mpv is None and not load_mpv():
            self._repair_components()
            return False
        self.video_stack.setCurrentWidget(self.video)
        QApplication.processEvents()
        winutil.dark_background(int(self.video.winId()), "#000000")
        ps, ss = settings.data["player"], settings.data["stream"]
        opts = dict(
            wid=str(int(self.video.winId())),
            vo=os.environ.get("NOVA_VO", "gpu-next,gpu"),
            hwdec="auto-safe" if ps["hwdec"] else "no",
            keep_open="yes",
            idle="yes",
            osc=False,
            osd_bar=False,
            osd_level=1,
            osd_font_size=28,
            input_default_bindings=False,
            input_vo_keyboard=True,
            cursor_autohide=1000,
            volume_max=150,
            volume=ps["volume"],
            audio_device=settings.get("audio", "device") or "auto",
            audio_exclusive="yes" if settings.get("audio", "exclusive") else "no",
            target_colorspace_hint="yes",
            ytdl=True,
            watch_later_directory=str(DATA / "watch_later"),
            resume_playback="no",
            alang=ps["audio_lang"],
            slang=ps["sub_lang"],
            sub_auto="fuzzy",
            sub_font_size=ps["sub_size"],
            sub_color=ps["sub_color"],
            sub_border_size=2.5,
            sub_shadow_offset=1,
            demuxer_mkv_subtitle_preroll="yes",
            stream_buffer_size="4MiB",          # letture di rete più grandi: meno attese sui link veloci
            cache="yes",
            demuxer_max_bytes=f"{fwd_cache_mb()}MiB",
            demuxer_max_back_bytes=f"{int(ss['back_cache_mb'])}MiB",
            script_opts=f"ytdl_hook-ytdl_path={tool('yt-dlp')}",
            ytdl_format=(f"bestvideo[height<=?{ss['max_height']}]+bestaudio/"
                         f"best[height<=?{ss['max_height']}]/best"),
        )
        if sys.platform == "win32":
            opts["gpu_api"] = "d3d11"
            gpu = winutil.discrete_gpu_name()
            if gpu:
                opts["d3d11_adapter"] = gpu  # forza la GPU dedicata (portatili con grafica ibrida)
        try:
            self.player = mpv.MPV(log_handler=self._log, loglevel="warn", **opts)
        except Exception as e:
            self.status.emit(f"Impossibile avviare mpv: {e}", "err")
            return False
        self.apply_runtime_settings()
        self.set_prop("audio-delay", float(self._dev_mem().get("delay", 0.0)))
        p = self.player
        p.observe_property("track-list", lambda n, v: self.bridge.tracks.emit(v or []))
        p.observe_property("pause", lambda n, v: self.bridge.paused.emit(bool(v)))
        p.observe_property("idle-active", lambda n, v: self.bridge.idle.emit(bool(v)))
        p.observe_property("chapter-list", lambda n, v: self.bridge.chapters.emit([c.get("time", 0) for c in (v or [])]))
        p.observe_property("media-title", lambda n, v: self.bridge.title.emit(v or ""))
        p.observe_property("audio-params", lambda n, v: self.bridge.audio_params.emit(v or {}))
        p.observe_property("eof-reached", lambda n, v: self.bridge.eof.emit(bool(v)))
        p.observe_property("audio-device-list", lambda n, v: self.bridge.devices.emit(v or []))

        @p.event_callback("file-loaded")
        def _fl(ev):
            self.bridge.loaded.emit()

        @p.event_callback("end-file")
        def _ef(ev):
            try:
                d = ev.data
                self.bridge.ended.emit(int(d.reason), int(d.error))
            except Exception:
                pass
        self._fl, self._ef = _fl, _ef
        self.bind_keys()
        self.timer.start()
        return True

    def _repair_components(self):
        """Il motore video manca (es. cartella bin cancellata): NOVA lo riscarica da sola, una volta."""
        if getattr(self, "_repairing", False):
            return
        self._repairing = True
        self.status.emit("Manca il motore video: lo scarico ora (circa 1 minuto, una volta sola)…", "info")

        def work():
            from . import deps
            try:
                failed = deps.ensure(log=lambda *_: None)
            except Exception as e:
                failed = [str(e)]
            self.bridge.repaired.emit(not failed or "libmpv-2.dll" not in failed)
        threading.Thread(target=work, daemon=True).start()

    def _repaired(self, ok):
        self._repairing = False
        if ok and load_mpv():
            self.status.emit("Motore video pronto: riapri il film.", "info")
        else:
            self.status.emit("Non riesco a scaricare il motore video: controlla la connessione e riprova.", "err")

    def _log(self, level, prefix, text):
        try:
            with open(DATA / "logs" / "mpv.log", "a", encoding="utf-8") as f:
                f.write(f"[{level}] {prefix}: {text}")
        except Exception:
            pass

    def apply_runtime_settings(self):
        """Applica a caldo le impostazioni di cache, qualità e sottotitoli."""
        if not self.player:
            return
        ps, ss = settings.data["player"], settings.data["stream"]
        p = self.player
        opts = {
            "cache": "yes",
            "demuxer-max-bytes": f"{fwd_cache_mb()}MiB",
            "demuxer-max-back-bytes": f"{back_cache_mb()}MiB",
            "cache-secs": str(int(ss["cache_secs"])),
            "demuxer-readahead-secs": str(readahead_s()),
            "cache-pause-initial": "no",
            "vd-lavc-threads": "0",
            "hwdec-codecs": "all",
            "cache-pause-wait": "1.5",        # riparte con 1,5 s pronti: abbastanza per non ri-fermarsi subito
            "network-timeout": "120",
            "stream-lavf-o": "reconnect=1,reconnect_streamed=1,reconnect_on_network_error=1,reconnect_delay_max=10",
            "hwdec": ("auto-copy-safe" if getattr(self, "theatre", False) else "auto-safe") if ps["hwdec"] else "no",
            "ytdl-format": (f"bestvideo[height<=?{ss['max_height']}]+bestaudio/"
                            f"best[height<=?{ss['max_height']}]/best"),
            "script-opts": f"ytdl_hook-ytdl_path={tool('yt-dlp')}",
            "sub-font-size": str(ps["sub_size"]),
            "sub-color": ps["sub_color"],
            "sub-back-color": "#99000000" if ps["sub_background"] else "#00000000",
            "sub-border-style": "opaque-box" if ps["sub_background"] else "outline-and-shadow",
            "alang": ps["audio_lang"],
            "slang": ps["sub_lang"],
            "resume-playback": "no",
            "subs-with-matching-audio": "yes" if ps.get("subs_with_english_audio", True) else "no",
        }
        if ss.get("user_agent"):
            opts["user-agent"] = ss["user_agent"]
        if ss.get("proxy"):
            opts["http-proxy"] = ss["proxy"]
        q = ps["quality"]
        if q == "max":
            opts.update({"scale": "ewa_lanczossharp", "dscale": "mitchell", "cscale": "ewa_lanczossharp",
                         "deband": "yes", "deband-iterations": "2"})
        elif q == "balanced":
            opts.update({"scale": "spline36", "dscale": "mitchell", "cscale": "spline36", "deband": "no"})
        else:
            opts.update({"scale": "bilinear", "dscale": "bilinear", "cscale": "bilinear", "deband": "no"})
        if ps.get("smooth", True):
            # niente micro-scatti: il video segue il refresh del monitor, tscale toglie il judder dei 24/25 fps
            opts.update({"video-sync": "display-resample", "interpolation": "yes", "tscale": "oversample"})
        else:
            opts.update({"video-sync": "audio", "interpolation": "no"})
        for line in settings.get("advanced", "mpv_conf").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                opts[k.strip().lstrip("-")] = v.strip()
        for k, v in opts.items():
            try:
                p.command("set", k, str(v))
            except Exception:
                pass
        if getattr(self, "theatre", False):
            self._cam_gpu()

    def bind_keys(self):
        """Scorciatoie attive anche quando il focus è dentro la finestra video di mpv."""
        if not self.player:
            return
        sc = settings.data["shortcuts"]
        mp = {qt_to_mpv_key(v): k for k, v in sc.items() if v}
        mp.update({"ESC": "escape", "MBTN_LEFT_DBL": "fullscreen", "MBTN_LEFT": "play_pause",
                   "WHEEL_UP": "vol_up", "WHEEL_DOWN": "vol_down", "MOUSE_MOVE": "move",
                   "MBTN_RIGHT": "context", "Ctrl+k": "palette", "F5": "refresh",
                   "PLAYPAUSE": "play_pause", "NEXT": "next", "PREV": "prev",
                   "Shift+RIGHT": "frame_fwd", "Shift+LEFT": "frame_back"})
        for old in getattr(self, "_bound", []):
            try:
                self.player.unregister_key_binding(old)
            except Exception:
                pass
        self._bound = []
        for keydef, action in mp.items():
            if not keydef:
                continue
            try:
                self.player.register_key_binding(
                    keydef, lambda state, name, char, *a, act=action: self._mpv_key(state, act))
                self._bound.append(keydef)
            except Exception:
                pass

    def _mpv_key(self, state, action):
        if action == "move" or state[0] in ("d", "p") or (state[0] == "r" and action.startswith(("seek", "vol"))):
            self.bridge.key.emit(action)

    def cmd(self, *args):
        if self.player:
            try:
                self.player.command(*args)
            except Exception:
                pass

    def set_prop(self, name, value):
        if self.player:
            try:
                self.player._set_property(name, value)
            except Exception:
                try:
                    self.player.command("set", name, str(value))
                except Exception:
                    pass

    def get_prop(self, name, default=None):
        if not self.player:
            return default
        try:
            v = self.player._get_property(name)
            return default if v is None else v
        except Exception:
            return default

    def add_prop(self, name, delta):
        self.set_prop(name, round(float(self.get_prop(name, 0)) + delta, 3))
        if name.endswith("delay"):
            self.cmd("show-text", f"{'Audio' if 'audio' in name else 'Sottotitoli'}: {self.get_prop(name, 0):+.1f}s")

    # ---------- apertura ----------
    def open_files(self):
        exts = " ".join(f"*{e}" for e in sorted(VIDEO_EXT | AUDIO_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "Apri file multimediali", "",
                                                f"Media ({exts});;Tutti i file (*)")
        if files:
            self.play(files[0], extra=files[1:])

    def play(self, url: str, extra=None, title: str | None = None, kind: str | None = None,
             key: str | None = None, start: float | None = None, hist_extra: dict | None = None):
        """url = cosa riprodurre; key = identità stabile per cronologia/ripresa (es. il file finale di un torrent)."""
        if not self.ensure_player():
            return
        if self.cast_session:
            self.stop_cast(resume_local=False)
        self._save_position()
        self.video_stack.setCurrentWidget(self.video)
        if not self.is_fullscreen and not self.is_pip:
            self.controls.show()
        self.current_url = url
        self.current_key = key or url
        is_local = os.path.isfile(url)
        self.thumbs.set_file(url if is_local else None)
        name = title or (Path(url).name if is_local else None)
        known = history.get(key or url)
        self.title.setText((known or {}).get("clean") or name or "Caricamento…")
        self.subtitle.setText("Locale" if is_local else ("Torrent · streaming" if kind == "torrent" else url[:110]))
        old = history.get(self.current_key)
        if start is None and settings.get("player", "resume"):
            start = resume_point(old)
        self._set_cover(str(cover_path(self.current_key)))
        self._old_sid, self.turbo_sid, self._pending = self.turbo_sid, None, None
        history.add(self.current_key, name or (old["title"] if old else url),
                    kind or ("file" if is_local else "link"), hist_extra)
        self._update_dl_button()
        if self._turbo_candidate(url):
            # Stream Turbo: prima controlla il link (dimensione, salti), poi parte dal proxy multi-connessione
            self.subtitle.setText("Stream Turbo · collegamento…")
            self._pending = (secrets.token_hex(6), url, extra, start)
            ss = settings.data["stream"]
            self.turbo.open(url, ss.get("user_agent", ""), int(ss.get("turbo_connections", 8)), self._pending[0])
            return
        self._load(url, extra, start)

    def _load(self, target, extra=None, start=None, opts=None):
        self._loaded_target = target
        try:
            o = dict(opts or {})
            if start:
                o["start"] = f"{start:.1f}"
            self.player.loadfile(target, "replace", **o)
            for f in extra or []:
                self.player.loadfile(f, "append")
        except Exception as e:
            self.status.emit(f"Errore: {e}", "err")
            return
        finally:
            old = getattr(self, "_old_sid", None)
            if old:
                # la sorgente precedente si chiude solo dopo che mpv è passato al nuovo video
                QTimer.singleShot(1500, lambda sid=old: self.turbo.close(sid))
                self._old_sid = None
        self.set_prop("pause", False)
        if start:
            QTimer.singleShot(900, lambda: self.cmd("show-text", f"Ripreso da {human_time(start)}", "2500"))

    # ---------- Stream Turbo ----------
    @staticmethod
    def _turbo_candidate(url: str) -> bool:
        if not settings.get("stream", "turbo") or not url.startswith(("http://", "https://")):
            return False
        host = urllib.parse.urlparse(url).hostname or ""
        if host in ("127.0.0.1", "localhost"):
            return False
        if any(host == d or host.endswith("." + d) for d in YTDL_HOSTS):
            return False      # pagine video: le gestisce yt-dlp
        ext = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).suffix.lower()
        if ext in (".m3u8", ".m3u", ".mpd", ".html", ".htm", ".txt", ".json"):
            return False
        # anche i link senza estensione (es. Cloudflare R2, Google Drive, CDN firmati):
        # la prova decide (serve un file grande che supporti i salti), altrimenti si apre normalmente
        return True

    def _turbo_ready(self, token, info):
        if not self._pending or self._pending[0] != token:
            return   # nel frattempo hai aperto altro
        _, url, extra, start = self._pending
        self._pending = None
        if not info.get("ok"):
            exp = link_expiry(url)
            if info.get("expired") and exp and exp < time.time():
                self.subtitle.setText("Link scaduto")
                self.status.emit("Questo link è scaduto: copia un link nuovo dal sito e riaprilo.", "err")
                return
            self._load(url, extra, start)    # non raggiungibile in turbo: prova normale
            return
        if info.get("name") and self.title.text() in ("Caricamento…", ""):
            self.title.setText(info["name"])
            history.set_title(self.current_key, info["name"])
        if not info.get("local"):
            self.subtitle.setText(url[:110])
            self._load(url, extra, start)
            return
        self.turbo_sid = info["sid"]
        self.subtitle.setText("Stream Turbo · " + (urllib.parse.urlparse(url).hostname or ""))
        # stesso film con un link nuovo (es. link scaduto ricopiato dal sito): riprende da dove eri
        name, size = info.get("name") or "", info.get("size") or 0
        if name and size:
            fid = f"{name}|{size}"
            old = history.find(fid=fid)
            if old and old["url"] != self.current_key:
                merged = history.rekey(old["url"], self.current_key)
                if merged and start is None and settings.get("player", "resume"):
                    start = resume_point(merged)
                self._set_cover(str(cover_path(self.current_key)))
            history.update_meta(self.current_key, {"fid": fid, "fname": name, "size": size, "dead": False})
            it = history.get(self.current_key)
            if it and it.get("clean"):
                self.title.setText(it["clean"])
        # niente timeout: se il link scade, mpv aspetta il link nuovo invece di chiudere il film
        self._load(info["local"], extra, start, {"network-timeout": "1800"})

    def _turbo_state(self, sid, st):
        if sid == self.turbo_sid and st == "expired":
            self.link_expired.emit(sid)

    def renew_link(self, url: str):
        if self.turbo_sid:
            self.turbo.renew(self.turbo_sid, url)

    def _close_turbo(self):
        self._pending = None
        self.turbo.close_all()
        self.turbo_sid = None

    def watching_network(self) -> bool:
        """True se stai guardando qualcosa che arriva dalla rete (link o torrent) e non è in pausa."""
        if self.cast_session:
            return not self.cast_session.paused       # anche la TV via Wi-Fi: niente scansioni, priorità
        if not self.player or self.get_prop("idle-active", True) or self.get_prop("pause", True):
            return False
        return bool(self.current_url) and not os.path.isfile(self.current_url)

    # ---------- profilo automatico per file pesanti e refresh ----------
    def _apply_profile(self):
        if not self.player or self.get_prop("idle-active", True):
            return
        vids = [t for t in self.track_list if t.get("type") == "video" and t.get("selected")]
        h = (vids[0].get("demux-h") if vids else 0) or (self.get_prop("height", 0) or 0)
        fps = float(self.get_prop("container-fps", 0) or 0)
        heavy = h >= 1440
        ps = settings.data["player"]
        self.apply_runtime_settings()      # base: qualità scelta nelle impostazioni
        self._fps = fps
        mode = refresh_mode()
        integer = self._match_refresh(fps) if mode == "always" or (mode == "fullscreen" and self.is_fullscreen) \
            else False
        opts = {}
        if heavy:
            # 4K: il video viene rimpicciolito; filtri pesanti non migliorano niente di visibile
            opts.update({"deband": "no", "cscale": "spline36", "dscale": "mitchell", "correct-downscaling": "yes",
                         "linear-downscaling": "no", "sigmoid-upscaling": "no"})
        if ps.get("smooth", True):
            # refresh multiplo esatto: movimento già perfetto. Altrimenti (es. 200 Hz) oversample toglie il judder
            opts["interpolation"] = "no" if integer else "yes"   # oversample: leggero anche in 4K (output 1080p)
        for k, v in opts.items():
            try:
                self.player.command("set", k, v)
            except Exception:
                pass
        self._rtx_vsr(h)
        it = history.get(self.current_key) or {}
        st = it.get("state") or {}
        want = st.get("theatre") if "theatre" in st else bool(it.get("theatre") and settings.get("player", "theatre_auto"))
        self.set_theatre(bool(want), quiet=not want)
        self._log("info", "profile", f"h={h} fps={fps} heavy={heavy} integer_refresh={integer} "
                                     f"switched={self._refresh_switched}\n")

    def _rtx_vsr(self, h):
        """RTX Video Super Resolution per i video piccoli (≤720p): la GPU NVIDIA li ingrandisce con l'AI."""
        want = None
        if (sys.platform == "win32" and settings.get("player", "rtx_vsr") and 0 < h <= 900
                and "NVIDIA" in (winutil.discrete_gpu_name() or "").upper()
                and str(self.get_prop("hwdec-current", "")).startswith("d3d11va")):
            scr = self.window().screen()
            sh = int(scr.size().height() * scr.devicePixelRatio()) if scr else 1080
            sc = round(min(4.0, max(1.0, sh / h)), 2)
            if sc > 1.05:
                want = f"d3d11vpp=scaling-mode=nvidia:scale={sc}"
        cur = getattr(self, "_vsr", None)
        if want == cur:
            return
        try:
            if cur:
                self.player.command("vf", "remove", "@nova_vsr")
            if want:
                self.player.command("vf", "add", f"@nova_vsr:{want}")
                self.cmd("show-text", "RTX Super Resolution attiva", "1500")
            self._vsr = want
        except Exception as e:
            self._vsr = None
            self._log("warn", "vsr", f"non disponibile: {e}\n")

    def _monitor(self):
        names = self.get_prop("display-names", []) or []
        return names[0] if names else None

    def _match_refresh(self, fps) -> bool:
        """Porta il monitor a un multiplo esatto dei fps (es. 200→144 Hz per i film a 24 fps)."""
        dev = self._monitor()
        if not dev or not fps:
            return False
        mode = winutil.display_mode(dev)
        if not mode:
            return False
        w, h, cur = mode
        if self._refresh_switched and self._refresh_switched[0] == dev:
            orig = self._refresh_switched[1]
        else:
            orig = cur
        target = winutil.best_rate_for(fps, winutil.display_rates(dev, w, h), orig)
        if target is None:
            k = round(orig / fps) if fps else 0
            exact = k >= 2 and abs(orig / (k * fps) - 1) < 0.004
            if self._refresh_switched and exact:
                self._restore_refresh()
            return exact
        if target == cur:
            return True
        if winutil.set_refresh(dev, target):
            if not self._refresh_switched:
                self._refresh_switched = (dev, orig)
            self.cmd("show-text", f"Monitor a {target} Hz per questo film", "2000")
            return True
        return False

    def _fs_refresh(self, on):
        if on and self.is_fullscreen:
            integer = self._match_refresh(getattr(self, "_fps", 0) or float(self.get_prop("container-fps", 0) or 0))
            if settings.get("player", "smooth") and integer:
                self.set_prop("interpolation", "no")
        elif not on:
            self._restore_refresh()

    def _restore_refresh(self):
        if self._refresh_switched:
            winutil.restore_refresh(self._refresh_switched[0])
            self._refresh_switched = None

    # ---------- suono: profili, uscita, ritardo per dispositivo ----------
    def device_name(self) -> str:
        return settings.get("audio", "device") or "auto"

    def device_desc(self, name: str | None = None) -> str:
        name = name or self.device_name()
        if name == "auto":
            return "Predefinita di Windows"
        d = next((x for x in self._device_list if x.get("name") == name), None)
        return (d.get("description") if d else None) or name

    def _dev_mem(self, name=None) -> dict:
        return settings.data["audio"].setdefault("devices", {}).setdefault(name or self.device_name(), {})

    def audio_profile(self) -> str:
        """Profilo scelto per l'uscita attuale (o quello generale); 'auto' viene risolto dal nome dell'uscita."""
        return self._dev_mem().get("profile") or settings.get("audio", "profile") or "auto"

    def effective_profile(self) -> str:
        p = self.audio_profile()
        return snd.auto_profile(self.device_desc()) if p == "auto" else p

    def set_audio_profile(self, prof: str):
        self._dev_mem()["profile"] = prof
        settings.save()
        self._apply_audio(force=True)
        eff = self.effective_profile()
        extra = f" → {snd.PROFILE_NAMES.get(eff, eff)}" if prof == "auto" else ""
        self.cmd("show-text", f"Suono: {snd.PROFILE_NAMES.get(prof, prof)}{extra}", "1800")

    def set_audio_device(self, name: str):
        settings.set("audio", "device", name, notify=False)
        self.set_prop("audio-device", name)
        mem = self._dev_mem()
        self.set_prop("audio-delay", float(mem.get("delay", 0.0)))
        self._apply_audio(force=True)
        self.cmd("show-text", f"Uscita: {self.device_desc()}", "1800")

    def set_exclusive(self, on: bool):
        self.set_prop("audio-exclusive", "yes" if on else "no")

    def save_device_delay(self):
        self._dev_mem()["delay"] = round(float(self.get_prop("audio-delay", 0) or 0), 3)
        settings.save()

    def _on_devices(self, lst):
        self._device_list = [d for d in lst if isinstance(d, dict)]
        want = self.device_name()
        names = {d.get("name") for d in self._device_list}
        if self.player and want != "auto" and self._device_list:
            if want not in names and not getattr(self, "_dev_lost", False):
                # cuffie scollegate (es. Bluetooth spento): pausa, invece di sparare il film dalle casse
                self._dev_lost = True
                if not self.get_prop("idle-active", True) and not self.get_prop("pause", True):
                    self.set_prop("pause", True)
                    self.status.emit(f"{self.device_desc()} scollegate: film in pausa. Ricollegale e premi play "
                                     "(o premi play per sentire dalle casse).", "info")
                self.set_prop("audio-device", "auto")
            elif want in names and getattr(self, "_dev_lost", False):
                self._dev_lost = False
                self.set_prop("audio-device", want)
                self.cmd("show-text", f"{self.device_desc()} di nuovo collegate", "1800")
        a = settings.data["audio"]
        if (not a.get("fx_warned") and self.device_name() == "auto"
                and any(snd.is_fxsound(d.get("description", "")) for d in self._device_list)):
            a["fx_warned"] = True
            settings.save()
            self.status.emit("FxSound è installato: se vuoi il suono originale del film, nel pannello Audio "
                             "scegli l'uscita diretta (cuffie o casse) invece di FxSound.", "info")

    def _on_audio_params(self, params):
        self._audio_in = params or {}
        self._apply_audio()

    def _apply_audio(self, force=False):
        if not self.player:
            return
        p = self._audio_in
        af = snd.build_af(self.effective_profile(), p.get("channels") or p.get("hr-channels") or "",
                          int(p.get("channel-count") or 0), getattr(self, "theatre", False),
                          bool((history.get(self.current_key) or {}).get("line_audio"))) if p else ""
        if p and settings.get("player", "loudness"):
            # volume uniforme tra film: misura (EBU R128) prima dei filtri, guadagno regolabile al volo
            g = getattr(self, "_lgain", 0.0)
            chain = ["@nova_lufs:lavfi=[ebur128=metadata=1]", f"@nova_gain:lavfi=[volume={g:.1f}dB]"]
            chain.append(af or "lavfi=[alimiter=limit=0.97:attack=5:release=80:level=disabled]")
            af = ",".join(chain)
        if af == self._af and not force:
            return
        self._af = af
        try:
            self.player.command("set", "af", af)
        except Exception as e:
            self._log("warn", "audio", f"filtro non applicato ({e}): {af}\n")
            try:
                self.player.command("set", "af", "")
            except Exception:
                pass

    # ---------- memoria per film ----------
    def _film_state(self) -> dict:
        return {"aid": self.get_prop("aid", None), "sid": self.get_prop("sid", None),
                "sub_delay": round(float(self.get_prop("sub-delay", 0) or 0), 2),
                "volume": int(self.controls.vol.value()), "theatre": bool(self.theatre)}

    def _restore_film(self):
        self._film_restored = True
        it = history.get(self.current_key)
        st = (it or {}).get("state")
        if not st or not settings.get("player", "remember_per_film"):
            return
        ids = {(t.get("type"), t.get("id")) for t in self.track_list}
        if st.get("aid") not in (None, False) and ("audio", st["aid"]) in ids:
            self.set_prop("aid", st["aid"])
        if st.get("sid") is False or st.get("sid") == "no":
            self.set_prop("sid", "no")
        elif st.get("sid") is not None and ("sub", st["sid"]) in ids:
            self.set_prop("sid", st["sid"])
        for f in st.get("subs") or []:
            loaded = any(t.get("external-filename") == f for t in self.track_list)
            if os.path.exists(f) and not loaded:
                try:
                    self.player.sub_add(f, "auto")
                except Exception:
                    pass
        if st.get("sub_delay"):
            self.set_prop("sub-delay", st["sub_delay"])
        if st.get("volume") is not None:
            self.controls.vol.setValue(int(st["volume"]))

    # ---------- copertine ----------
    def capture_cover(self):
        """Salva il fotogramma attuale come copertina (Home e sfondo). Lo scatto è istantaneo, il resto in background."""
        key = self.current_key
        if not self.player or not key or not self.get_prop("vid", False) or self.get_prop("idle-active", True):
            return
        out = cover_path(key)
        tmp = out.with_name(out.stem + "_full.jpg")
        try:
            self.player.command("set", "screenshot-format", "jpg")
            self.player.command("screenshot-to-file", str(tmp), "video")
        except Exception:
            return

        def work():
            try:
                img = QImage(str(tmp))
                if img.isNull():
                    return
                img.scaledToWidth(720, Qt.SmoothTransformation).save(str(out), "JPG", 88)
                tmp.unlink(missing_ok=True)
                self.bridge.cover.emit(key, str(out))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _set_cover(self, path):
        self.header.set_cover(path)
        col = None
        if settings.get("player", "film_colors") and path and os.path.exists(path):
            from .widgets import film_color
            c = film_color(QImage(path))
            col = c.name() if c else None
        self.controls.seek.accent = col
        self.controls.b_play.accent = col
        self.controls.seek.update()
        self.controls.b_play.update()

    def _on_cover(self, key, path):
        history.touch()
        if key == self.current_key:
            self._set_cover(path)

    def load_external_sub(self):
        f, _ = QFileDialog.getOpenFileName(self, "Carica sottotitoli", "",
                                           "Sottotitoli (*.srt *.ass *.ssa *.vtt *.sub *.sup *.idx);;Tutti (*)")
        if f:
            self.add_sub(f)

    def add_sub(self, f):
        try:
            self.player.sub_add(f, "select")
            self.cmd("show-text", f"Sottotitoli caricati: {Path(f).name}")
        except Exception as e:
            self.status.emit(f"Sottotitoli non validi: {e}", "err")

    def _download_current(self):
        if self.current_url and not os.path.isfile(self.current_url):
            self.request_download.emit(self.current_url)

    def _update_dl_button(self):
        self.controls.b_dl.setVisible(bool(self.current_url) and not os.path.isfile(self.current_url))

    # ---------- azioni ----------
    def toggle_pause(self):
        if not self.player:
            self.open_files()
            return
        if self.cast_session:
            self.cast_session.toggle_pause()
            return
        self.cmd("cycle", "pause")

    def toggle_mute(self):
        self.cmd("cycle", "mute")
        m = self.get_prop("mute", False)
        self.controls.b_vol.set_icon("mute" if m else "volume")

    def _vol(self, v):
        self.set_prop("volume", v)
        self.controls.b_vol.set_icon("mute" if v == 0 else "volume")
        settings.set("player", "volume", v, notify=False)

    def seek_abs(self, t):
        if self.cast_session:
            self.cast_session.seek(float(t))
            return
        self.cmd("seek", str(t), "absolute+keyframes" if t else "absolute")

    def seek_rel(self, s):
        if self.cast_session:
            self.cast_session.seek_rel(float(s))
            return
        self.cmd("seek", str(s), "relative")

    def reload(self) -> bool:
        """Riapre il video attuale dallo stesso punto (riconnette il link se lo stream si era bloccato)."""
        if not self.player or not self.current_url or self.get_prop("idle-active", True):
            return False
        pos = float(self.get_prop("time-pos", 0) or 0)
        it = history.get(self.current_key) or {}
        self.play(self.current_url, title=it.get("clean") or it.get("title"), kind=it.get("kind"),
                  key=self.current_key, start=max(0.0, pos - 1) or None,
                  hist_extra={k: it[k] for k in ("tid", "idx") if k in it} or None)
        return True

    def seek_to(self, t: float, text: str = ""):
        if self.cast_session:
            self.cast_session.seek(t)
            return
        self.cmd("seek", f"{t:.2f}", "absolute+exact")
        if self.get_prop("pause", False):
            self.set_prop("pause", False)
        self.cmd("show-text", f"{human_time(t)} · {text[:80]}" if text else human_time(t), "2200")

    def _sub_track(self):
        subs = [t for t in self.track_list if t.get("type") == "sub"]
        sel = next((t for t in subs if t.get("selected")), None)
        if sel:
            return sel
        from .subsearch import TEXT_CODECS
        text = [t for t in subs if t.get("external-filename") or (t.get("codec") or "").lower() in TEXT_CODECS]
        return next((t for t in text if (t.get("lang") or "").lower() in ("en", "eng")), text[0] if text else None)

    def open_sub_search(self):
        """Ctrl+F: cerca una frase nei sottotitoli e salta lì."""
        if not self.player or self.get_prop("idle-active", True):
            return
        from .subsearch import SubSearch
        src = self.current_url if os.path.isfile(self.current_url or "") else (self.get_prop("path", "") or "")
        SubSearch(self).start(src, self._sub_track())

    def ab_loop(self):
        self.cmd("ab-loop")

    def toggle_stats(self):
        self.cmd("script-binding", "stats/display-stats-toggle")

    def cycle_track(self, typ):
        self.cmd("cycle", "aid" if typ == "audio" else "sid")
        QTimer.singleShot(150, lambda: self._osd_track(typ))

    def _osd_track(self, typ):
        sel = [t for t in self.track_list if t.get("type") == typ and t.get("selected")]
        name = track_label(sel[0]) if sel else "Disattivati"
        self.cmd("show-text", f"{'Audio' if typ == 'audio' else 'Sottotitoli'}: {name}")

    def _on_key(self, action):
        if action == "move":
            self._last_move = time.time()
            return
        acts = {
            "play_pause": self.toggle_pause, "seek_fwd": lambda: self.seek_rel(5),
            "seek_back": lambda: self.seek_rel(-5), "seek_fwd_big": lambda: self.seek_rel(60),
            "seek_back_big": lambda: self.seek_rel(-60),
            "fullscreen": lambda: self.request_fullscreen.emit(not self.is_fullscreen),
            "escape": lambda: (self.request_fullscreen.emit(False) if self.is_fullscreen else
                               self.request_pip.emit(False) if self.is_pip else
                               self.request_cinema.emit(False) if self.is_cinema else
                               getattr(self.window(), "close_details", lambda: None)()),
            "cinema": lambda: self.request_cinema.emit(not self.is_cinema),
            "cam": lambda: self.set_theatre(not self.theatre),
            "sub_search": self.open_sub_search, "refresh": self.request_refresh.emit,
            "context": self.context_menu,
            "palette": self.request_palette.emit,
            "mute": self.toggle_mute, "stats": self.toggle_stats,
            "next_audio": lambda: self.cycle_track("audio"), "next_sub": lambda: self.cycle_track("sub"),
            "speed_up": lambda: (self.set_prop("speed", min(4.0, self.get_prop("speed", 1) + 0.25)),
                                 self.cmd("show-text", f"Velocità {self.get_prop('speed', 1):g}x")),
            "speed_down": lambda: (self.set_prop("speed", max(0.25, self.get_prop("speed", 1) - 0.25)),
                                   self.cmd("show-text", f"Velocità {self.get_prop('speed', 1):g}x")),
            "ab_loop": self.ab_loop, "pip": lambda: self.request_pip.emit(not self.is_pip),
            "vol_up": lambda: self.controls.vol.setValue(min(150, self.controls.vol.value() + 5)),
            "vol_down": lambda: self.controls.vol.setValue(max(0, self.controls.vol.value() - 5)),
            "next": lambda: self.cmd("playlist-next"), "prev": lambda: self.cmd("playlist-prev"),
            "frame_fwd": lambda: self.cmd("frame-step"), "frame_back": lambda: self.cmd("frame-back-step"),
        }
        f = acts.get(action)
        if f:
            f()
            self._last_move = time.time()

    def install_shortcuts(self, window):
        """Scorciatoie Qt (quando il focus è nell'interfaccia)."""
        for s in getattr(self, "_shortcuts", []):
            s.setEnabled(False)
            s.deleteLater()
        self._shortcuts = []
        for action, seq in settings.data["shortcuts"].items():
            if not seq:
                continue
            s = QShortcut(QKeySequence(seq), window)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(lambda a=action: self._shortcut(a))
            self._shortcuts.append(s)
        esc = QShortcut(QKeySequence("Esc"), window)
        esc.activated.connect(lambda: self._on_key("escape"))
        self._shortcuts.append(esc)

    def _shortcut(self, action):
        fw = QApplication.focusWidget()
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QKeySequenceEdit, QSpinBox
        if isinstance(fw, (QLineEdit, QPlainTextEdit, QKeySequenceEdit, QSpinBox)):
            return
        if not self.isVisible() and action not in ("play_pause", "mute"):
            return
        self._on_key(action)

    # ---------- eventi mpv ----------
    def _on_tracks(self, tl):
        self.track_list = tl
        if self.cast_session:
            sel = tuple((t.get("type"), t.get("id")) for t in tl if t.get("selected") and t.get("type") in ("audio", "sub"))
            if getattr(self, "_cast_sel", None) not in (None, sel):
                self.cast_session.seek(self.cast_session.position())
            self._cast_sel = sel
        vids = [t for t in tl if t.get("type") == "video" and not t.get("albumart")]
        self.controls.b_quality.setVisible(len(vids) > 1)

    def _on_pause(self, paused):
        self.controls.b_play.set_icon("play" if paused else "pause")
        winutil.keep_awake(not paused and bool(self.player))

    def _on_idle(self, idle):
        if idle:
            winutil.keep_awake(False)
            self._restore_refresh()

    def _on_title(self, t):
        if t and self.current_url and not os.path.isfile(self.current_url) and not t.startswith("http"):
            history.set_title(self.current_key, t)     # titolo dentro al file (MKV): spesso il più pulito
        it = history.get(self.current_key) if self.current_key else None
        if it and it.get("clean"):
            self.title.setText(it["clean"])
        elif t:
            self.title.setText(t)

    def _check_perf(self):
        """Avvisa se un video pesante sta andando senza decodifica hardware (causa n.1 di scatti)."""
        hw = self.get_prop("hwdec-current", "no")
        h = (self.get_prop("video-params", {}) or {}).get("h", 0) or 0
        codec = self.get_prop("video-codec", "") or ""
        self._log("info", "perf", f"hwdec={hw} h={h} codec={codec} "
                  f"adapter={settings.get('player', 'hwdec') and winutil.discrete_gpu_name()}\n")
        if h >= 1440 and hw in ("no", "", None) and settings.get("player", "hwdec"):
            self.status.emit("Decodifica hardware non attiva su questo video: potrebbe scattare. "
                             "Aggiorna il driver NVIDIA e riavvia NOVA.", "err")

    def _on_loaded(self):
        self._film_restored = False
        self.intro = self.credits = None
        self._intro_skipped = False
        self.controls.b_skip.hide()
        QTimer.singleShot(1500, self._find_intro)
        QTimer.singleShot(400, self._restore_film)
        QTimer.singleShot(2500, self._check_perf)
        QTimer.singleShot(700, self._apply_profile)
        # Per HLS/DASH con più varianti: scegli la qualità più alta entro il limite impostato
        maxh = int(settings.get("stream", "max_height"))
        vids = [t for t in self.track_list if t.get("type") == "video" and t.get("demux-h")]
        if len(vids) > 1:
            ok = [t for t in vids if t["demux-h"] <= maxh] or vids
            best = max(ok, key=lambda t: (t["demux-h"], t.get("demux-bitrate") or t.get("hls-bitrate") or 0))
            self.set_prop("vid", best["id"])
        path = self.get_prop("path", "")
        if path and path != self.current_url and path != getattr(self, "_loaded_target", None) \
                and os.path.isfile(path):
            # la playlist è passata al file successivo
            self.current_url = self.current_key = path
            self.thumbs.set_file(path)
            history.add(path, Path(path).name, "file")
            self._set_cover(str(cover_path(path)))
            self._update_dl_button()
        self._lgain = float((history.get(self.current_key) or {}).get("lgain") or 0.0)
        self._apply_audio(force=True)
        QTimer.singleShot(6000 if cover_path(self.current_key).exists() else 1500, self.capture_cover)
        self.status.emit("", "loaded")

    def _on_end(self, reason, error):
        if reason == 4:  # ERROR
            self.status.emit("Impossibile riprodurre questo contenuto. Controlla il link o il formato.", "err")
            self.subtitle.setText("Errore di riproduzione")

    def _poll(self):
        if not self.player:
            return
        pos = self.get_prop("time-pos", 0) or 0
        dur = self.get_prop("duration", 0) or 0
        cache_t = self.get_prop("demuxer-cache-time", 0) or 0
        c = self.controls
        if self.cast_session:
            cs = self.cast_session
            pos = cs.position()
            dur = dur or cs.duration
            c.seek.set_state(pos, dur, pos + cs.buffer_ahead(), 0.0 if cs.paused or cs._pending is not None else 1.0)
            c.time.setText(f"{human_time(pos)} / {human_time(dur)}")
            c.net.setText(cs.info_text())
            if getattr(self, "_cast_sub", None):
                self._cast_sub.setText(cs.info_text().replace("TV · ", ""))
            if time.time() - self._last_hist > 5 and self.current_key and dur:
                self._last_hist = time.time()
                history.update_pos(self.current_key, pos, dur)
            return
        paused = self.get_prop("pause", True) or self.get_prop("paused-for-cache", False) \
            or self.get_prop("seeking", False)
        c.seek.set_state(pos, dur, cache_t, 0.0 if paused else float(self.get_prop("speed", 1.0) or 1.0))
        c.seek.ab = (self.get_prop("ab-loop-a", None) if self.get_prop("ab-loop-a", "no") != "no" else None,
                     self.get_prop("ab-loop-b", None) if self.get_prop("ab-loop-b", "no") != "no" else None)
        c.time.setText(f"{human_time(pos)} / {human_time(dur)}")
        net = ""
        if self.current_url and not os.path.isfile(self.current_url):
            spd = self.turbo.speed(self.turbo_sid) if self.turbo_sid else (self.get_prop("cache-speed", 0) or 0)
            ahead = max(0.0, cache_t - pos)
            buffering = self.get_prop("paused-for-cache", False)
            bstate = self.get_prop("cache-buffering-state", 100)
            net = f"↓ {human_speed(spd)}  ·  buffer {ahead:.0f}s"
            if buffering:
                net = f"Buffering {bstate}%  ·  ↓ {human_speed(spd)}"
        c.net.setText(net)
        self._update_skip(pos, dur)
        self._check_sleep(pos, dur)
        if not paused and dur:
            self._watch_acc = getattr(self, "_watch_acc", 0.0) + 0.25
        if time.time() - self._last_hist > 5 and self.current_key and dur:
            self._last_hist = time.time()
            fin = None
            if pos > dur * 0.93 and not (history.get(self.current_key) or {}).get("finished"):
                history.update_meta(self.current_key, {"finished": True}, notify=False)
                fin = self.current_key
            if getattr(self, "_watch_acc", 0) >= 5 or fin:
                from .catalog import add_watch
                add_watch(self._watch_acc, fin)
                self._watch_acc = 0.0
            history.update_pos(self.current_key, pos, dur)
            if not paused:
                self._loudness_step()
            if self._film_restored:
                history.update_state(self.current_key, self._film_state())

    # ---------- volume uniforme tra film (EBU R128) ----------
    LOUD_TARGET = -21.0

    def _loudness_step(self):
        """Ogni 5 s: legge la loudness integrata del film e porta il guadagno verso il livello comune,
        al massimo 1 dB alla volta (nessun salto udibile). Il valore resta salvato per film."""
        if not settings.get("player", "loudness") or "nova_lufs" not in (self._af or ""):
            return
        try:
            md = self.player._get_property("af-metadata/nova_lufs") or {}
            i = float(md.get("lavfi.r128.I", "-70"))
        except Exception:
            return
        if i <= -60:
            return     # ancora troppo poco audio misurato (o silenzio)
        want = max(-10.0, min(8.0, self.LOUD_TARGET - i))
        cur = getattr(self, "_lgain", 0.0)
        if abs(want - cur) < 0.6:
            return
        new = round(cur + max(-1.0, min(1.0, want - cur)), 1)
        try:
            self.player.command("af-command", "nova_gain", "volume", f"{new:.1f}dB", "Parsed_volume_0")
        except Exception:
            return
        self._lgain = new
        self._af = self._af.replace(f"volume={cur:.1f}dB", f"volume={new:.1f}dB")
        if self.current_key:
            history.update_meta(self.current_key, {"lgain": new}, notify=False)

    def _save_position(self):
        if self.player and self.current_key:
            pos, dur = self.get_prop("time-pos", 0), self.get_prop("duration", 0)
            if dur:
                history.update_pos(self.current_key, pos or 0, dur)
                if pos and pos > 5:
                    self.capture_cover()

    # ---------- anteprima seekbar ----------
    def _seek_hover(self, t, gpos):
        self._hover_t = t
        self._hover_gpos = gpos
        img = None
        if self.thumbs.path:
            key = int(t // 2) * 2
            img = self.thumbs.cache.get(key)
            self.thumbs.request(t)
        self.thumb_popup.set(human_time(t), img)
        self._place_thumb()

    def _place_thumb(self):
        tp = self.thumb_popup
        g = self._hover_gpos
        tp.move(g.x() - tp.width() // 2, g.y() - tp.height() - 12)
        if not tp.isVisible():
            tp.show()

    def _thumb_ready(self, t, img):
        if self.thumb_popup.isVisible() and abs(t - self._hover_t) < 2.5:
            self.thumb_popup.set(human_time(self._hover_t), img)
            self._place_thumb()

    # ---------- Boost: video di bassa qualità ----------
    CAM_VF = ("deblock=filter=strong:block=8,hqdn3d=3:2.5:9:7,"
              "eq=contrast=1.07:saturation=1.12:gamma=0.96,cas=0.6")

    def _cam_gpu(self):
        for k, v in (("deband", "yes"), ("deband-iterations", "4"), ("deband-threshold", "64"),
                     ("deband-range", "16"), ("deband-grain", "24"), ("scale", "ewa_lanczossharp"),
                     ("cscale", "ewa_lanczossharp")):
            try:
                self.player.command("set", k, v)
            except Exception:
                pass

    def set_theatre(self, on: bool, quiet=False):
        """Migliora video di bassa qualità (registrazioni, vecchi video, file molto compressi). Video: meno blocchi e grana, contrasto e colori più vivi, più nitido, upscaling
        di qualità e debanding sulla GPU. Audio: meno fruscio e rimbombo, voci avanti (saltato se il file ha
        l'audio 'Line/Org', che è già pulito)."""
        self.controls.b_cam.setChecked(on)
        if not self.player:
            return
        changed = on != self.theatre
        self.theatre = on
        self._apply_audio(force=True)
        try:
            if on:
                self.player.command("set", "hwdec", "auto-copy-safe")
                if not self._cam_vf:
                    self.player.command("vf", "add", f"@nova_cam:lavfi=[{self.CAM_VF}]")
                    self._cam_vf = True
                self._cam_gpu()
            elif self._cam_vf:
                self.player.command("vf", "remove", "@nova_cam")
                self._cam_vf = False
                self.apply_runtime_settings()          # torna alla qualità normale (hwdec, deband, scaler)
        except Exception as e:
            self._log("warn", "cam", f"{e}\n")
        if changed and not quiet:
            it = history.get(self.current_key) or {}
            extra = " · audio Line già pulito" if on and it.get("line_audio") else ""
            self.cmd("show-text", ("Boost video attivo" + extra) if on else "Boost video spento", "1800")
        if changed and self.current_key and self._film_restored:
            history.update_state(self.current_key, self._film_state())

    # ---------- salta intro ----------
    def _find_intro(self):
        if not self.player or self.get_prop("idle-active", True):
            return
        from . import ai
        dur = float(self.get_prop("duration", 0) or 0)
        chapters = self.get_prop("chapter-list", []) or []
        self.intro, self.credits = ai.chapter_ranges(chapters, dur)
        it = history.get(self.current_key) or {}
        if not self.intro and it.get("intro"):
            self.intro = tuple(it["intro"])
        if self.intro or not settings.get("library", "detect_intro"):
            return
        key = self.current_key
        if not os.path.isfile(key) or it.get("intro_checked"):
            return          # solo file sul PC: per i link servirebbe scaricare i primi minuti
        from .catalog import Catalog
        sib = Catalog.sibling_episode(key)
        if not sib:
            return

        def work():
            try:
                fa, fb = ai.fingerprint(key), ai.fingerprint(sib)
                res = ai.find_common(fa, fb)
            except Exception:
                res = None
            self.bridge.intro_found.emit(key, sib, list(res) if res else [])
        threading.Thread(target=work, daemon=True).start()

    def _intro_found(self, key, sib, res):
        history.update_meta(key, {"intro_checked": True}, notify=False)
        if not res:
            return
        (a0, a1), (b0, b1) = res
        if a1 - a0 > 240:      # più di 4 minuti uguali: non è una sigla
            return
        history.update_meta(key, {"intro": [a0, a1]}, notify=False)
        if history.get(sib):
            history.update_meta(sib, {"intro": [b0, b1], "intro_checked": True}, notify=False)
        else:
            history.add(sib, Path(sib).name, "file", {"intro": [b0, b1], "intro_checked": True})
            history.items.insert(len(history.items), history.items.pop(0))   # non in cima: non l'hai ancora visto
            history._save(notify=False)
        if key == self.current_key:
            self.intro = (a0, a1)

    def _update_skip(self, pos, dur):
        b = self.controls.b_skip
        show = None
        if self.intro and self.intro[0] - 0.5 <= pos < self.intro[1] - 2:
            if settings.get("library", "skip_intro_auto") and not self._intro_skipped:
                self._intro_skipped = True
                self.seek_abs(self.intro[1])
                self.cmd("show-text", "Intro saltata", "1500")
                return
            show = "Salta intro  ›"
        elif self.credits and self.credits[0] <= pos < self.credits[1] - 3:
            show = "Prossimo episodio  ›"
        if show:
            if b.text() != show:
                b.setText(show)
            if not b.isVisible():
                b.show()
                self._last_move = time.time()      # in schermo intero fa comparire i controlli
        elif b.isVisible():
            b.hide()

    def _skip_clicked(self):
        if self.controls.b_skip.text().startswith("Salta") and self.intro:
            self._intro_skipped = True
            self.seek_abs(self.intro[1])
        elif self.current_key:
            self.episode_ended.emit(self.current_key)
        self.controls.b_skip.hide()

    # ---------- sottotitoli: AI e sincronizzazione ----------
    def _rel_index(self, typ, track):
        same = [t for t in self.track_list if t.get("type") == typ and not t.get("external")]
        return same.index(track) if track in same else 0

    def media_source(self) -> str:
        """Il file o il link da far leggere a ffmpeg (per i link passa dallo Stream Turbo, più veloce)."""
        if self.turbo_sid:
            return self.get_prop("path", self.current_url) or self.current_url
        return self.current_url

    def sync_subs(self):
        if not self.player or self.get_prop("idle-active", True):
            return
        sub = next((t for t in self.track_list if t.get("type") == "sub" and t.get("selected")), None)
        aud = next((t for t in self.track_list if t.get("type") == "audio" and t.get("selected")), None)
        if not sub or not aud:
            self.status.emit("Attiva prima i sottotitoli da sincronizzare.", "err")
            return
        from . import ai
        src = self.media_source()
        local = os.path.isfile(src)
        at = float(self.get_prop("time-pos", 0) or 0)
        aidx = self._rel_index("audio", aud)
        ext = sub.get("external-filename")
        sidx = None if ext else self._rel_index("sub", sub)
        self.cmd("show-text", "Sincronizzo i sottotitoli…", "4000")
        self.status.emit("Ascolto il film e allineo i sottotitoli: qualche secondo…", "info")

        def work():
            import tempfile
            try:
                tmp = Path(tempfile.gettempdir()) / f"nova_sub_{os.getpid()}.srt"
                path = ai.convert_sub(ext, tmp) if ext else ai.extract_text_sub(src, sidx, tmp)
                off, ratio, conf, before = ai.sync_subtitles(src, aidx, path, local=local, at=at)
                self.bridge.sync_done.emit({"ok": True, "off": off, "ratio": ratio, "conf": conf, "before": before,
                                            "path": path})
            except Exception as e:
                self.bridge.sync_done.emit({"ok": False, "msg": str(e)[:200]})
        threading.Thread(target=work, daemon=True).start()

    def _sync_done(self, r):
        from . import ai
        if not r.get("ok"):
            self.status.emit("Sincronizzazione non riuscita: " + r.get("msg", ""), "err")
            return
        off, ratio, conf, before = r["off"], r["ratio"], r["conf"], r["before"]
        if conf < 0.35:
            self.status.emit("Non sono sicuro: questi sottotitoli forse sono di un'altra versione del film.", "err")
            return
        if abs(ratio - 1) < 1e-6:
            self.set_prop("sub-delay", round(off, 2))
            if abs(off) < 0.15:
                self.status.emit("I sottotitoli erano già a tempo.", "info")
            else:
                self.status.emit(f"Sottotitoli sincronizzati: {off:+.2f} s (sicurezza {conf * 100:.0f}%).", "info")
            return
        cues = ai.read_srt(r["path"])
        out = ai.subs_dir_for(self.current_url) / (Path(self.current_url).stem + ".sync.srt")
        ai.write_srt(str(out), [(a * ratio + off, b * ratio + off, t) for a, b, t in cues])
        self.set_prop("sub-delay", 0)
        self.add_sub(str(out))
        self.status.emit("Sottotitoli corretti: erano per una versione a velocità diversa (25 / 23,976 fps).", "info")

    # ---------- timer spegnimento ----------
    def set_sleep(self, seconds):
        """>0: tra N secondi · -1: a fine film · 0: annulla."""
        self._sleep_at = None if seconds == 0 else ("end" if seconds < 0 else time.time() + seconds)
        msg = ("Timer annullato" if seconds == 0 else "Si ferma a fine film" if seconds < 0
               else f"Si ferma tra {seconds // 60} minuti")
        self.cmd("show-text", msg, "2000")

    def _sleep_left(self):
        if self._sleep_at == "end":
            return "fine film"
        return f"{max(0, int((self._sleep_at - time.time()) // 60))} min"

    def _check_sleep(self, pos, dur):
        if not self._sleep_at:
            return
        due = (self._sleep_at == "end" and dur and pos >= dur - 1.5) or \
              (self._sleep_at != "end" and time.time() >= self._sleep_at)
        if not due:
            return
        self._sleep_at = None
        self.set_prop("pause", True)
        self._save_position()
        if self.is_fullscreen:
            self.request_fullscreen.emit(False)
        if settings.get("player", "sleep_pc"):
            QTimer.singleShot(3000, winutil.sleep_pc)
        self.status.emit("Timer: film in pausa. Riprendi da dove eri quando vuoi.", "info")

    # ---------- telefono e TV ----------
    def _lan(self):
        if self.lan is None:
            from .lan import LanServer
            self.lan = LanServer(self.remote_state)
            self.lan.accent = theme.accent
            self.lan.command.connect(self._remote_cmd)
        if not self.lan.start():
            self.status.emit("Impossibile aprire il server sulla rete di casa.", "err")
            return None
        return self.lan

    def remote_state(self) -> dict:
        cs = self.cast_session
        if cs:
            return {"title": self.title.text(), "pos": cs.position(), "dur": cs.duration, "paused": cs.paused,
                    "volume": int(self.get_prop("volume", 100) or 0), "tv": self.casting.get("name", "TV")}
        try:
            return {"title": self.title.text() if self.player else "", "pos": float(self.get_prop("time-pos", 0) or 0),
                    "dur": float(self.get_prop("duration", 0) or 0), "paused": bool(self.get_prop("pause", True)),
                    "volume": int(self.get_prop("volume", 100) or 0)}
        except Exception:
            return {}

    def _remote_cmd(self, a, v):
        try:
            x = float(v) if v else 0.0
        except ValueError:
            x = 0.0
        if self.cast_session and a in ("toggle", "seek", "goto"):
            {"toggle": self.toggle_pause, "seek": lambda: self.seek_rel(x), "goto": lambda: self.seek_abs(x)}[a]()
            return
        if self.casting and a in ("toggle", "seek", "goto"):
            self._tv(a, x)
            return
        acts = {"toggle": self.toggle_pause, "seek": lambda: self.seek_rel(x), "goto": lambda: self.seek_abs(x),
                "vol": lambda: self.controls.vol.setValue(max(0, min(150, self.controls.vol.value() + int(x)))),
                "mute": self.toggle_mute, "audio": lambda: self.cycle_track("audio"),
                "sub": lambda: self.cycle_track("sub"),
                "fs": lambda: self.request_fullscreen.emit(not self.is_fullscreen),
                "next": lambda: self.cmd("playlist-next")}
        f = acts.get(a)
        if f and self.player:
            f()

    def show_remote(self):
        lan = self._lan()
        if lan:
            RemoteDialog(self, lan.remote_url()).exec()

    def cast_pc(self, tv, quality: str | None = None):
        """TV: il PC fa tutto (decodifica, sottotitoli, compressione leggera); la TV mostra soltanto."""
        if not self.player or self.get_prop("idle-active", True):
            self.status.emit("Apri prima un film, poi trasmettilo alla TV.", "err")
            return
        srv = self._lan()
        if not srv:
            return
        from .tvcast import CastSession
        if self.cast_session:
            pos = self.cast_session.stop()
            self.cast_session.deleteLater()
        else:
            pos = float(self.get_prop("time-pos", 0) or 0)
        q = quality or settings.get("player", "tv_quality") or "auto"
        self.set_prop("pause", True)
        self.casting = tv
        cs = self.cast_session = CastSession(self, tv, srv, q)
        cs.status.connect(self.status.emit)
        cs.changed.connect(lambda: self.controls.b_play.set_icon("play" if cs.paused else "pause"))
        self._cast_sel = None
        winutil.keep_awake(True)
        cs.start(pos)
        self._show_cast_page(tv)
        h, kb = L_ladder(cs.level)
        self.status.emit(f"Invio a {tv['name']}: il PC prepara il film ({h}p), parte in pochi secondi. "
                         "Comanda tutto da NOVA o dal telefono.", "info")

    def _show_cast_page(self, tv):
        """Sul PC, al posto del fotogramma fermo: 'In onda sulla TV'."""
        if not getattr(self, "_cast_page", None):
            w = QWidget()
            w.setObjectName("castpage")
            w.setStyleSheet(f"#castpage{{background:qradialgradient(cx:0.5,cy:0.45,radius:0.8,"
                            f"stop:0 {theme.surface2},stop:1 #000000);}}")
            v = QVBoxLayout(w)
            v.addStretch(1)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("cast", theme.accent, 72))
            ic.setAlignment(Qt.AlignCenter)
            v.addWidget(ic)
            self._cast_title = QLabel()
            self._cast_title.setAlignment(Qt.AlignCenter)
            self._cast_title.setStyleSheet("color:white;font-size:24px;font-weight:700;")
            v.addWidget(self._cast_title)
            self._cast_sub = QLabel()
            self._cast_sub.setAlignment(Qt.AlignCenter)
            self._cast_sub.setStyleSheet("color:rgba(255,255,255,0.65);font-size:14px;")
            v.addWidget(self._cast_sub)
            hint = QLabel("Il PC prepara il film, la TV lo mostra soltanto.\nSalti, pausa e tracce da qui o dal "
                          "telefono · per tornare sul PC: Trasmetti › Ferma la TV")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("color:rgba(255,255,255,0.45);font-size:12px;margin-top:14px;")
            v.addWidget(hint)
            v.addStretch(1)
            self._cast_page = w
            self.video_stack.addWidget(w)
        self._cast_title.setText(f"In onda su {tv.get('name', 'TV')}")
        self._cast_sub.setText("Avvio…")
        self.video_stack.setCurrentWidget(self._cast_page)

    def set_tv_quality(self, q: str):
        settings.set("player", "tv_quality", q, notify=False)
        if self.cast_session:
            self.cast_session.set_quality(q)

    def cast_to(self, tv):
        from . import lan as L
        if not self.player or self.get_prop("idle-active", True):
            self.status.emit("Apri prima un film, poi trasmettilo alla TV.", "err")
            return
        srv = self._lan()
        if not srv:
            return
        src = self.current_url
        if self.turbo_sid:
            src = self.get_prop("path", src) or src          # passa dallo Stream Turbo (veloce, con salti)
        pos = float(self.get_prop("time-pos", 0) or 0)
        aud = next((t for t in self.track_list if t.get("type") == "audio" and t.get("selected")), None)
        codec = (aud or {}).get("codec", "")
        live = bool(aud) and codec not in L.TV_AUDIO_OK
        aidx = 0
        if aud:
            auds = [t for t in self.track_list if t.get("type") == "audio"]
            aidx = auds.index(aud)
        mid = srv.add_media(src, aidx if live else None, pos if live else 0.0)
        url = f"{srv.base()}/{'live' if live else 'm'}/{mid}"
        ext = Path(urllib.parse.urlparse(src).path).suffix.lower() if src.startswith("http") else Path(src).suffix.lower()
        mime = "video/mp2t" if live else L.MIME.get(ext, "video/x-matroska")
        title = self.title.text()
        self.set_prop("pause", True)

        def work():
            try:
                L.cast(tv, url, title, mime, live)
                if not live and pos > 5:
                    time.sleep(4)
                    try:
                        L.tv_command(tv, "Seek", pos)
                    except Exception:
                        pass
                self.bridge.cast_state.emit(tv, "ok" + (":live" if live else ""))
            except Exception as e:
                self.bridge.cast_state.emit(tv, f"err:{e}")
        threading.Thread(target=work, daemon=True).start()
        self.status.emit(f"Invio a {tv['name']}…", "info")

    def _cast_state(self, tv, st):
        if st.startswith("ok"):
            self.casting = tv
            note = (" L'audio viene convertito per la TV: per saltare usa NOVA, non il telecomando della TV."
                    if st.endswith(":live") else "")
            self.status.emit(f"In onda su {tv['name']}.{note}", "info")
        else:
            self.casting = None
            self.status.emit(f"La TV non ha accettato il video ({st[4:][:120]}). Controlla che sia accesa e sullo "
                             "stesso Wi-Fi, e che Windows permetta a NOVA l'accesso alle reti private.", "err")

    def _tv(self, a, x):
        from . import lan as L
        tv = self.casting

        def work():
            try:
                if a == "toggle":
                    st = getattr(self, "_tv_paused", False)
                    L.tv_command(tv, "Play" if st else "Pause")
                    self._tv_paused = not st
                elif a == "goto":
                    L.tv_command(tv, "Seek", x)
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def stop_cast(self, resume_local=True):
        from . import lan as L
        cs, self.cast_session = self.cast_session, None
        tv, self.casting = self.casting, None
        if cs:
            pos = cs.stop()
            cs.deleteLater()
            winutil.keep_awake(False)
            self.video_stack.setCurrentWidget(self.video)
            if resume_local and self.player and not self.get_prop("idle-active", True):
                # sul PC riprendi da dove era arrivata la TV (in pausa)
                self.cmd("seek", f"{pos:.1f}", "absolute")
                self.set_prop("pause", True)
                self.controls.b_play.set_icon("play")
            self.status.emit("TV fermata: su NOVA riprendi da dove eri.", "info")
            return
        if tv:
            threading.Thread(target=lambda: L.tv_command(tv, "Stop"), daemon=True).start()

    # ---------- menu col tasto destro ----------
    def context_menu(self):
        from PySide6.QtWidgets import QMenu
        if not self.player or self.get_prop("idle-active", True):
            return
        m = QMenu(self)
        paused = self.get_prop("pause", False)
        m.addAction("▶  Riprendi" if paused else "❚❚  Pausa", self.toggle_pause)
        m.addSeparator()
        for typ, title, prop in (("audio", "Traccia audio", "aid"), ("sub", "Sottotitoli", "sid")):
            sm = m.addMenu(title)
            tracks = [t for t in self.track_list if t.get("type") == typ]
            if typ == "sub":
                a = sm.addAction("Disattivati", lambda: self.set_prop("sid", "no"))
                a.setCheckable(True)
                a.setChecked(not any(t.get("selected") for t in tracks))
            for t in tracks:
                a = sm.addAction(track_label(t), lambda tid=t["id"], pr=prop: self.set_prop(pr, tid))
                a.setCheckable(True)
                a.setChecked(bool(t.get("selected")))
            if typ == "sub":
                sm.addSeparator()
                sm.addAction("Cerca una frase…  (Ctrl+F)", self.open_sub_search)
                sm.addAction("Carica sottotitoli esterni…", self.load_external_sub)
        sm = m.addMenu("Suono")
        cur = self.audio_profile()
        for k, name, _ in snd.PROFILES:
            a = sm.addAction(name, lambda k=k: self.set_audio_profile(k))
            a.setCheckable(True)
            a.setChecked(k == cur)
        sm = m.addMenu("Velocità")
        sp = self.get_prop("speed", 1.0)
        for v in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            a = sm.addAction("Normale" if v == 1 else f"{v:g}x", lambda v=v: self.set_prop("speed", v))
            a.setCheckable(True)
            a.setChecked(abs(sp - v) < 0.01)
        m.addSeparator()
        a = m.addAction("Migliora video di bassa qualità (T)", lambda: self.set_theatre(not self.theatre))
        a.setCheckable(True)
        a.setChecked(self.theatre)
        m.addAction("Sincronizza sottotitoli", self.sync_subs)
        m.addAction("Esci da modalità cinema" if self.is_cinema else "Modalità cinema (C)",
                    lambda: self.request_cinema.emit(not self.is_cinema))
        m.addAction("Esci da schermo intero" if self.is_fullscreen else "Schermo intero (F)",
                    lambda: self.request_fullscreen.emit(not self.is_fullscreen))
        m.addAction("Picture-in-picture (P)", lambda: self.request_pip.emit(not self.is_pip))
        m.addAction("Statistiche (I)", self.toggle_stats)
        sm = m.addMenu("Timer spegnimento" + (f"  ·  {self._sleep_left()}" if self._sleep_at else ""))
        for mins in (15, 30, 45, 60, 90, 120):
            sm.addAction(f"Tra {mins} minuti", lambda mn=mins: self.set_sleep(mn * 60))
        sm.addAction("A fine film", lambda: self.set_sleep(-1))
        sm.addSeparator()
        a = sm.addAction("Metti anche il PC in sospensione", lambda: settings.set(
            "player", "sleep_pc", not settings.get("player", "sleep_pc"), notify=False))
        a.setCheckable(True)
        a.setChecked(bool(settings.get("player", "sleep_pc")))
        if self._sleep_at:
            sm.addAction("Annulla timer", lambda: self.set_sleep(0))
        m.addSeparator()
        if self.get_prop("time-pos", 0) and self.get_prop("time-pos", 0) > 5:
            m.addAction("Ricomincia dall'inizio", lambda: self.seek_abs(0))
        if self.current_url and os.path.isfile(self.current_url):
            from .downloads import reveal
            m.addAction("Mostra nella cartella", lambda: reveal(self.current_url))
        elif self.current_url:
            m.addAction("Copia link", lambda: QApplication.clipboard().setText(self.current_url))
            m.addAction("Scarica questo video", self._download_current)
        if self.current_url and not self.current_url.startswith("http://127.0.0.1"):
            from .downloads import start_phone
            it = history.get(self.current_key) or {}
            m.addAction("Versione per telefono (max 1,4 GB)",
                        lambda: start_phone(self, self.current_url, it.get("clean") or self.title.text()))
        m.exec(QCursor.pos())

    def set_cinema_mode(self, on: bool):
        self.is_cinema = on
        self.top.setVisible(not on and not self.is_pip and not self.is_fullscreen)
        if on:
            self.cmd("show-text", "Modalità cinema · Esc per uscire", "1500")

    # ---------- schermo intero ----------
    def set_fullscreen_mode(self, on: bool):
        self.is_fullscreen = on
        if refresh_mode() == "fullscreen" and self.player and not self.get_prop("idle-active", True):
            # refresh del film solo a schermo intero: niente schermo nero quando chiudi o lavori in finestra
            if on:
                QTimer.singleShot(250, lambda: self._fs_refresh(True))
            else:
                self._fs_refresh(False)
        self.top.setVisible(not on and not self.is_pip and not self.is_cinema)
        c = self.controls
        if on:
            self._root.removeWidget(c)
            c.setParent(None)
            c.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                             Qt.WindowDoesNotAcceptFocus)
            c.setAttribute(Qt.WA_TranslucentBackground)
            c.setAttribute(Qt.WA_ShowWithoutActivating)
            c.set_overlay(True)
            QTimer.singleShot(60, self._place_overlay)
            self._last_move = time.time()
            self.hide_timer.start()
        else:
            self.hide_timer.stop()
            c.hide()
            c.setWindowFlags(Qt.Widget)
            c.setAttribute(Qt.WA_TranslucentBackground, False)
            c.set_overlay(False)
            c.setWindowOpacity(1.0)
            self._root.addWidget(c)
            c.setVisible(not self.is_pip)
            self._ctrl_visible = True

    def _place_overlay(self):
        if not self.is_fullscreen:
            return
        scr = self.window().screen().geometry()
        h = 120
        self.controls.setGeometry(scr.left(), scr.bottom() - h + 1, scr.width(), h)
        self.controls.setWindowOpacity(1.0)
        self.controls.show()
        self._ctrl_visible = True

    def _autohide(self):
        cur = QCursor.pos()
        if cur != self._last_cursor:
            self._last_cursor = cur
            self._last_move = time.time()
        idle = time.time() - self._last_move
        c = self.controls
        over = c.isVisible() and c.geometry().contains(cur)
        want = idle < 2.0 or over or self.get_prop("pause", False)
        if want and not self._ctrl_visible:
            self._ctrl_visible = True
            c.show()
            self._fade(c, 0.0, 1.0)
        elif not want and self._ctrl_visible:
            self._ctrl_visible = False
            self.thumb_popup.hide()
            self._fade(c, 1.0, 0.0, hide=True)

    def _fade(self, w, a, b, hide=False):
        if not theme.motion:
            w.setWindowOpacity(b)
            if hide:
                w.hide()
            return
        an = QVariantAnimation(w, startValue=a, endValue=b, duration=theme.dur(220))
        an.valueChanged.connect(w.setWindowOpacity)
        if hide:
            an.finished.connect(lambda: (w.hide() if not self._ctrl_visible else None))
        an.start()

    def set_pip_mode(self, on: bool):
        self.is_pip = on
        self.top.setVisible(not on)
        self.controls.setVisible(not on)

    def drop_file(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        if ext in SUB_EXT and self.player and self.current_url:
            self.add_sub(path)
            return True
        return False

    def shutdown(self):
        self._save_position()
        winutil.keep_awake(False)
        self._restore_refresh()
        self._close_turbo()
        if self.player:
            try:
                self.player.terminate()
            except Exception:
                pass
            self.player = None


class RemoteDialog(QDialog):
    """QR da inquadrare col telefono: si apre il telecomando di NOVA (stessa rete Wi-Fi)."""

    def __init__(self, parent, url):
        super().__init__(parent)
        self.setWindowTitle("Telecomando dal telefono")
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 20)
        v.setSpacing(12)
        v.addWidget(label("Telecomando dal telefono", "sectionTitle"))
        v.addWidget(label("Inquadra il codice con la fotocamera del telefono (stesso Wi-Fi del PC).", "muted", wrap=True))
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        pm = qr_pixmap(url, 260)
        if pm:
            qr.setPixmap(pm)
        else:
            qr.setText("(Per il QR serve il pacchetto qrcode: rilancia setup.bat)")
        v.addWidget(qr)
        u = label(url, "faint")
        u.setTextInteractionFlags(Qt.TextSelectableByMouse)
        u.setAlignment(Qt.AlignCenter)
        v.addWidget(u)
        v.addWidget(label("Se il telefono non si collega: quando Windows chiede, consenti a NOVA l'accesso alle "
                          "reti private.", "faint", wrap=True))
        b = button("Chiudi", "primary", None, self.accept)
        v.addWidget(b, 0, Qt.AlignRight)


def qr_pixmap(text, size=260):
    try:
        import qrcode
    except Exception:
        return None
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    img = QImage(n, n, QImage.Format_RGB32)
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            img.setPixel(x, y, 0xFF000000 if on else 0xFFFFFFFF)
    return QPixmap.fromImage(img.scaled(size, size, Qt.KeepAspectRatio, Qt.FastTransformation))

