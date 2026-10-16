"""Installazione: scarica i componenti nativi in bin/ e crea i collegamenti.

Uso:  python setup_deps.py             (scarica solo ciò che manca)
      python setup_deps.py --force     (aggiorna tutto)
      python setup_deps.py --shortcut  (solo collegamenti Desktop/Start)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from app.deps import ensure, missing  # noqa: E402


def make_icon():
    ico = ROOT / "assets" / "nova.ico"
    if ico.exists():
        return ico
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(ROOT))
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])  # noqa: F841
    from app.icons import app_icon
    ico.parent.mkdir(exist_ok=True)
    app_icon().pixmap(256, 256).save(str(ico))
    return ico


def make_shortcuts():
    """Collegamenti NOVA sul Desktop e nel menu Start."""
    import subprocess
    ico = make_icon()
    pyw = Path(sys.executable).with_name("pythonw.exe")
    q = lambda s: "'" + str(s).replace("'", "''") + "'"  # noqa: E731
    ok = 0
    for folder in ("Desktop", "Programs"):
        ps = ("$ErrorActionPreference='Stop';"
              f"$p=Join-Path ([Environment]::GetFolderPath('{folder}')) 'NOVA.lnk';"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($p);"
              f"$s.TargetPath={q(pyw)};$s.Arguments={q(chr(34) + str(ROOT / 'main.py') + chr(34))};"
              f"$s.WorkingDirectory={q(ROOT)};$s.IconLocation={q(ico)};"
              "$s.Description='NOVA - player, stream, download e torrent';$s.Save()")
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True)
        if r.returncode == 0:
            ok += 1
        else:
            print(f"  ✗ shortcut {folder}: {r.stderr.strip().splitlines()[0] if r.stderr.strip() else r.returncode}")
    if ok == 2:
        print("  ✓ Shortcuts created on the Desktop and in the Start menu")
    else:
        print("  Use avvia.bat to open NOVA.")


def main():
    # console di Windows non UTF-8 (es. server di build): niente errori sui simboli della barra
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if "--shortcut" in sys.argv:
        make_shortcuts()
        return
    latest = "--latest" in sys.argv
    failed = ensure(force="--force" in sys.argv or latest)
    if latest:
        # versione più recente di tutto; se un download non riesce si tiene quella già presente
        failed = [f for f in failed if f in missing()]
    if failed:
        print("\nFAILED:", ", ".join(failed))
        print("Check your connection and run setup.bat again.")
        if "--force" in sys.argv:
            input("Press Enter to close…")
        sys.exit(1)
    print("\nComponents ready.")
    if "--force" in sys.argv:
        input("Done. Press Enter and restart NOVA…")


if __name__ == "__main__":
    main()
