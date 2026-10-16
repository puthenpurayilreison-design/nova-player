"""Ctrl+K: cerca un film della libreria o un comando e premi Invio."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPoint, QVariantAnimation
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QFrame

from . import icons
from .catalog import item_title
from .config import history
from .theme import theme
from .widgets import label, ease


class CommandPalette(QDialog):
    def __init__(self, win):
        super().__init__(win, Qt.FramelessWindowHint | Qt.Popup)
        self.win = win
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        box = QFrame()
        box.setObjectName("pal")
        box.setStyleSheet(f"#pal{{background:{theme.surface2};border:1px solid {theme.border};border-radius:16px;}}"
                          f"QListWidget{{background:transparent;border:none;outline:none;}}"
                          f"QListWidget::item{{padding:9px 10px;border-radius:9px;color:{theme.text};}}"
                          f"QListWidget::item:selected{{background:{theme.accent_soft};color:{theme.text};}}")
        outer.addWidget(box)
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 12, 12, 10)
        v.setSpacing(8)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Search a movie or a command…  (Enter to open, Esc to close)")
        self.q.textChanged.connect(self.fill)
        self.q.installEventFilter(self)
        v.addWidget(self.q)
        self.list = QListWidget()
        self.list.itemActivated.connect(lambda it: self.run(it))
        self.list.itemClicked.connect(lambda it: self.run(it))
        v.addWidget(self.list)
        v.addWidget(label("↑ ↓ to choose · Enter to open", "faint"))
        w = min(640, win.width() - 80)
        self.setFixedSize(w, 430)
        g = win.geometry()
        self.move(g.x() + (g.width() - w) // 2, g.y() + 90)
        self.fill()
        if theme.motion:
            self.setWindowOpacity(0.0)
            a = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=theme.dur(150))
            a.setEasingCurve(ease())
            a.valueChanged.connect(self.setWindowOpacity)
            a.start()
        QTimer.singleShot(0, self.q.setFocus)

    def commands(self):
        w = self.win
        p = w.player
        clip = QApplication.clipboard().text().strip()
        cmds = [
            ("Open file…", "folder", lambda: (w.go("player"), p.open_files())),
            ("Add links to the library…", "plus", lambda: (w.go("library"), w.page("library").add_links())),
        ]
        if clip.startswith(("http://", "https://", "magnet:")):
            cmds.insert(0, ("Play the copied link", "link", lambda: w.play(clip) if not clip.startswith("magnet:")
                            else w.download(clip)))
            cmds.insert(1, ("Download the copied link", "download", lambda: w.download(clip)))
        if p.player and not p.get_prop("idle-active", True):
            cmds += [("Cinema mode", "film", lambda: w.set_cinema(not p.is_cinema)),
                     ("Full screen", "fullscreen", lambda: w.set_fullscreen(not p.is_fullscreen)),
                     ("Video statistics", "info", p.toggle_stats),
                     ("Sound: Cinema in headphones", "audio", lambda: p.set_audio_profile("headphones")),
                     ("Sound: Clear dialogue", "audio", lambda: p.set_audio_profile("dialogue")),
                     ("Sound: Night volume", "audio", lambda: p.set_audio_profile("night")),
                     ("Sound: Original", "audio", lambda: p.set_audio_profile("normal"))]
        for key, name, ic in (("home", "Home", "nova"), ("player", "Player", "player"), ("stream", "Stream", "globe"),
                              ("downloads", "Download", "download"), ("torrent", "Torrent", "magnet"),
                              ("library", "Library", "library"), ("settings", "Settings", "settings")):
            cmds.append((f"Go to {name}", ic, lambda k=key: w.go(k)))
        return cmds

    def fill(self, *_):
        q = self.q.text().lower().strip()
        self.list.clear()
        words = q.split()

        def match(text):
            t = text.lower()
            return all(x in t for x in words)
        films = [i for i in history.items if not q or match(item_title(i) + " " + (i.get("title") or ""))]
        for it in films[:8 if not q else 30]:
            li = QListWidgetItem(icons.icon("film" if it.get("kind") != "link" else "link", theme.text2, 18),
                                 item_title(it))
            li.setData(Qt.UserRole, ("item", it))
            self.list.addItem(li)
        for name, ic, fn in self.commands():
            if not q or match(name):
                li = QListWidgetItem(icons.icon(ic, theme.accent, 18), name)
                li.setData(Qt.UserRole, ("cmd", fn))
                self.list.addItem(li)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, e):
        if obj is self.q and e.type() == e.Type.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it:
                    self.run(it)
                return True
            if k == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, e)

    def run(self, li):
        kind, val = li.data(Qt.UserRole)
        self.close()
        if kind == "item":
            QTimer.singleShot(0, lambda: self.win.play_item(val))
        else:
            QTimer.singleShot(0, val)
