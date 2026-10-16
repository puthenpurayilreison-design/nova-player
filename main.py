"""NOVA — player universale, streaming 4K, download manager e torrent per Windows 11."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6.QtCore import Qt, QLocale  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.config import DATA  # noqa: E402
from app.deps import apply_pending  # noqa: E402

apply_pending()   # componenti aggiornati mentre l'app era aperta

SERVER = "NOVA-MediaHub-single-instance"


def log_exceptions(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    try:
        with open(DATA / "logs" / "crash.log", "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    sys.__excepthook__(etype, value, tb)


def forward_to_running(args) -> bool:
    """Se NOVA è già aperto, gli passa file/link e chiude questa istanza."""
    s = QLocalSocket()
    s.connectToServer(SERVER)
    if s.waitForConnected(300):
        s.write(("\n".join(args) or "--show").encode("utf-8"))
        s.flush()
        s.waitForBytesWritten(500)
        s.disconnectFromServer()
        return True
    return False


def main():
    sys.excepthook = log_exceptions
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("NOVA")
    app.setOrganizationName("NOVA")
    app.setQuitOnLastWindowClosed(False)
    QLocale.setDefault(QLocale(QLocale.Italian, QLocale.Italy))
    args = [a for a in sys.argv[1:]]

    if forward_to_running(args):
        return 0

    from app import winutil
    winutil.set_app_id()
    winutil.prefer_high_performance_gpu()
    from app.theme import apply_theme
    apply_theme(app)
    from app import icons
    ico = ROOT / "assets" / "nova.ico"
    if not ico.exists():
        ico.parent.mkdir(exist_ok=True)
        icons.app_icon().pixmap(256, 256).save(str(ico))
    app.setWindowIcon(icons.app_icon())

    from app.main_window import MainWindow
    win = MainWindow()

    server = QLocalServer()
    QLocalServer.removeServer(SERVER)
    server.listen(SERVER)

    def incoming():
        c = server.nextPendingConnection()
        if not c:
            return

        def read():
            data = bytes(c.readAll()).decode("utf-8", "ignore").strip()
            items = [x for x in data.split("\n") if x and x != "--show"]
            win.handle_args(items)
            win.show_normal()
        c.readyRead.connect(read)
    server.newConnection.connect(incoming)

    if "--tray" in args:
        win.hide()
    else:
        win.show()
    files = [a for a in args if a != "--tray"]
    if "--tray" not in args and not files:
        win.play_intro()
    if files:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(400, lambda: win.handle_args(files))
    code = app.exec()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        log_exceptions(*sys.exc_info())
        try:
            QMessageBox.critical(None, "NOVA", "Errore all'avvio. Dettagli in:\n" + str(DATA / "logs" / "crash.log"))
        except Exception:
            pass
        raise
