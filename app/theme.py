"""Design system: colori, densità, durate delle animazioni e foglio di stile Qt."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from .config import settings


# Temi pronti: ogni preset definisce la palette; l'accento resta personalizzabile
PRESETS = {
    "midnight": {"name": "Midnight", "dark": True, "accent": "#22D3EE", "bg": "#0E0E11", "sidebar": "#121216",
                 "surface": "#17171C", "surface2": "#1F1F26", "surface3": "#2A2A33", "border": "#26262E",
                 "text": "#F2F2F5", "text2": "#A3A3AE", "text3": "#6B6B76"},
    "oled": {"name": "OLED nero", "dark": True, "accent": "#E5E5EA", "bg": "#000000", "sidebar": "#000000",
             "surface": "#0B0B0C", "surface2": "#141416", "surface3": "#1F1F22", "border": "#1A1A1D",
             "text": "#FFFFFF", "text2": "#9A9AA2", "text3": "#5E5E66"},
    "ocean": {"name": "Ocean", "dark": True, "accent": "#3EA6FF", "bg": "#0A1018", "sidebar": "#0C141E",
              "surface": "#111B27", "surface2": "#172433", "surface3": "#203043", "border": "#1B2a3A",
              "text": "#EEF4FA", "text2": "#9CB0C4", "text3": "#647A90"},
    "forest": {"name": "Forest", "dark": True, "accent": "#3DD68C", "bg": "#0B110E", "sidebar": "#0E1511",
               "surface": "#131C17", "surface2": "#1A251F", "surface3": "#24322A", "border": "#1F2B24",
               "text": "#EEF5F0", "text2": "#9DB3A6", "text3": "#66796D"},
    "sakura": {"name": "Sakura", "dark": True, "accent": "#FF7EB6", "bg": "#130D11", "sidebar": "#171015",
               "surface": "#1D141A", "surface2": "#261B22", "surface3": "#33242E", "border": "#2E2029",
               "text": "#FBF1F6", "text2": "#BFA3B2", "text3": "#7F6573"},
    "light": {"name": "Chiaro", "dark": False, "accent": "#0891B2", "bg": "#F6F6F8", "sidebar": "#EEEEF2",
              "surface": "#FFFFFF", "surface2": "#F1F1F4", "surface3": "#E4E4EA", "border": "#E2E2E8",
              "text": "#141418", "text2": "#5E5E69", "text3": "#9696A0"},
}


class Theme:
    def __init__(self):
        self.reload()

    def reload(self):
        a = settings.data["appearance"]
        self.preset = a["theme"] if a["theme"] in PRESETS else "midnight"
        pr = PRESETS[self.preset]
        self.dark = pr["dark"]
        self.accent = a["accent"]
        for k in ("bg", "sidebar", "surface", "surface2", "surface3", "border", "text", "text2", "text3"):
            setattr(self, k, pr[k])
        self.success = "#3DD68C"
        self.warning = "#F5B83D"
        self.danger = "#FF5C6C"
        self.info = "#4DA3FF"
        c = QColor(self.accent)
        self.accent_soft = f"rgba({c.red()},{c.green()},{c.blue()},0.16)"
        self.accent_hover = (c.darker(112) if c.lightnessF() > 0.7 else c.lighter(115)).name()
        lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
        self.on_accent = "#101014" if lum > 0.62 else "#FFFFFF"   # testo leggibile sopra l'accento
        dens = a["density"]
        self.pad = {"compact": 0.75, "normal": 1.0, "spacious": 1.25}.get(dens, 1.0)
        self.font_scale = float(a.get("font_scale", 1.0))
        anim = a["animations"]
        self.anim_factor = {"full": 1.25, "balanced": 1.0, "minimal": 0.5, "none": 0.0}.get(anim, 1.0)
        self.anim_level = anim

    def dur(self, ms: int) -> int:
        """Durata di un'animazione scalata secondo le impostazioni (0 = disattivata)."""
        return int(ms * self.anim_factor)

    @property
    def motion(self) -> bool:
        return self.anim_factor > 0

    @property
    def rich_motion(self) -> bool:
        return self.anim_level in ("full", "balanced")

    def s(self, px: float) -> int:
        return max(1, int(round(px * self.pad)))

    def fs(self, pt: float) -> int:
        return max(8, int(round(pt * self.font_scale)))

    def qss(self) -> str:
        s, f = self.s, self.fs
        return f"""
* {{ outline: none; }}
QWidget {{ color: {self.text}; font-size: {f(10)}pt; }}
QMainWindow, #root {{ background: {self.bg}; }}
#sidebar {{ background: {self.sidebar}; border-right: 1px solid {self.border}; }}
#pageTitle {{ font-size: {f(20)}pt; font-weight: 650; }}
#pageSub {{ color: {self.text2}; font-size: {f(10)}pt; }}
#sectionTitle {{ font-size: {f(11)}pt; font-weight: 600; color: {self.text}; }}
#muted {{ color: {self.text2}; }}
#faint {{ color: {self.text3}; font-size: {f(9)}pt; }}
#card {{ background: {self.surface}; border: 1px solid {self.border}; border-radius: 14px; }}
#cardFlat {{ background: {self.surface2}; border-radius: 12px; }}
QLabel {{ background: transparent; }}

QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit QLineEdit {{
    background: {self.surface2}; border: 1px solid {self.border}; border-radius: 10px;
    padding: {s(8)}px {s(12)}px; selection-background-color: {self.accent};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border: 1px solid {self.accent}; }}
#bigInput {{ font-size: {f(12)}pt; padding: {s(13)}px {s(16)}px; border-radius: 12px; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{ background: {self.surface2}; border: 1px solid {self.border};
    selection-background-color: {self.accent_soft}; selection-color: {self.text}; padding: 4px; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QPushButton {{ background: {self.surface2}; border: 1px solid {self.border}; border-radius: 10px;
    padding: {s(8)}px {s(14)}px; font-weight: 550; }}
QPushButton:hover {{ background: {self.surface3}; }}
QPushButton:pressed {{ background: {self.border}; }}
QPushButton:disabled {{ color: {self.text3}; }}
QPushButton#primary {{ background: {self.accent}; border: 1px solid {self.accent}; color: {self.on_accent}; }}
QPushButton#primary:hover {{ background: {self.accent_hover}; }}
QPushButton#danger {{ color: {self.danger}; }}
QPushButton#ghost {{ background: transparent; border: none; }}
QPushButton#ghost:hover {{ background: {self.surface2}; }}
QPushButton#chip {{ border-radius: 14px; padding: {s(5)}px {s(12)}px; font-weight: 500; }}
QPushButton#chip:checked {{ background: {self.accent_soft}; border: 1px solid {self.accent}; color: {self.text}; }}

QToolTip {{ background: {self.surface2}; color: {self.text}; border: 1px solid {self.border}; padding: 6px 8px; border-radius: 6px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {self.surface3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {self.text3}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid {self.text3}; background: transparent; }}
QCheckBox::indicator:checked {{ background: {self.accent}; border-color: {self.accent};
    image: url(none); }}

QMenu {{ background: {self.surface2}; border: 1px solid {self.border}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {self.accent_soft}; }}
QMenu::item:checked {{ color: {self.accent}; font-weight: 600; }}
QMenu::indicator {{ width: 0; }}
QMenu::separator {{ height: 1px; background: {self.border}; margin: 5px 8px; }}

QListWidget {{ background: transparent; border: none; }}
QListWidget::item {{ border-radius: 8px; padding: 8px; }}
QListWidget::item:selected {{ background: {self.accent_soft}; color: {self.text}; }}
QListWidget::item:hover {{ background: {self.surface2}; }}
QTreeWidget {{ background: {self.surface2}; border: 1px solid {self.border}; border-radius: 10px; padding: 4px; }}
QTreeWidget::item {{ padding: 5px; }}
QHeaderView::section {{ background: transparent; color: {self.text2}; border: none; padding: 6px; font-weight: 600; }}
QDialog {{ background: {self.surface}; }}
QSlider::groove:horizontal {{ height: 4px; background: {self.surface3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {self.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
"""


theme = Theme()


def apply_theme(app: QApplication):
    theme.reload()
    font = QFont("Segoe UI Variable Text")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    font.setPointSizeF(10 * theme.font_scale)
    font.setHintingPreference(QFont.PreferNoHinting)
    app.setFont(font)
    # Palette scura completa: qualunque widget non ancora "stilizzato" si disegna già nei colori del tema
    # (niente lampo bianco quando una pagina si apre la prima volta).
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    for role, col in ((QPalette.Window, theme.bg), (QPalette.Base, theme.surface), (QPalette.AlternateBase,
                      theme.surface2), (QPalette.Button, theme.surface2), (QPalette.Text, theme.text),
                      (QPalette.WindowText, theme.text), (QPalette.ButtonText, theme.text),
                      (QPalette.ToolTipBase, theme.surface2), (QPalette.ToolTipText, theme.text),
                      (QPalette.Highlight, theme.accent), (QPalette.HighlightedText, theme.on_accent),
                      (QPalette.PlaceholderText, theme.text3)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(theme.qss() + _checkbox_qss())


def _checkbox_qss() -> str:
    """Caselle di spunta ben visibili sul tema scuro (liste di episodi e file torrent)."""
    try:
        from .config import DATA
        from . import icons
        d = DATA / "ui"
        d.mkdir(exist_ok=True)
        f = d / f"check_{theme.on_accent.strip('#')}.png"
        if not f.exists():
            icons.pixmap("check", theme.on_accent, 14, 1.0).save(str(f))
        img = str(f).replace("\\", "/")
    except Exception:
        img = ""
    t = theme
    return f"""
QTreeView::indicator, QListView::indicator, QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px; border: 1.5px solid {t.text3}; background: {t.surface2}; }}
QTreeView::indicator:hover, QListView::indicator:hover, QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QTreeView::indicator:checked, QListView::indicator:checked, QCheckBox::indicator:checked {{
    background: {t.accent}; border-color: {t.accent}; image: url("{img}"); }}
QTreeView::indicator:disabled {{ border-color: {t.border}; background: transparent; }}
QTreeView::item {{ padding: 6px 2px; }}
"""
