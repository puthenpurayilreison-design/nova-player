"""Impostazioni: menu delle sezioni, ricerca, spiegazioni chiare e ripristino del valore consigliato."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer, QUrl, QRectF, QPointF, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QKeySequence, QDesktopServices, QPainter, QPainterPath, QFont
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLineEdit, QSpinBox,
                               QDoubleSpinBox, QPlainTextEdit, QFileDialog, QColorDialog, QKeySequenceEdit,
                               QGridLayout, QAbstractButton, QFrame, QApplication)

from . import winutil, icons
from .config import settings, DATA, DEFAULTS, VIDEO_EXT, AUDIO_EXT, FROZEN, VERSION, tool
from . import audio as snd
from .theme import theme, PRESETS
from .widgets import Card, label, button, Segmented, Toggle, divider, IconButton, Pill

ACCENTS = ["#22D3EE", "#7C6CFF", "#3EA6FF", "#00C2A8", "#3DD68C", "#F5B83D", "#FF7A45", "#FF7EB6", "#E5E5EA"]
SHORTCUT_NAMES = {
    "play_pause": "Play / Pause", "seek_fwd": "Forward 5 s", "seek_back": "Back 5 s",
    "seek_fwd_big": "Forward 1 min", "seek_back_big": "Back 1 min", "fullscreen": "Full screen",
    "mute": "Mute", "stats": "Statistics", "next_audio": "Next audio track",
    "next_sub": "Next subtitles", "speed_up": "Faster", "speed_down": "Slower",
    "ab_loop": "Loop A-B", "pip": "Picture-in-picture", "cinema": "Cinema mode", "cam": "Improve low-quality video",
    "sub_search": "Search the subtitles",
}
SECTIONS = [("appearance", "palette", "Appearance"), ("player", "player", "Player"), ("audio", "audio", "Audio"), ("library", "library", "Library"),
            ("stream", "globe", "Streaming"),
            ("downloads", "download", "Downloads"), ("torrent", "magnet", "Torrent"),
            ("shortcuts", "keyboard", "Shortcuts"), ("system", "wrench", "System")]
NOWIN = 0x08000000 if sys.platform == "win32" else 0


class Swatch(QAbstractButton):
    def __init__(self, color, selected, parent=None):
        super().__init__(parent)
        self.color = color
        self.sel = selected
        self.setFixedSize(30, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.sel:
            p.setPen(QColor(theme.text))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(1, 1, 28, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self.color))
        p.drawEllipse(5, 5, 20, 20)


class ThemeCard(QAbstractButton):
    """Anteprima in miniatura di un tema (finestra con sidebar, card e accento)."""

    def __init__(self, key, selected):
        super().__init__()
        self.key = key
        self.pr = PRESETS[key]
        self.sel = selected
        self.setFixedSize(114, 96)
        self.setCursor(Qt.PointingHandCursor)
        self._h = 0.0
        self._a = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=160)
        self._a.valueChanged.connect(lambda v: (setattr(self, "_h", v), self.update()))

    def enterEvent(self, e):
        self._a.setDirection(QVariantAnimation.Forward)
        self._a.start()

    def leaveEvent(self, e):
        self._a.setDirection(QVariantAnimation.Backward)
        self._a.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pr = self.pr
        r = QRectF(4, 4, self.width() - 8, 62)
        lift = -2 * self._h
        r.translate(0, lift)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.fillPath(path, QColor(pr["bg"]))
        p.save()
        p.setClipPath(path)
        p.fillRect(QRectF(r.left(), r.top(), 30, r.height()), QColor(pr["sidebar"]))
        p.fillRect(QRectF(r.left() + 6, r.top() + 14, 18, 6), QColor(pr["accent"]))
        for i in range(3):
            p.fillRect(QRectF(r.left() + 6, r.top() + 26 + i * 10, 18, 4), QColor(pr["surface3"]))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(pr["surface"]))
        p.drawRoundedRect(QRectF(r.left() + 38, r.top() + 8, r.width() - 46, 20), 5, 5)
        p.drawRoundedRect(QRectF(r.left() + 38, r.top() + 34, r.width() - 46, 20), 5, 5)
        p.setBrush(QColor(pr["accent"]))
        p.drawRoundedRect(QRectF(r.left() + 44, r.top() + 16, (r.width() - 58) * 0.6, 4), 2, 2)
        p.setBrush(QColor(pr["text3"]))
        p.drawRoundedRect(QRectF(r.left() + 44, r.top() + 42, (r.width() - 58) * 0.8, 4), 2, 2)
        p.restore()
        pen = QColor(theme.accent) if self.sel else QColor(theme.border)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 11, 11) if self.sel else p.drawRoundedRect(r, 10, 10)
        f = QFont(self.font())
        f.setWeight(QFont.DemiBold if self.sel else QFont.Normal)
        p.setFont(f)
        p.setPen(QColor(theme.text if self.sel else theme.text2))
        p.drawText(QRectF(0, 70, self.width(), 22), Qt.AlignCenter, pr["name"])


def spin(val, lo, hi, step=1, suffix="", dbl=False):
    s = QDoubleSpinBox() if dbl else QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(140)
    s.setAlignment(Qt.AlignRight)
    return s


def fmt_default(v):
    if isinstance(v, bool):
        return "On" if v else "Off"
    labels = {"midnight": "Midnight", "full": "Full", "normal": "Normal", "max": "Maximum", "ratio": "Ratio",
              "2160": "4K", "mkv": "MKV"}
    return labels.get(str(v), str(v) if len(str(v)) < 40 else str(v)[:37] + "…")


class Row(QWidget):
    """Riga impostazione: titolo, spiegazione, controllo e ↺ per tornare al valore consigliato."""

    def __init__(self, page, title, desc, ctrl, sec=None, key=None, wide=False):
        super().__init__()
        self.page, self.sec, self.key = page, sec, key
        self.search_text = f"{title} {desc}".lower()
        lay = QVBoxLayout(self) if wide else QHBoxLayout(self)
        lay.setContentsMargins(theme.s(20), theme.s(13), theme.s(14), theme.s(13))
        lay.setSpacing(theme.s(10) if wide else theme.s(16))
        v = QVBoxLayout()
        v.setSpacing(3)
        t = label(title)
        t.setStyleSheet("font-weight:600;")
        v.addWidget(t)
        if desc:
            d = label(desc, "faint", wrap=True)
            d.setMaximumWidth(560)
            v.addWidget(d)
        lay.addLayout(v, 1)
        r = QHBoxLayout()
        r.setSpacing(6)
        r.addWidget(ctrl, 0, Qt.AlignRight | Qt.AlignVCenter)
        self.reset = IconButton("retry", "", 30, 15)
        self.reset.clicked.connect(self._reset)
        r.addWidget(self.reset)
        if wide:
            r.insertStretch(0)
        lay.addLayout(r)
        self.refresh_reset()

    def refresh_reset(self):
        show = self.sec is not None and settings.get(self.sec, self.key) != DEFAULTS[self.sec][self.key]
        self.reset.setVisible(show)
        if self.sec:
            self.reset.setToolTip(f"Restore the recommended value: {fmt_default(DEFAULTS[self.sec][self.key])}")
        if not show and self.sec:
            # tiene lo spazio, così i controlli restano allineati
            self.reset.setVisible(False)

    def _reset(self):
        self.page.set(self.sec, self.key, DEFAULTS[self.sec][self.key], rebuild=True)


class NavButton(QAbstractButton):
    def __init__(self, key, icon_name, text):
        super().__init__()
        self.key, self.icon_name, self.text_ = key, icon_name, text
        self.setCheckable(True)
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self._hov = False

    def enterEvent(self, e):
        self._hov = True
        self.update()

    def leaveEvent(self, e):
        self._hov = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.isChecked() or self._hov:
            c = QColor(theme.accent) if self.isChecked() else QColor(theme.text)
            c.setAlphaF(0.16 if self.isChecked() else 0.05)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(r, 9, 9)
        col = theme.accent if self.isChecked() else theme.text2
        p.drawPixmap(QPointF(12, (r.height() - 18) / 2), icons.pixmap(self.icon_name, col, 18))
        f = QFont(self.font())
        if self.isChecked():
            f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.text if self.isChecked() else theme.text2))
        p.drawText(QRectF(40, 0, r.width() - 44, r.height()), Qt.AlignVCenter, self.text_)


class SettingsPage(QWidget):
    appearance_changed = Signal()
    changed = Signal(str)
    toast = Signal(str, str, str)
    open_firewall = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # menu sezioni
        nav = QWidget()
        nav.setFixedWidth(230)
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(theme.s(20), theme.s(26), theme.s(8), theme.s(20))
        nv.setSpacing(4)
        nv.addWidget(label("Settings", "pageTitle"))
        nv.addSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search a setting…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        nv.addWidget(self.search)
        nv.addSpacing(8)
        self.navs: dict[str, NavButton] = {}
        for key, ic, name in SECTIONS:
            b = NavButton(key, ic, name)
            b.clicked.connect(lambda _=False, k=key: self.scroll_to(k))
            self.navs[key] = b
            nv.addWidget(b)
        nv.addStretch()
        nv.addWidget(label(f"NOVA {VERSION}", "faint"))
        outer.addWidget(nav)
        # contenuto
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_nav)
        outer.addWidget(self.scroll, 1)
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.scroll.verticalScrollBar().setValue(int(v)))
        self.build()

    # ---------- costruzione ----------
    def build(self):
        pos = self.scroll.verticalScrollBar().value()
        host = QWidget()
        self.root = QVBoxLayout(host)
        m = theme.s(28)
        self.root.setContentsMargins(theme.s(12), m, m, m)
        self.root.setSpacing(theme.s(12))
        self.sections: dict[str, tuple] = {}
        self.rows: list[Row] = []
        for key, ic, name in SECTIONS:
            getattr(self, f"_s_{key}")(self._section(key, ic, name))
        self.no_results = label("No settings found.", "muted")
        self.no_results.setAlignment(Qt.AlignCenter)
        self.no_results.hide()
        self.root.addWidget(self.no_results)
        self.root.addStretch()
        old = self.scroll.takeWidget()
        self.scroll.setWidget(host)
        if old:
            old.deleteLater()
        QTimer.singleShot(0, self, lambda: self.scroll.verticalScrollBar().setValue(pos))
        self._filter(self.search.text())
        self._sync_nav()

    def _section(self, key, icon_name, title):
        head = QWidget()
        h = QHBoxLayout(head)
        h.setContentsMargins(4, theme.s(14), 0, 2)
        il = label("")
        il.setPixmap(icons.pixmap(icon_name, theme.accent, 20))
        h.addWidget(il)
        h.addWidget(label(title, "sectionTitle"))
        h.addStretch()
        card = Card()
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 4, 0, 4)
        v.setSpacing(0)
        self.root.addWidget(head)
        self.root.addWidget(card)
        self.sections[key] = (head, card, v)
        return v

    def add(self, v, title, desc, ctrl, sec=None, key=None, wide=False):
        if v.count():
            v.addWidget(divider())
        r = Row(self, title, desc, ctrl, sec, key, wide)
        self.rows.append(r)
        v.addWidget(r)
        return ctrl

    # ---------- navigazione e ricerca ----------
    def scroll_to(self, key):
        head = self.sections[key][0]
        target = max(0, head.y() - 6)
        sb = self.scroll.verticalScrollBar()
        self._anim.stop()
        self._anim.setDuration(max(1, theme.dur(380)))
        self._anim.setStartValue(float(sb.value()))
        self._anim.setEndValue(float(min(target, sb.maximum())))
        self._anim.start()
        for k, b in self.navs.items():
            b.setChecked(k == key)

    def _sync_nav(self, *_):
        if self._anim.state() == QVariantAnimation.Running:
            return
        y = self.scroll.verticalScrollBar().value() + 40
        cur = SECTIONS[0][0]
        for key, _, _ in SECTIONS:
            head = self.sections[key][0]
            if head.isVisible() and head.y() <= y:
                cur = key
        if self.scroll.verticalScrollBar().value() >= self.scroll.verticalScrollBar().maximum() - 4:
            vis = [k for k, _, _ in SECTIONS if self.sections[k][0].isVisible()]
            cur = vis[-1] if vis else cur
        for k, b in self.navs.items():
            b.setChecked(k == cur)

    def _filter(self, text):
        q = text.lower().strip()
        any_vis = False
        for key, _, name in SECTIONS:
            head, card, v = self.sections[key]
            rows = [r for r in self.rows if r.parent() is card]
            sec_match = q and q in name.lower()
            vis_rows = 0
            for i in range(v.count()):
                w = v.itemAt(i).widget()
                if isinstance(w, Row):
                    ok = not q or sec_match or q in w.search_text
                    w.setVisible(ok)
                    vis_rows += ok
            # i separatori seguono la riga successiva visibile
            prev_visible = False
            for i in range(v.count()):
                w = v.itemAt(i).widget()
                if isinstance(w, Row):
                    prev_visible = prev_visible or w.isVisibleTo(card)
                elif w is not None:
                    nxt = v.itemAt(i + 1).widget() if i + 1 < v.count() else None
                    w.setVisible(bool(prev_visible and nxt is not None and nxt.isVisibleTo(card)) or not q)
            show = vis_rows > 0 or not rows
            if q and not rows:
                show = sec_match
            head.setVisible(show)
            card.setVisible(show)
            any_vis |= show
        self.no_results.setVisible(not any_vis)

    # ---------- helper controlli ----------
    def set(self, sec, key, val, appearance=False, rebuild=False):
        settings.set(sec, key, val)
        if sec == "appearance" or appearance:
            self.appearance_changed.emit()     # la finestra ricrea le pagine con il nuovo stile
            return
        self.changed.emit(sec)
        if rebuild:
            QTimer.singleShot(0, self.build)
        else:
            for r in self.rows:
                if r.sec == sec and r.key == key:
                    r.refresh_reset()

    def seg(self, sec, key, opts, cast=str):
        s = Segmented(opts, str(settings.get(sec, key)))
        s.changed.connect(lambda v: self.set(sec, key, cast(v)))
        return s

    def tog(self, sec, key):
        t = Toggle(bool(settings.get(sec, key)))
        t.toggled.connect(lambda on: self.set(sec, key, on))
        return t

    def num(self, sec, key, lo, hi, step=1, suffix="", dbl=False):
        s = spin(settings.get(sec, key), lo, hi, step, suffix, dbl)
        t = QTimer(self, singleShot=True, interval=450)
        t.timeout.connect(lambda: self.set(sec, key, s.value()))
        s.valueChanged.connect(lambda _: t.start())
        return s

    def text(self, sec, key, placeholder="", password=False, width=280):
        e = QLineEdit(settings.get(sec, key))
        e.setPlaceholderText(placeholder)
        e.setFixedWidth(width)
        if password:
            e.setEchoMode(QLineEdit.Password)
        e.editingFinished.connect(lambda: self.set(sec, key, e.text().strip()))
        return e

    def folder(self, sec, key):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        cur = settings.get(sec, key)
        l = label(cur if len(cur) < 40 else "…" + cur[-38:], "muted")
        l.setToolTip(cur)
        b = button("Choose…", None, "folder")

        def pick():
            d = QFileDialog.getExistingDirectory(self, "Choose folder", settings.get(sec, key))
            if d:
                Path(d).mkdir(parents=True, exist_ok=True)
                self.set(sec, key, d, rebuild=True)
        b.clicked.connect(pick)
        h.addWidget(l)
        h.addWidget(b)
        return w

    def _toast_later(self, t, m, k):
        QTimer.singleShot(0, self, lambda: self.toast.emit(t, m, k))

    # ---------- sezioni ----------
    def _s_appearance(self, v):
        grid = QWidget()
        g = QHBoxLayout(grid)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(8)
        cur = settings.get("appearance", "theme")
        for k in PRESETS:
            c = ThemeCard(k, k == cur)
            c.clicked.connect(lambda _=False, k=k: self._pick_theme(k))
            g.addWidget(c)
        g.addStretch()
        self.add(v, "Theme", "Full app palette. The accent colour can be changed below.", grid,
                 "appearance", "theme", wide=True)
        sw = QWidget()
        h = QHBoxLayout(sw)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        acc = settings.get("appearance", "accent")
        for c in ACCENTS:
            s = Swatch(c, c.lower() == acc.lower())
            s.clicked.connect(lambda _=False, c=c: self.set("appearance", "accent", c))
            h.addWidget(s)
        custom = IconButton("plus", "Custom colour", 30, 16)

        def pick():
            col = QColorDialog.getColor(QColor(acc), self, "Accent colour")
            if col.isValid():
                self.set("appearance", "accent", col.name())
        custom.clicked.connect(pick)
        h.addWidget(custom)
        self.add(v, "Accent colour", "Buttons, bars and highlighted details.", sw, "appearance", "accent")
        self.add(v, "Animations", "Full: richer, with bounce. Minimal: quick fades only. None: everything instant (recommended on slow PCs).",
                 self.seg("appearance", "animations", [("full", "Full"), ("balanced", "Balanced"),
                                                       ("minimal", "Minimal"), ("none", "None")]),
                 "appearance", "animations")
        self.add(v, "Startup animation", "The NOVA logo lights up for a second when you open the app (not shown when you open a file directly).", self.tog("appearance", "intro"), "appearance", "intro")
        self.add(v, "Density", "How much space there is between elements.",
                 self.seg("appearance", "density", [("compact", "Compact"), ("normal", "Normal"),
                                                    ("spacious", "Spacious")]), "appearance", "density")
        self.add(v, "Text size", "",
                 self.seg("appearance", "font_scale", [("0.9", "90%"), ("1.0", "100%"), ("1.1", "110%"),
                                                       ("1.25", "125%")], float), "appearance", "font_scale")

    def _pick_theme(self, k):
        settings.set("appearance", "accent", PRESETS[k]["accent"], notify=False)
        self.set("appearance", "theme", k)

    def _s_player(self, v):
        self.add(v, "Hardware decoding", "The GPU decodes the video: essential for 4K HEVC/AV1 without stutter.",
                 self.tog("player", "hwdec"), "player", "hwdec")
        self.add(v, "Smooth motion", "Aligns the video to the monitor refresh (60/144 Hz): no micro-stutter and no judder in 24 fps movies.", self.tog("player", "smooth"), "player", "smooth")
        self.add(v, "Automatic refresh for movies", "Switches the monitor to an exact multiple of the movie's fps (e.g. 144 Hz for 24 fps): perfectly smooth motion. Each refresh change turns the screen black for 1-2 seconds: «Full screen only» does it only when entering and leaving a full-screen movie, never when you close the app or work in a window.",
                 self.seg("player", "refresh_mode", [("fullscreen", "Full screen only"), ("always", "Always"),
                                                     ("off", "Never")]), "player", "refresh_mode")
        self.add(v, "RTX Super Resolution", "On small videos (720p or less) the NVIDIA GPU upscales them with AI: sharper on the monitor. Also turn on NVIDIA Control Panel › Adjust video image settings › RTX video enhancement › Super Resolution.", self.tog("player", "rtx_vsr"), "player", "rtx_vsr")
        self.add(v, "Colours from the movie", "The progress bar and the play button take the colour of the movie you're watching.", self.tog("player", "film_colors"), "player", "film_colors")
        self.add(v, "Picture quality", "Maximum: sharpest scaler and debanding. If the video stutters, try Balanced.", self.seg("player", "quality", [("max", "Maximum"), ("balanced", "Balanced"),
                                                               ("saver", "Saver")]), "player", "quality")
        self.add(v, "Resume where you left off", "Every video restarts from the point where you left it.",
                 self.tog("player", "resume"), "player", "resume")
        self.add(v, "Preferred audio languages", "Comma-separated codes, in order of preference (e.g. eng,ita).",
                 self.text("player", "audio_lang", "eng,ita"), "player", "audio_lang")
        self.add(v, "Preferred subtitle languages", "Leave empty to not turn them on automatically.",
                 self.text("player", "sub_lang", "ita"), "player", "sub_lang")
        self.add(v, "Subtitle size", "", self.num("player", "sub_size", 20, 90), "player", "sub_size")
        cw = QWidget()
        ch = QHBoxLayout(cw)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(4)
        for c in ("#FFFFFF", "#FFE66D", "#B8F2E6", "#FFD1DC"):
            s = Swatch(c, settings.get("player", "sub_color").upper() == c)
            s.clicked.connect(lambda _=False, c=c: self.set("player", "sub_color", c, rebuild=True))
            ch.addWidget(s)
        self.add(v, "Subtitle colour", "", cw, "player", "sub_color")
        self.add(v, "Background behind subtitles", "Dark box to read them better on bright scenes.",
                 self.tog("player", "sub_background"), "player", "sub_background")

    def _s_audio(self, v):
        from PySide6.QtWidgets import QComboBox
        cb = QComboBox()
        cb.setFixedWidth(260)
        cur = settings.get("audio", "profile")
        for k, name, desc in snd.PROFILES:
            cb.addItem(name, k)
            cb.setItemData(cb.count() - 1, desc, Qt.ToolTipRole)
        cb.setCurrentIndex(max(0, cb.findData(cur)))
        cb.currentIndexChanged.connect(lambda i: self.set("audio", "profile", cb.itemData(i)))
        self.add(v, "Default sound", "Automatic: Cinema in headphones on headphones, clearer voices on monitor speakers, original on everything else. From the player's Audio panel you can pick a different one for each output, and it's remembered.", cb, "audio", "profile")
        self.add(v, "Exclusive output", "NOVA uses the sound card on its own: it skips the Windows mixer and effects like FxSound (original sound, minimal latency). While you watch, other apps are muted.",
                 self.tog("audio", "exclusive"), "audio", "exclusive")
        self.add(v, "Subtitles even with English audio", "On: English subtitles show up even when the audio is already English. Off: only when the audio is in another language.",
                 self.tog("player", "subs_with_english_audio"), "player", "subs_with_english_audio")
        self.add(v, "Remember for each movie", "Audio track, subtitles, subtitle delay and volume chosen for a movie are restored when you reopen it.",
                 self.tog("player", "remember_per_film"), "player", "remember_per_film")
        self.add(v, "Same volume across movies", "NOVA measures the loudness of every movie (EBU R128 standard) and brings it to the same level: no more very quiet movies and others that shout. It adjusts gently, without jumps, and remembers the value for each movie.", self.tog("player", "loudness"), "player", "loudness")
        self.add(v, "Smart resume", "When you reopen a movie it restarts a few seconds before where you were (3 s after a short pause, up to 25 s after days), so you pick up the thread.",
                 self.tog("player", "smart_resume"), "player", "smart_resume")

    def _s_library(self, v):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        e = QLineEdit(settings.get("library", "tmdb_key"))
        e.setEchoMode(QLineEdit.Password)
        e.setPlaceholderText("API Key or Read Access Token")
        e.setFixedWidth(240)
        b = button("Checking", None, "check")

        def save():
            from .tmdb import check_key
            k = e.text().strip()
            if not k:
                self.set("library", "tmdb_key", "")
                return
            ok, msg = check_key(k)
            if ok:
                self.set("library", "tmdb_key", k)
            self.toast.emit("TMDB", msg, "ok" if ok else "err")
        b.clicked.connect(save)
        e.returnPressed.connect(save)
        link = button("Create key", "ghost", "globe",
                      lambda: QDesktopServices.openUrl(QUrl("https://www.themoviedb.org/settings/api")))
        for x in (e, b, link):
            h.addWidget(x)
        self.add(v, "TMDB key", "Free: account on themoviedb.org › Settings › API. Used for official posters and «Name (year)» titles in Library and Home.", w, "library", "tmdb_key")
        self.add(v, "Title language", "English keeps the original titles of Indian movies; other languages use local titles when they exist.",
                 self.seg("library", "tmdb_lang", [("en-US", "English"), ("it-IT", "Italian")]),
                 "library", "tmdb_lang")
        self.add(v, "Detect series intros", "Compares two episodes in the same folder and shows «Skip intro». Also uses the file's chapters when present.", self.tog("library", "detect_intro"),
                 "library", "detect_intro")
        self.add(v, "Skip the intro automatically", "Instead of the button, the intro is skipped automatically.",
                 self.tog("library", "skip_intro_auto"), "library", "skip_intro_auto")
        self.add(v, "Next episode", "At the end of an episode it suggests the next one (same folder or Library) and starts it after 10 seconds.", self.tog("library", "next_episode"),
                 "library", "next_episode")

    def _s_stream(self, v):
        self.add(v, "Stream Turbo", "Downloads links with several connections at once: full speed, near-instant seeking and, if the link expires, it restarts from the same point with a new link.",
                 self.tog("stream", "turbo"), "stream", "turbo")
        self.add(v, "Stream Turbo connections", "16 recommended. If a website blocks the stream, try 8 or 4.",
                 self.num("stream", "turbo_connections", 1, 16), "stream", "turbo_connections")
        self.add(v, "Wi-Fi streaming mode", "While you watch a movie from the network, Windows stops scanning for Wi-Fi networks in the background (it freezes the connection for a moment every minute) and uses the adapter's streaming mode. Everything goes back to normal when you stop watching.",
                 self.tog("downloads", "wifi_streaming"), "downloads", "wifi_streaming")
        self.add(v, "Maximum quality", "For HLS/DASH and video pages. 4K needs at least a 25 Mbit/s connection.",
                 self.seg("stream", "max_height", [("2160", "4K"), ("1440", "1440p"), ("1080", "1080p"),
                                                   ("720", "720p")], int), "stream", "max_height")
        self.add(v, "Forward cache", "Memory for the buffer. With the recommended value and 16 GB of RAM NOVA uses 2 GB (about 3 minutes of 4K).",
                 self.num("stream", "cache_mb", 64, 8192, 64, " MB"), "stream", "cache_mb")
        self.add(v, "Back cache", "To go back without downloading again.",
                 self.num("stream", "back_cache_mb", 0, 4096, 32, " MB"), "stream", "back_cache_mb")
        self.add(v, "Read-ahead", "Seconds of video downloaded in advance.",
                 self.num("stream", "readahead_s", 5, 600, 5, " s"), "stream", "readahead_s")
        self.add(v, "Maximum cache duration", "", self.num("stream", "cache_secs", 10, 3600, 10, " s"),
                 "stream", "cache_secs")
        self.add(v, "User-Agent", "Only if a website blocks the player. Empty = default.",
                 self.text("stream", "user_agent", "default"), "stream", "user_agent")
        self.add(v, "HTTP proxy", "e.g. http://127.0.0.1:8080", self.text("stream", "proxy", "none"),
                 "stream", "proxy")

    def _s_downloads(self, v):
        self.add(v, "Download folder", "", self.folder("downloads", "dir"), "downloads", "dir")
        self.add(v, "Connections per file", "NOVA splits the file into parts downloaded together. If a server refuses too many connections, it retries by itself with fewer.", self.num("downloads", "connections", 1, 32),
                 "downloads", "connections")
        self.add(v, "Parallel downloads", "How many files to download at the same time.",
                 self.num("downloads", "parallel", 1, 10), "downloads", "parallel")
        self.add(v, "Speed limit", "0 = unlimited.", self.num("downloads", "limit_kb", 0, 10_000_000, 256, " KB/s"),
                 "downloads", "limit_kb")
        self.add(v, "Organise by type", "Moves finished files into Video / Audio / Other.",
                 self.tog("downloads", "organize"), "downloads", "organize")
        self.add(v, "Detect copied links", "When you copy a link or a magnet, NOVA suggests what to do with it.",
                 self.tog("downloads", "clipboard"), "downloads", "clipboard")
        self.add(v, "Movie first", "While you watch a movie from the network, other downloads and torrents slow down by themselves, so the movie never buffers.", self.tog("downloads", "player_priority"),
                 "downloads", "player_priority")
        self.add(v, "Minimise to tray on close", "With active downloads, closing the window doesn't stop them.",
                 self.tog("downloads", "tray_on_close"), "downloads", "tray_on_close")

    def _s_torrent(self, v):
        self.add(v, "Torrent folder", "", self.folder("torrent", "dir"), "torrent", "dir")
        b = button("Open port", "primary", "check", self.open_firewall.emit)
        self.add(v, "Firewall port", "Lets peers connect to you too: it's what boosts speed the most. Windows asks for confirmation once.", b)
        self.add(v, "Sequential download", "Off = maximum speed. It turns on by itself when you press ▶ or use Instant link.", self.tog("torrent", "sequential"), "torrent", "sequential")
        self.add(v, "Seeding after download", "How much to share before stopping.",
                 self.seg("torrent", "seed_mode", [("off", "No"), ("ratio", "Ratio"), ("time", "Time")]),
                 "torrent", "seed_mode")
        self.add(v, "Maximum ratio", "1.0 = you upload as much as you downloaded.",
                 self.num("torrent", "seed_ratio", 0.1, 50, 0.1, "", dbl=True), "torrent", "seed_ratio")
        self.add(v, "Maximum seeding time", "", self.num("torrent", "seed_minutes", 1, 10080, 10, " min"),
                 "torrent", "seed_minutes")
        self.add(v, "Download limit", "0 = unlimited.",
                 self.num("torrent", "down_limit_kb", 0, 10_000_000, 256, " KB/s"), "torrent", "down_limit_kb")
        self.add(v, "Upload limit", "0 = unlimited. Limiting it too much slows downloads too.",
                 self.num("torrent", "up_limit_kb", 0, 10_000_000, 64, " KB/s"), "torrent", "up_limit_kb")
        self.add(v, "Listening port", "Change it only if your provider blocks 6881.",
                 self.num("torrent", "port", 1024, 65535), "torrent", "port")
        self.add(v, "Encryption", "Encrypts connections with peers when possible.",
                 self.tog("torrent", "encryption"), "torrent", "encryption")

    def _s_shortcuts(self, v):
        g = QWidget()
        grid = QGridLayout(g)
        grid.setContentsMargins(theme.s(20), theme.s(14), theme.s(20), theme.s(14))
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        for n, (k, name) in enumerate(SHORTCUT_NAMES.items()):
            r, c = divmod(n, 2)
            grid.addWidget(label(name, "muted"), r, c * 2)
            ed = QKeySequenceEdit(QKeySequence(settings.get("shortcuts", k)))
            ed.setMaximumSequenceLength(1)
            ed.setFixedWidth(150)
            ed.editingFinished.connect(lambda k=k, ed=ed: self.set("shortcuts", k, ed.keySequence().toString()))
            grid.addWidget(ed, r, c * 2 + 1)
        row = Row(self, "Keys", "Click a field and press the new key. Double-click on the video: full screen · wheel: volume · Esc: exit.", QWidget())
        self.rows.append(row)
        v.addWidget(row)
        v.addWidget(g)
        v.addWidget(divider())

        def reset():
            for k, val in DEFAULTS["shortcuts"].items():
                settings.set("shortcuts", k, val, notify=False)
            self.changed.emit("shortcuts")
            QTimer.singleShot(0, self.build)
        self.add(v, "Reset shortcuts", "Back to the default keys (VLC/mpv style).",
                 button("Reset", None, "retry", reset))

    def _s_system(self, v):
        from .config import REPO_URL, DONATE_URL, CRYPTO
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        gh = button("GitHub", None, "globe", lambda: QDesktopServices.openUrl(QUrl(REPO_URL)))
        self.add(v, f"NOVA {VERSION}", "Free and open source (GPL-3.0 license). Code, news and bug reports on GitHub.", gh)
        if DONATE_URL:
            d = button("Support NOVA", "primary", "sparkle", lambda: QDesktopServices.openUrl(QUrl(DONATE_URL)))
            self.add(v, "Do you like NOVA?", "It's free and ad-free: if you like, buy me a coffee to help it grow.", d)
        for name, addr in (CRYPTO or {}).items():
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.addWidget(button("Copy", None, "clipboard",
                                lambda _=False, a=addr: (QApplication.clipboard().setText(a),
                                                         self.toast.emit("Address copied", a, "ok"))))
            rh.addWidget(button("QR", None, "phone", lambda _=False, n=name, a=addr: self._show_qr(n, a)))
            self.add(v, f"Donate in {name}", addr, row)
        self.add(v, "Credits", "This product uses the TMDB API but is not endorsed or certified by TMDB. Video engine mpv, ffmpeg, aria2, libtorrent, yt-dlp, Qt: thanks to their authors.",
                 label("TMDB", "faint"))
        b = button("Register", None, "check")
        b.clicked.connect(lambda: self.toast.emit("Windows integration",
                                                  winutil.register_associations(VIDEO_EXT, AUDIO_EXT), "ok"))
        self.add(v, "Open with NOVA", "NOVA in 'Open with', in the right-click menu, for magnet links and .torrent files.", b)
        t = Toggle(winutil.is_autostart())
        t.toggled.connect(lambda on: winutil.set_autostart(on))
        self.add(v, "Start with Windows", "Starts in the tray, so downloads resume by themselves.", t)
        self.add(v, "Update components", "Downloads the latest versions of mpv, aria2, ffmpeg and yt-dlp. Applied at the next start.", button("Update", None, "retry", self._update_components))
        self.add(v, "Update yt-dlp", "Do it if a video website stops working.",
                 button("Update", None, "retry", self._update_ytdlp))
        w = QWidget()
        wv = QVBoxLayout(w)
        wv.setContentsMargins(0, 0, 0, 0)
        ed = QPlainTextEdit(settings.get("advanced", "mpv_conf"))
        ed.setPlaceholderText("interpolation=yes\ntscale=oversample")
        ed.setFixedHeight(96)
        wv.addWidget(ed)
        ap = button("Apply", None, "check", lambda: self.set("advanced", "mpv_conf", ed.toPlainText()))
        rr = QHBoxLayout()
        rr.addStretch()
        rr.addWidget(ap)
        wv.addLayout(rr)
        self.add(v, "Custom mpv options", "For experts: one per line, mpv.conf format.", w,
                 "advanced", "mpv_conf", wide=True)
        row = QWidget()
        rh = QHBoxLayout(row)
        rh.setContentsMargins(0, 0, 0, 0)

        def exp():
            f, _ = QFileDialog.getSaveFileName(self, "Export settings", "nova-settings.json", "JSON (*.json)")
            if f:
                settings.export(f)
                self.toast.emit("Settings exported", f, "ok")

        def imp():
            f, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
            if f:
                try:
                    settings.import_(f)
                    self.changed.emit("*")
                    self.appearance_changed.emit()
                except Exception as ex:
                    self.toast.emit("Invalid file", str(ex), "err")

        def reset():
            settings.reset()
            self.changed.emit("*")
            self.appearance_changed.emit()
        rh.addWidget(button("Export", None, "up", exp))
        rh.addWidget(button("Import", None, "down", imp))
        rh.addWidget(button("Reset everything", "danger", "retry", reset))
        self.add(v, "Settings backup", "Export to a file, import on another PC or go back to the recommended values.", row)
        row2 = QWidget()
        rh2 = QHBoxLayout(row2)
        rh2.setContentsMargins(0, 0, 0, 0)
        rh2.addWidget(button("Create backup", None, "up", self._backup))
        rh2.addWidget(button("Restore…", None, "down", self._restore))
        self.add(v, "Full backup", "A single .zip file with settings, library, resume points, audio choices per movie, posters and statistics. Useful if you change PC or reinstall Windows.", row2)
        self.add(v, "Logs and diagnostics", str(DATA / "logs"),
                 button("Open folder", None, "folder",
                        lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA / "logs")))))

    # ---------- backup completo ----------
    def _backup(self):
        import time as _t
        import zipfile
        f, _ = QFileDialog.getSaveFileName(self, "Full NOVA backup",
                                           f"NOVA-backup-{_t.strftime('%Y-%m-%d')}.zip", "Zip (*.zip)")
        if not f:
            return
        try:
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
                for name in ("settings.json", "history.json", "stats.json", "tmdb_cache.json", "downloads.json"):
                    p = DATA / name
                    if p.exists():
                        z.write(p, name)
                for folder in ("covers", "posters"):
                    for p in (DATA / folder).glob("*"):
                        if p.is_file():
                            z.write(p, f"{folder}/{p.name}")
            self.toast.emit("Backup created", f, "ok")
        except OSError as e:
            self.toast.emit("Backup failed", str(e), "err")

    def _restore(self):
        import zipfile
        f, _ = QFileDialog.getOpenFileName(self, "Restore NOVA backup", "", "Zip (*.zip)")
        if not f:
            return
        try:
            with zipfile.ZipFile(f) as z:
                names = z.namelist()
                if "settings.json" not in names and "history.json" not in names:
                    raise ValueError("this zip is not a NOVA backup")
                for n in names:
                    if n.startswith(("/", "..")) or ".." in n.split("/"):
                        continue
                    if n in ("settings.json", "history.json", "stats.json", "tmdb_cache.json", "downloads.json") \
                            or n.startswith(("covers/", "posters/")):
                        z.extract(n, DATA)
            self.toast.emit("Backup restored", "Restart NOVA to see everything as it was.", "ok")
        except Exception as e:
            self.toast.emit("Restore failed", str(e), "err")

    # ---------- aggiornamenti ----------
    def _show_qr(self, name, addr):
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        from .player import qr_pixmap
        d = QDialog(self)
        d.setWindowTitle(f"Donate in {name}")
        lay = QVBoxLayout(d)
        q = label("")
        q.setPixmap(qr_pixmap(addr, 260))
        lay.addWidget(q)
        t = label(addr, "faint", wrap=True)
        t.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(t)
        d.exec()

    def _update_components(self):
        from . import deps
        self.toast.emit("Updating components", "Downloading mpv, aria2, ffmpeg and yt-dlp in the background…", "info")

        def go():
            failed = deps.ensure(force=True, log=lambda *_: None)
            if failed:
                self._toast_later("Update incomplete", "Failed: " + ", ".join(failed), "err")
            else:
                self._toast_later("Components updated", "Restart NOVA to use the new versions.", "ok")
        threading.Thread(target=go, daemon=True).start()

    def _update_ytdlp(self):
        self.toast.emit("yt-dlp", "Updating…", "info")

        def go():
            ok = True
            exe = tool("yt-dlp")
            if Path(exe).is_absolute() and Path(exe).exists():
                r = subprocess.run([exe, "-U"], capture_output=True, text=True, creationflags=NOWIN)
                ok = r.returncode == 0
            if not FROZEN:
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"], capture_output=True,
                                   text=True, creationflags=NOWIN)
                ok = ok and r.returncode == 0
            self._toast_later("yt-dlp", "Updated." if ok else "Update failed.", "ok" if ok else "err")
        threading.Thread(target=go, daemon=True).start()
