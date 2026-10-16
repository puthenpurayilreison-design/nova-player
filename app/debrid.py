"""Client Real-Debrid (API ufficiale REST 1.0): torrent/magnet → link diretti HTTP."""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import VIDEO_EXT

API = "https://api.real-debrid.com/rest/1.0"


class RDError(Exception):
    pass


class RealDebrid(QObject):
    progress = Signal(str, object)   # testo, frazione o None
    ready = Signal(list)             # [{filename, filesize, download}]
    failed = Signal(str)
    not_cached = Signal()            # non pronto entro il tempo massimo: non era in cache

    STATUS = {"magnet_conversion": "Converting magnet…", "waiting_files_selection": "Selecting files…",
              "queued": "Queued on the cloud…", "downloading": "Downloading on the cloud", "compressing": "Compressing…",
              "uploading": "Uploading…", "downloaded": "Ready"}

    def __init__(self, token: str, instant_timeout: float | None = None):
        super().__init__()
        self.token = token.strip()
        self.instant_timeout = instant_timeout
        self.cancelled = False

    def _req(self, method, path, data=None, raw=None):
        url = API + path
        headers = {"Authorization": f"Bearer {self.token}"}
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif raw is not None:
            body = raw
            headers["Content-Type"] = "application/x-bittorrent"
        req = urllib.request.Request(url, body, headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                txt = r.read()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read()).get("error", str(e))
            except Exception:
                err = str(e)
            if e.code == 401:
                err = "Real-Debrid token invalid or expired (Settings › Torrent)."
            elif e.code == 403:
                err = "Real-Debrid account without premium or blocked."
            raise RDError(err)

    def user(self) -> dict:
        return self._req("GET", "/user")

    def run(self, src: str):
        threading.Thread(target=self._run, args=(src,), daemon=True).start()

    def _run(self, src):
        try:
            if src.startswith("magnet:"):
                r = self._req("POST", "/torrents/addMagnet", {"magnet": src})
            else:
                r = self._req("PUT", "/torrents/addTorrent", raw=Path(src).read_bytes())
            tid = r["id"]
            selected = False
            t0 = time.time()
            while True:
                info = self._req("GET", f"/torrents/info/{tid}")
                st = info.get("status")
                if st == "waiting_files_selection" and not selected:
                    # solo i video (meno roba = link pronto prima); se non ce ne sono, tutto
                    vids = [str(f["id"]) for f in info.get("files", [])
                            if Path(f.get("path", "")).suffix.lower() in VIDEO_EXT]
                    self._req("POST", f"/torrents/selectFiles/{tid}", {"files": ",".join(vids) or "all"})
                    selected = True
                    continue
                if st == "downloaded":
                    break
                if st in ("error", "magnet_error", "virus", "dead"):
                    raise RDError(f"Real-Debrid: status '{st}'")
                pr = info.get("progress")
                txt = self.STATUS.get(st, st)
                if st == "downloading":
                    spd = info.get("speed") or 0
                    txt = f"{txt} · {pr:.0f}% · {spd / 1048576:.1f} MB/s · {info.get('seeders', 0)} seed"
                self.progress.emit(txt, (pr or 0) / 100 if st == "downloading" else None)
                if self.cancelled:
                    return
                if self.instant_timeout and time.time() - t0 > self.instant_timeout:
                    self.instant_timeout = None
                    self.not_cached.emit()
                if time.time() - t0 > 6 * 3600:
                    raise RDError("Timed out waiting for Real-Debrid.")
                time.sleep(1 if time.time() - t0 < 60 else 3)
            self.progress.emit("Generating direct links…", 1.0)
            out = []
            for link in info.get("links", []):
                u = self._req("POST", "/unrestrict/link", {"link": link})
                out.append({"filename": u.get("filename"), "filesize": u.get("filesize"),
                            "download": u.get("download")})
            if not out:
                raise RDError("No links returned.")
            out.sort(key=lambda f: (Path(f["filename"] or "").suffix.lower() not in VIDEO_EXT, -(f["filesize"] or 0)))
            self.ready.emit(out)
        except RDError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Network error: {e}")
