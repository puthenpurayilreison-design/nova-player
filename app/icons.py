"""Icone vettoriali (stile lineare 24x24) generate a runtime nel colore richiesto."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

P = {
    "play": '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12-7.5a1 1 0 0 0 0-1.72l-12-7.5A1 1 0 0 0 7 4.5z" fill="C" stroke="none"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1.2" fill="C" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1.2" fill="C" stroke="none"/>',
    "player": '<rect x="2.5" y="4.5" width="19" height="15" rx="3"/><path d="M10 9.2v5.6l4.6-2.8z" fill="C"/>',
    "link": '<path d="M10 13.5a4.5 4.5 0 0 0 6.4.2l2.8-2.8a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2"/><path d="M14 10.5a4.5 4.5 0 0 0-6.4-.2l-2.8 2.8a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2"/>',
    "download": '<path d="M12 3.5v11.5"/><path d="M7 10.5l5 5 5-5"/><path d="M4.5 19.5h15"/>',
    "magnet": '<path d="M5 4h4v8a3 3 0 0 0 6 0V4h4v8a7 7 0 0 1-14 0z"/><path d="M5 8h4M15 8h4"/>',
    "library": '<rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9.5" y="4" width="4" height="16" rx="1"/><path d="M16.5 5.2l3.8-1 3 15.4-3.8 1z" transform="translate(-2.2 0)"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/>',
    "volume": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="C"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
    "mute": '<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="C"/><path d="M16 9.5l5 5M21 9.5l-5 5"/>',
    "fullscreen": '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
    "exitfs": '<path d="M9 4v4a1 1 0 0 1-1 1H4M20 9h-4a1 1 0 0 1-1-1V4M15 20v-4a1 1 0 0 1 1-1h4M4 15h4a1 1 0 0 1 1 1v4"/>',
    "subtitles": '<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M6.5 12.5h3M12 12.5h5.5M6.5 15.5h6M14.5 15.5h3"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "sparkle": '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    "cast": '<path d="M3 8V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/><path d="M3 12a8 8 0 0 1 8 8M3 16a4 4 0 0 1 4 4"/><circle cx="3.5" cy="19.5" r=".8"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "shield": '<path d="M12 3 5 6v6c0 4.5 3 7.8 7 9 4-1.2 7-4.5 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    "audio": '<path d="M4 15v-3a8 8 0 0 1 16 0v3"/><rect x="3" y="14" width="4.5" height="6" rx="1.5"/><rect x="16.5" y="14" width="4.5" height="6" rx="1.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.6v.1"/>',
    "camera": '<path d="M4 8a2 2 0 0 1 2-2h2l1.5-2h5L16 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><circle cx="12" cy="12.5" r="3.5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "retry": '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4.5V11h-6.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "pip": '<rect x="2.5" y="4.5" width="19" height="15" rx="2.5"/><rect x="12" y="11.5" width="7" height="5.5" rx="1" fill="C"/>',
    "next": '<path d="M5 5.5v13l9.5-6.5z" fill="C"/><path d="M18.5 5.5v13"/>',
    "prev": '<path d="M19 5.5v13L9.5 12z" fill="C"/><path d="M5.5 5.5v13"/>',
    "speed": '<path d="M12 13l4-5"/><path d="M3.5 17a9 9 0 1 1 17 0"/>',
    "trash": '<path d="M4 6.5h16M9 6.5V4.5h6v2M6.5 6.5l1 13h9l1-13"/>',
    "film": '<rect x="3" y="3.5" width="18" height="17" rx="2.5"/><path d="M7.5 3.5v17M16.5 3.5v17M3 8h4.5M3 12h4.5M3 16h4.5M16.5 8H21M16.5 12H21M16.5 16H21"/>',
    "file": '<path d="M6 3h8l4.5 4.5V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v4.5h4.5"/>',
    "music": '<path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
    "loop": '<path d="M17 3.5l3 3-3 3"/><path d="M4 11.5v-1a4 4 0 0 1 4-4h12"/><path d="M7 20.5l-3-3 3-3"/><path d="M20 12.5v1a4 4 0 0 1-4 4H4"/>',
    "convert": '<path d="M4 8h13l-3.5-3.5M20 16H7l3.5 3.5"/>',
    "cloud": '<path d="M7 18.5a4.5 4.5 0 0 1-.6-9 6 6 0 0 1 11.5 1.6A3.8 3.8 0 0 1 17.5 18.5z"/>',
    "up": '<path d="M12 19V6M6.5 11.5L12 6l5.5 5.5"/>',
    "down": '<path d="M12 5v13M6.5 12.5L12 18l5.5-5.5"/>',
    "clipboard": '<rect x="5" y="4.5" width="14" height="16.5" rx="2"/><path d="M9 4.5V3h6v1.5"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18c1 0 1.6-.8 1.6-1.6 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11.5" r="1.2" fill="C"/><circle cx="10" cy="7.5" r="1.2" fill="C"/><circle cx="14.5" cy="7.5" r="1.2" fill="C"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6.5 10h.1M10 10h.1M13.5 10h.1M17 10h.1M7.5 14h9"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0 5 5L15 16l-7 5-3-3 5-7z" transform="translate(-.5 -.5)"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "star": '<path d="M12 3.2l2.7 5.6 6.1.8-4.5 4.2 1.1 6-5.4-2.9-5.4 2.9 1.1-6-4.5-4.2 6.1-.8z" fill="C" stroke="none"/>',
    "chev_left": '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    "chev_right": '<path d="M9.5 5.5 16 12l-6.5 6.5"/>',
    "back": '<path d="M19 12H5.5M11 6l-6 6 6 6"/>',
    "bookmark": '<path d="M6.5 3.5h11v17l-5.5-4-5.5 4z"/>',
    "bookmark_on": '<path d="M6.5 3.5h11v17l-5.5-4-5.5 4z" fill="C"/>',
    "trailer": '<rect x="2.5" y="5" width="19" height="14" rx="3.5"/><path d="M10 9.3v5.4l4.6-2.7z" fill="C"/>',
    "nova": '<path d="M12 2.5l2.4 6.6 6.6 2.4-6.6 2.4L12 20.5l-2.4-6.6-6.6-2.4 6.6-2.4z" fill="C" stroke="none"/>',
}


@lru_cache(maxsize=512)
def svg(name: str, color: str, stroke: float = 1.8) -> str:
    body = P.get(name, P["file"]).replace('"C"', f'"{color}"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" '
            f'stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 20, dpr: float = 2.0) -> QPixmap:
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, size: int = 20) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size))
    return ic


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        r = QSvgRenderer(QByteArray(
            ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
             '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0" stop-color="#5EEAD4"/><stop offset="1" stop-color="#0EA5E9"/></linearGradient></defs>'
             '<rect width="24" height="24" rx="6" fill="url(#g)"/>'
             '<path d="M12 4l1.9 5.1L19 11l-5.1 1.9L12 18l-1.9-5.1L5 11l5.1-1.9z" fill="#062A33"/></svg>').encode()))
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        ic.addPixmap(pm)
    return ic
