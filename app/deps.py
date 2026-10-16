"""Componenti nativi in bin/: libmpv-2.dll, aria2c.exe, ffmpeg/ffprobe.exe, yt-dlp.exe.
Usato da setup_deps.py (installazione) e dall'app (Impostazioni › Aggiorna componenti)."""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .config import BIN

UA = {"User-Agent": "NOVA-setup", "Accept": "application/vnd.github+json"}

MPV_REPOS = ["shinchiro/mpv-winbuild-cmake", "zhongfly/mpv-winbuild"]
ARIA2_REPO = "aria2/aria2"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


def _print_progress(label, pct, mb):
    bar = "█" * (pct // 4) + "░" * (25 - pct // 4)
    print(f"\r  {label:<10} {bar} {pct:3d}%  {mb:6.1f} MB", end="" if pct < 100 else "\n", flush=True)


progress_cb = _print_progress


def fetch(url: str, label: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "NOVA-setup"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            if total:
                progress_cb(label, done * 100 // total, done / 1048576)
        return buf.getvalue()


def release_assets(repo: str) -> list[dict]:
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("assets", [])


def extract_7z(data: bytes, dest: str):
    """Estrae un .7z: prima con py7zr, poi con tar di Windows, infine con 7zr.exe ufficiale."""
    import subprocess
    try:
        import py7zr
        with py7zr.SevenZipFile(io.BytesIO(data)) as z:
            z.extractall(dest)
        return
    except Exception as e:
        print(f"  py7zr is not enough ({e.__class__.__name__}), trying another method…")
    arc = Path(dest) / "_pkg.7z"
    arc.write_bytes(data)
    try:
        subprocess.run(["tar", "-xf", str(arc), "-C", dest], check=True, capture_output=True)
        return
    except Exception:
        pass
    seven = BIN / "7zr.exe"
    if not seven.exists():
        seven.write_bytes(fetch("https://www.7-zip.org/a/7zr.exe", "7zr"))
    subprocess.run([str(seven), "x", "-y", f"-o{dest}", str(arc)], check=True, capture_output=True)


def _write(path: Path, data: bytes):
    """Scrive un componente; se è in uso (app aperta) lo salva come .new e verrà sostituito al riavvio."""
    try:
        path.write_bytes(data)
    except PermissionError:
        path.with_name(path.name + ".new").write_bytes(data)


def apply_pending():
    """All'avvio, prima di caricare mpv: sostituisce i componenti aggiornati (.new)."""
    if not BIN.exists():
        return
    for f in BIN.glob("*.new"):
        try:
            f.replace(f.with_name(f.name[:-4]))
        except OSError:
            pass


def get_mpv():
    for repo in MPV_REPOS:
        try:
            assets = release_assets(repo)
        except Exception as e:
            print(f"  {repo}: {e}")
            continue
        names = [a["name"] for a in assets]
        # x86_64 "generico" (non v3: funziona anche su CPU senza AVX2)
        pick = [a for a in assets if re.match(r"^mpv-dev-x86_64-\d{8}-git-[0-9a-f]+\.7z$", a["name"])]
        pick = pick or [a for a in assets if a["name"].startswith("mpv-dev-x86_64") and "v3" not in a["name"]
                        and a["name"].endswith(".7z")]
        pick = pick or [a for a in assets if a["name"].startswith("mpv-dev-x86_64") and a["name"].endswith(".7z")]
        if not pick:
            print(f"  {repo}: no mpv-dev package found ({len(names)} files)")
            continue
        a = pick[0]
        print(f"  libmpv from {repo}: {a['name']}")
        data = fetch(a["browser_download_url"], "libmpv")
        with tempfile.TemporaryDirectory() as td:
            extract_7z(data, td)
            for dll in Path(td).rglob("*.dll"):
                if dll.name.lower() in ("libmpv-2.dll", "mpv-2.dll"):
                    _write(BIN / "libmpv-2.dll", dll.read_bytes())
                    return True
        print("  libmpv-2.dll not found in the package")
    return False


def get_aria2():
    assets = release_assets(ARIA2_REPO)
    a = next(a for a in assets if re.search(r"win-64bit.*\.zip$", a["name"]))
    print(f"  aria2: {a['name']}")
    data = fetch(a["browser_download_url"], "aria2")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            if n.lower().endswith("aria2c.exe"):
                _write(BIN / "aria2c.exe", z.read(n))
                return True
    return False


def get_ffmpeg():
    data = fetch(FFMPEG_URL, "ffmpeg")
    ok = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            base = n.rsplit("/", 1)[-1].lower()
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                _write(BIN / base, z.read(n))
                ok += 1
    return ok == 2


YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


def get_ytdlp():
    _write(BIN / "yt-dlp.exe", fetch(YTDLP_URL, "yt-dlp"))
    return True


JOBS = [("libmpv-2.dll", get_mpv), ("aria2c.exe", get_aria2), ("ffmpeg.exe", get_ffmpeg), ("yt-dlp.exe", get_ytdlp)]


def missing() -> list[str]:
    return [f for f, _ in JOBS if not (BIN / f).exists()]


def ensure(force=False, log=print) -> list[str]:
    """Scarica ciò che manca (o tutto con force). Restituisce l'elenco di ciò che non è riuscito."""
    BIN.mkdir(exist_ok=True)
    failed = []
    for fname, fn in JOBS:
        if (BIN / fname).exists() and not force:
            log(f"  ✓ {fname} already present")
            continue
        log(f"Downloading {fname}…")
        try:
            if not fn():
                failed.append(fname)
        except Exception as e:
            log(f"  ✗ {fname}: {e}")
            failed.append(fname)
    return failed
