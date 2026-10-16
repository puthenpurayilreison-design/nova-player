"""Modulo Download manager: aria2 (multi-connessione) + yt-dlp per le pagine video."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QScrollArea, QDialog,
                               QMenu, QInputDialog, QFileDialog, QApplication)

from . import icons
from .turbo import probe, link_expiry
from .config import (settings, tool, DATA, VIDEO_EXT, AUDIO_EXT, human_size, human_speed, human_eta)
from .theme import theme
from .widgets import (PageHeader, Card, label, button, IconButton, AnimatedProgress, Sparkline, Pill,
                      EmptyState, Segmented, animate_in, SpeedHero)

NOWIN = 0x08000000 if sys.platform == "win32" else 0
STORE = DATA / "downloads.json"
DIRECT_TYPES = ("video/", "audio/", "application/octet-stream", "application/zip", "application/x-",
                "application/pdf", "application/vnd", "image/", "application/gzip", "binary/")


def free_port(pref: int) -> int:
    for p in range(pref, pref + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return pref


def category_dir(base: str, name: str) -> str:
    ext = Path(name).suffix.lower()
    sub = "Video" if ext in VIDEO_EXT else "Audio" if ext in AUDIO_EXT else "Other"
    d = Path(base) / sub
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while True:
        q = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not q.exists():
            return q
        i += 1


# ------------------------------------------------------------------ aria2
class Aria2:
    """Gestisce il processo aria2c e le chiamate JSON-RPC."""

    def __init__(self):
        self.proc = None
        self.port = free_port(6801)
        self.secret = secrets.token_hex(12)
        self.session = DATA / "aria2.session"
        self.ok = False
        self.error = ""

    def start(self):
        ds = settings.data["downloads"]
        Path(ds["dir"]).mkdir(parents=True, exist_ok=True)
        self.session.touch(exist_ok=True)
        args = [tool("aria2c"), "--enable-rpc", f"--rpc-listen-port={self.port}", "--rpc-listen-all=false",
                f"--rpc-secret={self.secret}", f"--dir={ds['dir']}",
                f"--max-connection-per-server={min(16, int(ds['connections']))}",
                f"--split={int(ds['connections'])}", "--min-split-size=1M",
                f"--max-concurrent-downloads={int(ds['parallel'])}", "--continue=true",
                "--auto-file-renaming=true", "--allow-overwrite=false", "--file-allocation=none",
                f"--max-overall-download-limit={int(ds['limit_kb'])}K", "--max-tries=12",
                "--timeout=30", "--lowest-speed-limit=0",
                f"--input-file={self.session}", f"--save-session={self.session}",
                "--save-session-interval=20", "--force-save=false", "--follow-torrent=false",
                "--summary-interval=0", "--console-log-level=warn", "--disk-cache=128M",
                "--optimize-concurrent-downloads=true", "--http-accept-gzip=true",
                "--piece-length=1M", "--enable-http-keep-alive=true", "--async-dns=true",
                "--max-file-not-found=5", "--uri-selector=adaptive", "--max-resume-failure-tries=5",
                "--retry-wait=3", "--connect-timeout=15",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) NOVA/1.0",
                f"--log={DATA / 'logs' / 'aria2.log'}", "--log-level=warn"]
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=NOWIN)
        except FileNotFoundError:
            self.error = "aria2c not found: run setup.bat"
            return False
        for _ in range(50):
            time.sleep(0.1)
            try:
                self.call("aria2.getVersion")
                self.ok = True
                return True
            except Exception:
                if self.proc.poll() is not None:
                    break
        self.error = "aria2c is not responding"
        return False

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def call(self, method, *params):
        body = json.dumps({"jsonrpc": "2.0", "id": "nova", "method": method,
                           "params": [f"token:{self.secret}", *params]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/jsonrpc", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        if "error" in data:
            raise RuntimeError(data["error"].get("message"))
        return data["result"]

    def multicall(self, calls):
        body = json.dumps({"jsonrpc": "2.0", "id": "nova", "method": "system.multicall", "params": [[
            {"methodName": m, "params": [f"token:{self.secret}", *p]} for m, p in calls]]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/jsonrpc", body,
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())["result"]

    def stop(self):
        if self.alive():
            try:
                self.call("aria2.saveSession")
                self.call("aria2.shutdown")
                self.proc.wait(3)
            except Exception:
                self.proc.kill()


# ------------------------------------------------------------------ yt-dlp
class YtdlCancelled(Exception):
    pass


class YtdlJob(threading.Thread):
    def __init__(self, item: dict, mgr: "DownloadManager"):
        super().__init__(daemon=True)
        self.item = item
        self.mgr = mgr
        self.stop_flag = False

    def run(self):
        if use_ytdlp_exe():
            return self.run_exe()
        it = self.item
        try:
            import yt_dlp
        except ImportError:
            it.update(status="error", error="yt-dlp is not installed")
            return
        h = it.get("height") or 9999
        cont = it.get("container", "mkv")
        if it.get("audio_only"):
            fmt = "ba[ext=m4a]/ba/b"
        else:
            fmt = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        out_dir = it["dir"]
        Path(out_dir).mkdir(parents=True, exist_ok=True)

        def hook(d):
            if self.stop_flag:
                raise YtdlCancelled()
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                frag = d.get("info_dict", {}).get("format_id", "")
                it.update(done=d.get("downloaded_bytes") or 0, total=total, speed=d.get("speed") or 0,
                          eta=d.get("eta"), status="active", part=frag)
                if d.get("filename"):
                    it["name"] = Path(d["filename"]).name.replace(".part", "")
            elif d["status"] == "finished":
                it["stage"] += 1

        def pp_hook(d):
            if d.get("status") == "started" and d.get("postprocessor") in ("Merger", "FFmpegVideoRemuxer"):
                it.update(status="active", stage_text="Merging audio and video…")
            if d.get("status") == "finished" and d.get("info_dict", {}).get("filepath"):
                it["path"] = d["info_dict"]["filepath"]

        opts = {
            "format": fmt, "outtmpl": os.path.join(out_dir, "%(title).180B [%(id)s].%(ext)s"),
            "merge_output_format": None if it.get("audio_only") else cont,
            "ffmpeg_location": str(Path(tool("ffmpeg")).parent) if os.path.isabs(tool("ffmpeg")) else None,
            "progress_hooks": [hook], "postprocessor_hooks": [pp_hook], "quiet": True, "no_warnings": True,
            "noprogress": True, "continuedl": True, "concurrent_fragment_downloads": 16,
            "http_chunk_size": 10 * 1024 * 1024, "retries": 10,
            "fragment_retries": 10, "windowsfilenames": True, "noplaylist": True,
        }
        it.update(status="active", stage=0, stage_text="")
        try:
            with yt_dlp.YoutubeDL({k: v for k, v in opts.items() if v is not None}) as y:
                info = y.extract_info(it["url"], download=True)
                path = it.get("path") or (info.get("requested_downloads") or [{}])[0].get("filepath") \
                    or y.prepare_filename(info)
            it.update(status="complete", path=path, name=Path(path).name, done=it.get("total") or it.get("done"),
                      speed=0, stage_text="")
            if it.get("total"):
                it["done"] = it["total"]
            try:
                it["total"] = it["done"] = os.path.getsize(path)
            except OSError:
                pass
            self.mgr.finished.emit(it["id"])
        except YtdlCancelled:
            it.update(status="paused", speed=0)
        except Exception as e:
            msg = str(e).replace("ERROR: ", "")
            it.update(status="error", error=msg[:220], speed=0)
        self.mgr.save()


    def run_exe(self):
        """Versione con yt-dlp.exe (app compilata): si aggiorna da sola e segue i cambi dei siti."""
        it = self.item
        h = it.get("height") or 9999
        cont = it.get("container", "mkv")
        fmt = "ba[ext=m4a]/ba/b" if it.get("audio_only") else f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        Path(it["dir"]).mkdir(parents=True, exist_ok=True)
        args = [tool("yt-dlp"), "-f", fmt, "-o", os.path.join(it["dir"], "%(title).180B [%(id)s].%(ext)s"),
                "--no-playlist", "--newline", "--no-colors", "--windows-filenames", "-N", "16",
                "--http-chunk-size", "10M",
                "--retries", "10", "--fragment-retries", "10", "--continue",
                "--ffmpeg-location", str(Path(tool("ffmpeg")).parent),
                "--progress-template",
                "download:NOVA|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
                "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
                "--print", "after_move:NOVAFILE|%(filepath)s"]
        if not it.get("audio_only"):
            args += ["--merge-output-format", cont]
        it.update(status="active", stage_text="")
        num = lambda x: float(x) if x not in (None, "NA", "None", "") else 0.0  # noqa: E731
        try:
            p = subprocess.Popen(args + [it["url"]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="ignore", creationflags=NOWIN)
            last_err = ""
            for line in p.stdout:
                if self.stop_flag:
                    p.kill()
                    it.update(status="paused", speed=0)
                    self.mgr.save()
                    return
                line = line.strip()
                if line.startswith("NOVA|"):
                    _, d, t, te, sp, eta = (line.split("|") + [""] * 6)[:6]
                    it.update(done=num(d), total=num(t) or num(te), speed=num(sp),
                              eta=num(eta) or None, status="active")
                elif line.startswith("NOVAFILE|"):
                    it["path"] = line.split("|", 1)[1]
                elif "[Merger]" in line:
                    it["stage_text"] = "Merging audio and video…"
                elif line.startswith("ERROR"):
                    last_err = line.replace("ERROR: ", "")
            p.wait()
            if p.returncode == 0 and it.get("path"):
                try:
                    it["total"] = it["done"] = os.path.getsize(it["path"])
                except OSError:
                    pass
                it.update(status="complete", name=Path(it["path"]).name, speed=0, stage_text="")
                self.mgr.finished.emit(it["id"])
            else:
                it.update(status="error", error=(last_err or "yt-dlp failed")[:220], speed=0)
        except Exception as e:
            it.update(status="error", error=str(e)[:220], speed=0)
        self.mgr.save()


def use_ytdlp_exe() -> bool:
    """Nell'app compilata usa yt-dlp.exe (aggiornabile); nella versione Python il modulo."""
    from .config import FROZEN
    p = tool("yt-dlp")
    return FROZEN and os.path.isabs(p) and os.path.exists(p)


class InfoProbe(QObject):
    """Rileva in background se un link è un file diretto o una pagina da yt-dlp."""
    done = Signal(str, dict)

    def run(self, url):
        threading.Thread(target=self._run, args=(url,), daemon=True).start()

    def _run(self, url):
        res = {"kind": "direct"}
        path = urllib.parse.urlparse(url).path.lower()
        ext = Path(path).suffix
        if ext in (".m3u8", ".mpd"):
            res = {"kind": "ytdl"}
        elif ext and ext not in (".html", ".htm", ".php", ".aspx", ""):
            res = {"kind": "direct"}
        else:
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    ct = (r.headers.get("Content-Type") or "").lower()
                    cd = (r.headers.get("Content-Disposition") or "").lower()
                res = {"kind": "direct" if ("attachment" in cd or ct.startswith(DIRECT_TYPES)) else "ytdl"}
            except Exception:
                res = {"kind": "ytdl"}
        if res["kind"] == "ytdl":
            try:
                if use_ytdlp_exe():
                    out = subprocess.run([tool("yt-dlp"), "-J", "--no-playlist", url], capture_output=True,
                                         timeout=60, creationflags=NOWIN)
                    if out.returncode != 0:
                        raise RuntimeError(out.stderr.decode(errors="ignore")[-200:])
                    info = json.loads(out.stdout)
                else:
                    import yt_dlp
                    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                                           "skip_download": True}) as y:
                        info = y.extract_info(url, download=False)
                heights = sorted({f.get("height") for f in info.get("formats", []) if f.get("height")}, reverse=True)
                res.update(title=info.get("title") or url, heights=heights,
                           duration=info.get("duration"), extractor=info.get("extractor_key"))
            except Exception as e:
                res = {"kind": "direct", "probe_error": str(e)[:200]}
        self.done.emit(url, res)


class YtdlDialog(QDialog):
    """Scelta qualità e formato per i link di pagine video."""

    def __init__(self, parent, info: dict):
        super().__init__(parent)
        self.setWindowTitle("Download video")
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 20)
        v.setSpacing(14)
        v.addWidget(label("Video found", "faint"))
        t = label(info.get("title", ""), "sectionTitle", wrap=True)
        v.addWidget(t)
        hs = info.get("heights") or []
        opts = [("best", "Maximum")]
        for h, n in ((2160, "4K"), (1440, "1440p"), (1080, "1080p"), (720, "720p")):
            if any(x >= h for x in hs):
                opts.append((str(h), n))
        opts.append(("audio", "Audio only"))
        v.addWidget(label("Quality", "muted"))
        self.q = Segmented(opts, "best")
        v.addWidget(self.q)
        v.addWidget(label("Format", "muted"))
        self.c = Segmented([("mkv", "MKV"), ("mp4", "MP4")], settings.get("downloads", "ytdlp_container"))
        v.addWidget(self.c)
        r = QHBoxLayout()
        r.addStretch()
        r.addWidget(button("Cancel", None, None, self.reject))
        r.addWidget(button("Download", "primary", "download", self.accept))
        v.addSpacing(6)
        v.addLayout(r)

    def result_opts(self):
        q = self.q.value
        settings.set("downloads", "ytdlp_container", self.c.value, notify=False)
        return {"audio_only": q == "audio", "height": None if q in ("best", "audio") else int(q),
                "container": self.c.value}


# ------------------------------------------------------------------ manager
class DownloadManager(QObject):
    renewed = Signal(str, bool, str)
    added = Signal(str)
    removed = Signal(str)
    finished = Signal(str)
    error = Signal(str, str)
    need_ytdl_choice = Signal(str, dict)

    def __init__(self):
        super().__init__()
        self.items: dict[str, dict] = {}
        self.order: list[str] = []
        self.aria = Aria2()
        self.jobs: dict[str, YtdlJob] = {}
        self.probe = InfoProbe()
        self.probe.done.connect(self._probed)
        self._lock = threading.Lock()
        self._done_seen: set = set()
        self._gentle: set = set()
        self._load()
        threading.Thread(target=self._boot, daemon=True).start()
        self.finished.connect(self._organize)

    # ---- persistenza (completati e yt-dlp) ----
    def _load(self):
        try:
            data = json.loads(STORE.read_text("utf-8"))
        except Exception:
            data = []
        for it in data:
            if it["src"] == "ytdl" and it["status"] in ("active", "waiting"):
                it["status"] = "paused"
            it["speed"] = 0
            self.items[it["id"]] = it
            self.order.append(it["id"])

    def save(self):
        keep = [self.items[i] for i in self.order if i in self.items and
                (self.items[i]["src"] == "ytdl" or self.items[i]["status"] in ("complete", "error"))]
        clean = [{k: v for k, v in it.items() if k not in ("hist",)} for it in keep]
        try:
            STORE.write_text(json.dumps(clean, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    def _boot(self):
        if not self.aria.start():
            self.error.emit("Download", self.aria.error)
            return
        while True:
            try:
                self._poll()
            except Exception:
                if not self.aria.alive():
                    time.sleep(1)
                    self.aria = Aria2()
                    self.aria.start()
            time.sleep(0.5)

    def _poll(self):
        keys = ["gid", "status", "totalLength", "completedLength", "downloadSpeed", "connections",
                "errorMessage", "files", "dir", "numSeeders"]
        res = self.aria.multicall([("aria2.tellActive", [keys]), ("aria2.tellWaiting", [0, 1000, keys]),
                                   ("aria2.tellStopped", [0, 1000, keys])])
        seen = set()
        for group in res:
            for d in group[0]:
                gid = "a:" + d["gid"]
                seen.add(gid)
                total, done = int(d["totalLength"]), int(d["completedLength"])
                spd = int(d["downloadSpeed"])
                path = d["files"][0]["path"] if d.get("files") and d["files"][0].get("path") else ""
                uri = ""
                if d.get("files") and d["files"][0].get("uris"):
                    uri = d["files"][0]["uris"][0]["uri"]
                name = Path(path).name if path else Path(urllib.parse.unquote(urllib.parse.urlparse(uri).path)).name or uri
                st = d["status"]
                if st == "removed":
                    try:
                        self.aria.call("aria2.removeDownloadResult", d["gid"])
                    except Exception:
                        pass
                    continue
                if gid not in self.items and gid in self._done_seen:
                    continue
                with self._lock:
                    it = self.items.get(gid)
                    if not it:
                        it = {"id": gid, "src": "aria2", "url": uri, "added": time.time(),
                              "start_done": done, "start_t": time.time(), "auto_retry": gid in self._gentle}
                        self.items[gid] = it
                        self.order.insert(0, gid)
                        self.added.emit(gid)
                    if uri and it.get("exp_uri") != uri:
                        it["exp_uri"], it["expires"] = uri, link_expiry(uri)
                    msg_l = (d.get("errorMessage") or "").lower()
                    exp_at = it.get("expires")
                    if spd > 0:
                        it["last_flow"] = time.time()
                    it["expired"] = bool(
                        (st == "error" and any(k in msg_l for k in ("403", "404", "410", "401", "forbidden",
                                                                     "not found", "gone", "unauthorized")))
                        or (exp_at and time.time() > exp_at and st in ("active", "waiting", "error")
                            and time.time() - it.get("last_flow", 0) > 20))
                    it.update(name=name or it.get("name", "…"), total=total, done=done, speed=spd,
                              connections=int(d.get("connections", 0)), path=path,
                              status={"waiting": "waiting", "paused": "paused", "active": "active",
                                      "complete": "complete", "error": "error", "removed": "removed"}[st],
                              eta=(total - done) / spd if spd and total else None,
                              error=d.get("errorMessage", ""))
                if st == "complete" and gid not in self._done_seen:
                    self._done_seen.add(gid)
                    self.finished.emit(gid)
                    try:
                        self.aria.call("aria2.removeDownloadResult", d["gid"])
                    except Exception:
                        pass
                    self.save()
                elif st == "error" and gid not in self._done_seen:
                    self._done_seen.add(gid)
                    msg = (d.get("errorMessage") or "").lower()
                    it = self.items.get(gid, {})
                    # Connessioni automatiche: se il server rifiuta troppe connessioni, riprova con meno
                    if it.get("url") and not it.get("auto_retry") and any(
                            k in msg for k in ("429", "503", "too many", "connection reset", "refused")):
                        url = it["url"]
                        self.items.pop(gid, None)
                        if gid in self.order:
                            self.order.remove(gid)
                        self.removed.emit(gid)
                        try:
                            self.aria.call("aria2.removeDownloadResult", d["gid"])
                        except Exception:
                            pass
                        self._add_aria(url, gentle=True)
                    else:
                        self.save()

    # ---- azioni ----
    def add(self, url: str, force_direct=False):
        url = url.strip()
        if force_direct:
            self._add_aria(url)
            return
        self.probe.run(url)

    def _probed(self, url, info):
        if info["kind"] == "ytdl":
            self.need_ytdl_choice.emit(url, info)
        else:
            self._add_aria(url)

    def _add_aria(self, url, gentle=False):
        def go():
            for _ in range(60):
                if self.aria.ok:
                    break
                time.sleep(0.25)
            try:
                opts = {"dir": settings.get("downloads", "dir")}
                if gentle:
                    opts.update({"split": "4", "max-connection-per-server": "4"})
                gid = self.aria.call("aria2.addUri", [url], opts)
                if gentle:
                    self._gentle.add("a:" + gid)
            except Exception as e:
                self.error.emit("Couldn't add the download", str(e))
        threading.Thread(target=go, daemon=True).start()

    def add_ytdl(self, url, info, opts):
        iid = "y:" + secrets.token_hex(6)
        it = {"id": iid, "src": "ytdl", "url": url, "name": info.get("title", url), "total": 0, "done": 0,
              "speed": 0, "status": "waiting", "dir": settings.get("downloads", "dir"), "added": time.time(),
              "start_t": time.time(), "start_done": 0, **opts}
        self.items[iid] = it
        self.order.insert(0, iid)
        self.added.emit(iid)
        self._start_ytdl(iid)
        self.save()

    def _start_ytdl(self, iid):
        it = self.items[iid]
        it.update(status="waiting", error="", start_t=time.time(), start_done=it.get("done", 0))
        j = YtdlJob(it, self)
        self.jobs[iid] = j
        j.start()

    # ---- link scaduti ----
    def renew(self, iid, new_url):
        """Sostituisce il link scaduto con uno nuovo dello stesso file e riprende da dove era arrivato."""
        it = self.items.get(iid)
        if not it or it.get("src") != "aria2":
            return

        def go():
            info = probe(new_url)
            if not info.get("ok"):
                self.renewed.emit(iid, False, "This link doesn't work either." if info.get("expired")
                                  else "Link unreachable.")
                return
            if it.get("total") and info.get("size") and info["size"] != it["total"]:
                self.renewed.emit(iid, False, "It's a different file (different size): copy the link of the same file.")
                return
            gid = iid[2:]
            try:
                if it.get("status") in ("active", "waiting", "paused"):
                    old = it.get("url") or ""
                    self.aria.call("aria2.changeUri", gid, 1, [old] if old else [], [new_url])
                    if it.get("status") == "paused":
                        self.aria.call("aria2.unpause", gid)
                    it.update(url=new_url, expired=False, last_flow=time.time())
                else:
                    path = it.get("path") or ""
                    opts = {"dir": str(Path(path).parent) if path else settings.get("downloads", "dir")}
                    if path:
                        opts["out"] = Path(path).name     # stesso file: aria2 riprende dai pezzi già scaricati
                    try:
                        self.aria.call("aria2.removeDownloadResult", gid)
                    except Exception:
                        pass
                    with self._lock:
                        self.items.pop(iid, None)
                        if iid in self.order:
                            self.order.remove(iid)
                    self.removed.emit(iid)
                    self.aria.call("aria2.addUri", [new_url], opts)
                self.renewed.emit(iid, True, "")
            except Exception as e:
                self.renewed.emit(iid, False, str(e)[:160])
        threading.Thread(target=go, daemon=True).start()

    def set_player_priority(self, on: bool):
        """Mentre guardi un film dalla rete, i download vanno piano per non rubargli banda."""
        if getattr(self, "_prio", None) == on:
            return
        self._prio = on
        lim = "3M" if on else f"{int(settings.get('downloads', 'limit_kb'))}K"
        self._rpc("aria2.changeGlobalOption", {"max-overall-download-limit": lim})

    def pause(self, iid):
        it = self.items.get(iid)
        if not it:
            return
        if it["src"] == "aria2":
            self._rpc("aria2.forcePause", iid[2:])
        elif iid in self.jobs:
            self.jobs[iid].stop_flag = True

    def resume(self, iid):
        it = self.items.get(iid)
        if not it:
            return
        it["start_t"], it["start_done"] = time.time(), it.get("done", 0)
        if it["src"] == "aria2":
            if it["status"] == "error":
                url = it.get("url")
                self.remove(iid, keep_list=False)
                if url:
                    self._add_aria(url)
            else:
                self._rpc("aria2.unpause", iid[2:])
        else:
            self._start_ytdl(iid)

    def retry(self, iid):
        self.resume(iid)

    def remove(self, iid, delete_file=False, keep_list=False):
        it = self.items.get(iid)
        if not it:
            return
        if it["src"] == "aria2" and it["status"] not in ("complete",):
            self._rpc("aria2.forceRemove", iid[2:])
        if it["src"] == "ytdl" and iid in self.jobs:
            self.jobs[iid].stop_flag = True
        if delete_file and it.get("path"):
            for p in (it["path"], it["path"] + ".aria2", it["path"] + ".part"):
                try:
                    os.remove(p)
                except OSError:
                    pass
        if not keep_list:
            self.items.pop(iid, None)
            if iid in self.order:
                self.order.remove(iid)
            self.removed.emit(iid)
        self.save()

    def clear_completed(self):
        for iid in [i for i in self.order if self.items.get(i, {}).get("status") == "complete"]:
            self.remove(iid)

    def to_top(self, iid):
        if iid.startswith("a:"):
            self._rpc("aria2.changePosition", iid[2:], 0, "POS_SET")

    def limit(self, iid, kb):
        if iid.startswith("a:"):
            self._rpc("aria2.changeOption", iid[2:], {"max-download-limit": f"{int(kb)}K"})

    def apply_global(self):
        ds = settings.data["downloads"]
        self._rpc("aria2.changeGlobalOption", {
            "max-overall-download-limit": f"{int(ds['limit_kb'])}K",
            "max-concurrent-downloads": str(int(ds["parallel"])),
            "split": str(int(ds["connections"])),
            "max-connection-per-server": str(min(16, int(ds["connections"]))),
            "dir": ds["dir"]})

    def _rpc(self, method, *args):
        def go():
            try:
                self.aria.call(method, *args)
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def _organize(self, iid):
        it = self.items.get(iid)
        if not it or not settings.get("downloads", "organize"):
            return
        p = Path(it.get("path") or "")
        if not p.is_file():
            return
        base = Path(settings.get("downloads", "dir"))
        if p.parent != base:
            return
        dst = unique_path(Path(category_dir(str(base), p.name)) / p.name)
        try:
            shutil.move(str(p), str(dst))
            it["path"] = str(dst)
            it["name"] = dst.name
            self.save()
        except Exception:
            pass

    def retry_errors(self) -> int:
        """Riprova tutti i download finiti in errore (pulsante Aggiorna)."""
        bad = [iid for iid, it in list(self.items.items()) if it.get("status") == "error"]
        for iid in bad:
            try:
                self.retry(iid)
            except Exception:
                pass
        return len(bad)

    def stats(self):
        act = [i for i in list(self.items.values()) if i["status"] in ("active", "waiting")]
        spd = sum(i.get("speed", 0) or 0 for i in act)
        tot = sum(i.get("total", 0) or 0 for i in act)
        done = sum(i.get("done", 0) or 0 for i in act)
        return len(act), spd, (done / tot if tot else 0)

    def shutdown(self):
        for j in self.jobs.values():
            j.stop_flag = True
        self.save()
        self.aria.stop()


# ------------------------------------------------------------------ UI
STATUS = {
    "active": ("Downloading", "accent"), "waiting": ("Queued", "text2"), "paused": ("Paused", "warning"),
    "complete": ("Completed", "success"), "error": ("Error", "danger"), "removed": ("Removed", "text3"),
    "seeding": ("In seed", "info"), "checking": ("Checking", "text2"), "metadata": ("Metadata…", "text2"),
    "choose": ("Choose files", "warning"),
}


def file_icon(name):
    ext = Path(name or "").suffix.lower()
    return "film" if ext in VIDEO_EXT else "music" if ext in AUDIO_EXT else "file"


class DownloadCard(Card):
    """Card di un download con barra animata, velocità, ETA e sparkline."""

    def __init__(self, iid: str, page, torrent=False):
        super().__init__()
        self.iid = iid
        self.page = page
        self.torrent = torrent
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        h = QHBoxLayout(self)
        h.setContentsMargins(theme.s(16), theme.s(14), theme.s(12), theme.s(14))
        h.setSpacing(theme.s(14))
        self.ic = label("")
        self.ic.setFixedSize(44, 44)
        self.ic.setAlignment(Qt.AlignCenter)
        self.ic.setStyleSheet(f"background:{theme.accent_soft};border-radius:12px;")
        h.addWidget(self.ic, 0, Qt.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(theme.s(6))
        top = QHBoxLayout()
        self.name = label("…")
        self.name.setStyleSheet("font-weight:600;")
        self.name.setMinimumWidth(80)
        self.pill = Pill()
        top.addWidget(self.name, 1)
        top.addWidget(self.pill)
        v.addLayout(top)
        self.bar = AnimatedProgress(height=6)
        v.addWidget(self.bar)
        info = QHBoxLayout()
        self.l_size = label("", "faint")
        self.l_info = label("", "faint")
        info.addWidget(self.l_size)
        info.addStretch()
        info.addWidget(self.l_info)
        v.addLayout(info)
        h.addLayout(v, 1)
        self.spark = Sparkline()
        h.addWidget(self.spark, 0, Qt.AlignVCenter)
        self.btns = QHBoxLayout()
        self.btns.setSpacing(2)
        self.b_pause = IconButton("pause", "Pause", 34, 18)
        self.b_play = IconButton("play", "Play", 34, 18)
        self.b_folder = IconButton("folder", "Open folder", 34, 18)
        self.b_conv = IconButton("convert", "Convert MKV/MP4", 34, 18)
        self.b_x = IconButton("x", "Remove", 34, 18)
        self.b_renew = IconButton("link", "Link expired: paste a new link to the same file", 34, 18,
                                  color=theme.warning)
        self.b_renew.hide()
        for b in (self.b_renew, self.b_pause, self.b_play, self.b_conv, self.b_folder, self.b_x):
            self.btns.addWidget(b)
        h.addLayout(self.btns)
        self.b_pause.clicked.connect(self._toggle)
        self.b_play.clicked.connect(lambda: page.play_item(self.iid))
        self.b_folder.clicked.connect(lambda: page.open_folder(self.iid))
        self.b_conv.clicked.connect(lambda: page.convert_menu(self.iid, self.b_conv))
        self.b_x.clicked.connect(lambda: page.remove_item(self.iid))
        self.b_renew.clicked.connect(lambda: page.renew_item(self.iid))
        self._status = None

    def _toggle(self):
        it = self.page.get(self.iid)
        if not it:
            return
        if it["status"] in ("active", "waiting", "seeding", "metadata", "checking"):
            self.page.pause_item(self.iid)
        else:
            self.page.resume_item(self.iid)

    def _menu(self, pos):
        self.page.context_menu(self.iid, self.mapToGlobal(pos))

    def refresh(self, it: dict):
        st = it.get("status", "waiting")
        nm = it.get("name") or "…"
        if self.name.text() != nm:
            self.name.setText(nm if len(nm) < 90 else nm[:87] + "…")
            self.name.setToolTip(nm)
            self.ic.setPixmap(icons.pixmap("magnet" if self.torrent and st == "metadata" else file_icon(nm),
                                           theme.accent, 22))
        lbl, colkey = STATUS.get(st, (st, "text2"))
        if it.get("stage_text"):
            lbl = it["stage_text"]
        col = theme.accent if colkey == "accent" else getattr(theme, colkey)
        if self._status != (st, lbl):
            self.pill.set(lbl, col)
            self._status = (st, lbl)
        total, done = it.get("total") or 0, it.get("done") or 0
        frac = it.get("progress") if it.get("progress") is not None else (done / total if total else 0)
        self.bar.set_indeterminate(st in ("metadata",) or (st == "active" and not total and not frac))
        self.bar.set_value(1.0 if st in ("complete", "seeding") else (0 if st == "choose" else frac),
                           theme.success if st in ("complete", "seeding") else
                           theme.danger if st == "error" else theme.warning if st == "paused" else theme.accent)
        spd = it.get("speed") or 0
        self.spark.push(spd)
        self.spark.setVisible(st in ("active", "seeding", "waiting"))
        self.l_size.setText(f"{human_size(done)} / {human_size(total)}  ·  {frac * 100:.1f}%" if total
                            else human_size(done))
        if st != "choose" and st != "error":
            self.l_info.setStyleSheet("")
        if st == "active":
            el = max(1e-3, time.time() - it.get("start_t", time.time()))
            avg = max(0, (done - it.get("start_done", 0))) / el
            parts = [f"↓ {human_speed(spd)}", f"media {human_speed(avg)}", f"{human_eta(it.get('eta'))} left"]
            if it.get("connections"):
                parts.append(f"{it['connections']} conn.")
            if self.torrent:
                parts = [f"↓ {human_speed(spd)}", f"↑ {human_speed(it.get('up', 0))}",
                         f"{human_eta(it.get('eta'))}", f"{it.get('peers', 0)} peer · {it.get('seeds', 0)} seed"]
            self.l_info.setText("  ·  ".join(parts))
        elif st == "seeding":
            self.l_info.setText(f"↑ {human_speed(it.get('up', 0))}  ·  ratio {it.get('ratio', 0):.2f}  ·  {it.get('peers', 0)} peer")
        if it.get("expired") and not self.torrent:
            self.pill.set("Link expired", theme.warning)
            self._status = None
            self.l_info.setStyleSheet(f"color:{theme.warning};")
            self.l_info.setText("Copy a new link to the same file from the website and press 🔗: it resumes from here without losing what's already downloaded")
        elif st == "active" and it.get("expires") and not self.torrent:
            left = it["expires"] - time.time()
            late = it.get("eta") and it["eta"] > left
            self.l_info.setText(self.l_info.text() + f"  ·  link expires in {human_eta(left)}")
            self.l_info.setStyleSheet(f"color:{theme.warning};" if late else "")
        elif st == "choose":
            self.l_info.setStyleSheet(f"color:{theme.warning};")
            self.l_info.setText("No file selected: press ▶ to choose")
        elif st == "error":
            self.l_info.setText((it.get("error") or "Error")[:120])
            self.l_info.setStyleSheet(f"color:{theme.danger};")
        elif st not in ("active", "seeding"):
            self.l_info.setStyleSheet("")
            self.l_info.setText("")
        self.b_renew.setVisible(bool(it.get("expired")) and not self.torrent)
        active = st in ("active", "waiting", "seeding", "metadata", "checking")
        self.b_pause.set_icon("pause" if active else ("retry" if st == "error" else "play"))
        self.b_pause.setToolTip("Pause" if active else "Retry" if st == "error" else "Resume")
        self.b_pause.setVisible((st != "complete" or self.torrent) and st != "choose")
        path = it.get("path") or ""
        is_media = Path(nm).suffix.lower() in VIDEO_EXT | AUDIO_EXT
        if self.torrent:
            self.b_play.setVisible(bool(it.get("streamable")) or st == "choose")
            self.b_play.setToolTip("Choose files" if st == "choose" else "Watch (even while downloading)")
        else:
            self.b_play.setVisible(is_media and st == "complete")
        self.b_conv.setVisible(st in ("complete", "seeding") and Path(nm).suffix.lower() in (".mkv", ".mp4", ".webm", ".mov", ".ts", ".m2ts", ".avi"))
        self.b_folder.setVisible(bool(path) or self.torrent)


class DownloadsPage(QWidget):
    play = Signal(str)
    toast = Signal(str, str, str)  # titolo, testo, tipo

    def __init__(self, mgr: DownloadManager, parent=None):
        super().__init__(parent)
        self.mgr = mgr
        self.cards: dict[str, DownloadCard] = {}
        self.remux_jobs = {}
        root = QVBoxLayout(self)
        m = theme.s(28)
        root.setContentsMargins(m, m - 4, m, m)
        root.setSpacing(theme.s(16))
        hdr = PageHeader("Downloads", "Paste a link: direct files with multiple connections, video pages through yt-dlp.")
        root.addWidget(hdr)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setObjectName("bigInput")
        self.input.setPlaceholderText("Paste a link to download…")
        self.input.returnPressed.connect(self._add)
        paste = IconButton("clipboard", "Paste", 46, 20)
        paste.clicked.connect(lambda: (self.input.setText(QApplication.clipboard().text().strip()), self._add()))
        add = button("Download", "primary", "download", self._add)
        row.addWidget(self.input, 1)
        row.addWidget(paste)
        row.addWidget(add)
        root.addLayout(row)
        self.probe_bar = AnimatedProgress(height=3)
        self.probe_bar.set_indeterminate(True)
        self.probe_bar.hide()
        root.addWidget(self.probe_bar)
        self.hero = SpeedHero()
        root.addWidget(self.hero)

        filt = QHBoxLayout()
        self.filter = Segmented([("all", "All"), ("active", "Active"), ("complete", "Completed"),
                                 ("error", "Errors")], "all")
        self.filter.changed.connect(lambda _: self._apply_filter())
        filt.addWidget(self.filter)
        filt.addStretch()
        self.summary = label("", "muted")
        filt.addSpacing(10)
        filt.addWidget(button("Clear completed", "ghost", "trash", mgr.clear_completed))
        filt.addWidget(button("Folder", "ghost", "folder",
                              lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(settings.get("downloads", "dir")))))
        root.addLayout(filt)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(theme.s(10))
        self.empty = EmptyState("download", "No downloads",
                                "Paste a link above. When you copy a link, NOVA suggests it automatically.")
        self.list.addWidget(self.empty)
        self.list.addStretch()
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)

        mgr.added.connect(self._added)
        mgr.removed.connect(self._removed)
        mgr.finished.connect(self._finished)
        mgr.error.connect(self._mgr_error)
        mgr.need_ytdl_choice.connect(self._ytdl_choice)
        mgr.renewed.connect(self._renewed)
        mgr.probe.done.connect(self._probe_done)
        for iid in mgr.order:
            self._added(iid, anim=False)
        self.timer = QTimer(self, interval=400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

    def get(self, iid):
        return self.mgr.items.get(iid)

    def showEvent(self, e):
        self.timer.start()
        self.refresh()

    def hideEvent(self, e):
        self.timer.stop()

    def _mgr_error(self, t, m):
        self.toast.emit(t, m, "err")

    def _probe_done(self, *a):
        self.probe_bar.hide()

    def add_url(self, url):
        self.input.setText(url)
        self._add()

    def _add(self):
        u = self.input.text().strip()
        if not u.startswith(("http://", "https://", "ftp://")):
            if u:
                self.toast.emit("Invalid link", "Use an http(s) or ftp link. For torrents use the Torrent section.", "warn")
            return
        self.input.clear()
        self.probe_bar.show()
        self.mgr.add(u)

    def _ytdl_choice(self, url, info):
        d = YtdlDialog(self.window(), info)
        if d.exec():
            self.mgr.add_ytdl(url, info, d.result_opts())

    def _added(self, iid, anim=True):
        if iid in self.cards:
            return
        c = DownloadCard(iid, self)
        self.cards[iid] = c
        self.list.insertWidget(0, c)
        it = self.mgr.items.get(iid)
        if it:
            c.refresh(it)
        self.empty.hide()
        if anim:
            animate_in(c)
        self._apply_filter()

    def _removed(self, iid):
        c = self.cards.pop(iid, None)
        if c:
            c.deleteLater()
        self.empty.setVisible(not self.cards)

    def _finished(self, iid):
        it = self.mgr.items.get(iid, {})
        name = it.get("name", "File")
        acts = [("Open folder", lambda: self.open_folder(iid))]
        if Path(name).suffix.lower() in VIDEO_EXT | AUDIO_EXT:
            acts.insert(0, ("Play", lambda: self.play_item(iid)))
        self.window().notify("Download complete", name, acts)

    def refresh(self):
        for iid, c in list(self.cards.items()):
            it = self.mgr.items.get(iid)
            if it and c.isVisible():
                c.refresh(it)
        n, spd, frac = self.mgr.stats()
        self.hero.update_speed(spd, f"{n} active downloads" if n else "No active downloads")

    def _apply_filter(self):
        f = self.filter.value
        for iid, c in self.cards.items():
            st = self.mgr.items.get(iid, {}).get("status")
            vis = f == "all" or (f == "active" and st in ("active", "waiting", "paused")) or st == f
            c.setVisible(vis)

    # azioni card
    def pause_item(self, iid):
        self.mgr.pause(iid)

    def resume_item(self, iid):
        self.mgr.resume(iid)

    def renew_item(self, iid):
        clip = QApplication.clipboard().text().strip()
        url = clip if clip.startswith(("http://", "https://")) else ""
        if not url:
            url, ok = QInputDialog.getText(self, "New link", "Paste the new link to the same file:")
            if not ok or not url.strip().startswith(("http://", "https://")):
                return
        self.toast.emit("Checking the new link…", "", "info")
        self.mgr.renew(iid, url.strip())

    def _renewed(self, iid, ok, msg):
        if ok:
            self.toast.emit("Link renewed", "The download resumes from where it stopped.", "ok")
        else:
            self.toast.emit("Invalid link", msg, "err")

    def remove_item(self, iid):
        it = self.mgr.items.get(iid, {})
        if it.get("status") == "complete":
            self.mgr.remove(iid)
        else:
            self.mgr.remove(iid, delete_file=True)

    def play_item(self, iid):
        p = self.mgr.items.get(iid, {}).get("path")
        if p and os.path.exists(p):
            self.play.emit(p)
        else:
            self.toast.emit("File not found", "The file was moved or deleted.", "warn")

    def open_folder(self, iid):
        p = self.mgr.items.get(iid, {}).get("path") or settings.get("downloads", "dir")
        reveal(p)

    def convert_menu(self, iid, anchor):
        p = self.mgr.items.get(iid, {}).get("path")
        if p:
            convert_menu(self, p, anchor)

    def context_menu(self, iid, gpos):
        it = self.mgr.items.get(iid, {})
        m = QMenu(self)
        if it.get("url"):
            m.addAction("Copy link", lambda: QApplication.clipboard().setText(it["url"]))
        if it.get("src") == "aria2" and it.get("status") in ("waiting", "paused", "active"):
            m.addAction("High priority", lambda: self.mgr.to_top(iid))
            m.addAction("Limit speed…", lambda: self._limit(iid))
        if it.get("status") == "complete":
            m.addAction("Remove from list", lambda: self.mgr.remove(iid))
            m.addAction("Delete file", lambda: self.mgr.remove(iid, delete_file=True))
        else:
            m.addAction("Cancel and delete", lambda: self.mgr.remove(iid, delete_file=True))
        m.exec(gpos)

    def _limit(self, iid):
        kb, ok = QInputDialog.getInt(self, "Speed limit", "KB/s (0 = unlimited):", 0, 0, 10_000_000, 100)
        if ok:
            self.mgr.limit(iid, kb)


def reveal(path: str):
    p = Path(path)
    if sys.platform == "win32" and p.exists():
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            os.startfile(str(p))
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p if p.is_dir() else p.parent)))


_jobs = []


def convert_menu(page, path, anchor):
    from .remux import RemuxJob
    m = QMenu(page)
    ext = Path(path).suffix.lower()
    for tgt in ("mp4", "mkv"):
        if f".{tgt}" != ext:
            m.addAction(f"Convert to {tgt.upper()} (lossless)", lambda t=tgt: start_remux(page, path, t))
    m.addSeparator()
    m.addAction("Phone version (max 1.4 GB)", lambda: start_phone(page, path))
    m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))


def start_phone(page, src, title=None):
    """MP4 720p sotto 1,4 GB, audio nella lingua preferita: da un file o direttamente da un link."""
    from .remux import PhoneJob
    from .names import parse, display
    win = page.window()
    title = title or display(parse(Path(src).name if os.path.exists(src) else src)) or "video"
    out = str(Path(settings.get("downloads", "dir")) / "For phone")
    langs = [x.strip() for x in settings.get("player", "audio_lang").split(",") if x.strip()]
    job = PhoneJob(src, out, title, langs)
    _jobs.append(job)
    t = win.toasts.show("Phone version…", title + " · MP4 720p, max 1,4 GB",
                        [("Cancel", job.cancel)], "info", timeout=0)
    bar = AnimatedProgress(height=4)
    info = label("Preparing…", "faint")
    lay = t.layout().itemAt(1).layout()
    lay.insertWidget(2, bar)
    lay.insertWidget(3, info)
    t.adjustSize()
    win.toasts.layout()
    t0 = [None]

    def prog(v):
        import time as _t
        try:
            bar.set_value(v)
            if t0[0] is None and v > 0:
                t0[0] = (_t.time(), v)
            if t0[0] and v > t0[0][1]:
                el = _t.time() - t0[0][0]
                rate = (v - t0[0][1]) / el if el > 0 else 0
                eta = (1 - v) / rate if rate > 0 else 0
                spd = rate * job.duration if job.duration else 0
                info.setText(f"{v * 100:.0f}%  ·  {spd:.1f}x  ·  {human_eta(eta)} left  ·  {(job.notes or [''])[0].replace('Conversion: ', '').rstrip('.')}")
        except RuntimeError:
            pass
    job.progress.connect(prog)

    def done(ok, res, notes):
        try:
            t.close_anim()
        except RuntimeError:
            pass
        if ok:
            size = Path(res).stat().st_size / 1e9 if Path(res).exists() else 0
            win.notify("Ready for the phone", f"{Path(res).name} · {size:.2f} GB",
                       [("Open folder", lambda: reveal(res)), ("Play", lambda: win.play(res))])
        else:
            win.toasts.show("Conversion failed", res, None, "err")
        _jobs.remove(job)
    job.finished.connect(done)
    job.start()


def start_remux(page, path, target):
    from .remux import RemuxJob
    win = page.window()
    job = RemuxJob(path, target)
    _jobs.append(job)
    t = win.toasts.show(f"Converting to {target.upper()}…", Path(path).name, None, "info", timeout=0)
    bar = AnimatedProgress(height=4)
    t.layout().itemAt(1).layout().addWidget(bar)
    t.adjustSize()
    win.toasts.layout()
    job.progress.connect(lambda v: bar.set_value(v))

    def done(ok, res, notes):
        try:
            t.close_anim()
        except RuntimeError:
            pass
        if ok:
            win.notify("Conversion complete", Path(res).name + ("\n" + "\n".join(notes) if notes else ""),
                       [("Play", lambda: win.play(res)), ("Open folder", lambda: reveal(res))])
        else:
            win.toasts.show("Conversion failed", res, None, "err")
        _jobs.remove(job)
    job.finished.connect(done)
    job.start()
