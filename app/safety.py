"""Sicurezza: torrent falsi (programmi travestiti da film) e controllo con Windows Defender."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .config import VIDEO_EXT, AUDIO_EXT, SUB_EXT

DANGER_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".msi", ".msix", ".vbs", ".vbe", ".js", ".jse",
              ".wsf", ".wsh", ".ps1", ".hta", ".lnk", ".jar", ".cpl", ".dll", ".reg", ".appx", ".iso", ".img"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz", ".cab"}
HARMLESS_EXT = VIDEO_EXT | AUDIO_EXT | SUB_EXT | {".txt", ".nfo", ".jpg", ".jpeg", ".png", ".webp", ".srr",
                                                  ".sfv", ".md5", ".url", ".pdf"}
NOWIN = 0x08000000 if sys.platform == "win32" else 0


def fake_verdict(files: list[tuple[str, int]]) -> str | None:
    """files = [(percorso, dimensione)]. Restituisce il motivo se il torrent sembra un falso, altrimenti None."""
    if not files:
        return None
    total = sum(s for _, s in files) or 1
    vids = [(p, s) for p, s in files if Path(p).suffix.lower() in VIDEO_EXT]
    for p, s in files:
        name = Path(p).name.lower()
        ext = Path(p).suffix.lower()
        if re.search(r"\.(mkv|mp4|avi|mov|wmv|m4v)\.(exe|scr|bat|cmd|lnk|msi|js|vbs)$", name):
            return f"«{Path(p).name}» finge di essere un video ma è un programma."
        if ext in DANGER_EXT and ext not in (".iso", ".img"):
            return f"Contiene un programma ({Path(p).name}). Un film non ha bisogno di file {ext}: quasi sempre è un virus."
        if ext == ".lnk":
            return "Contiene un collegamento (.lnk): trucco tipico dei torrent falsi."
    if not vids:
        arch = [p for p, _ in files if Path(p).suffix.lower() in ARCHIVE_EXT]
        if arch:
            return "Niente video, solo archivi (.zip/.rar): spesso chiedono una password su un sito = truffa."
        if any(Path(p).suffix.lower() in (".iso", ".img") for p, _ in files):
            return None   # immagini disco: possono essere legittime (Blu-ray), nessun allarme
        return None
    big = max(s for _, s in vids)
    if big < 80 * 1024 * 1024 and total > 50 * 1024 * 1024:
        return "Il video è minuscolo rispetto al resto dei file: probabilmente non è il film."
    for p, _ in files:
        if re.search(r"(?i)(password|codec[ _-]?pack|player[ _-]?install|read[ _-]?me[ _-]?first|"
                     r"download[ _-]?codec)", Path(p).name):
            return f"«{Path(p).name}» chiede codec o password: tipico dei falsi."
    return None


def needs_scan(path: str) -> bool:
    """Solo file che possono eseguire codice: i video non vanno scansionati (sarebbe lento e inutile)."""
    ext = Path(path).suffix.lower()
    return ext in DANGER_EXT or ext in ARCHIVE_EXT


def _mpcmdrun() -> str | None:
    if sys.platform != "win32":
        return None
    cands = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Windows Defender" / "MpCmdRun.exe"]
    plat = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    try:
        cands += sorted(plat.glob("*/MpCmdRun.exe"), reverse=True)
    except OSError:
        pass
    return next((str(c) for c in cands if c.exists()), None)


def defender_scan(path: str, timeout=600) -> tuple[str, str]:
    """('clean'|'threat'|'unavailable', messaggio). Scansiona file o cartella con Windows Defender."""
    exe = _mpcmdrun()
    if not exe:
        return "unavailable", "Windows Defender non trovato."
    try:
        r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"],
                           capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    except Exception as e:
        return "unavailable", f"Scansione non riuscita: {e}"
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 2 or "Threat" in out and "no threats" not in out.lower():
        m = re.search(r"Threat\s*:\s*(.+)", out)
        return "threat", (m.group(1).strip() if m else "minaccia trovata")
    if r.returncode == 0:
        return "clean", "Nessuna minaccia."
    return "unavailable", out.strip()[-200:] or f"codice {r.returncode}"
