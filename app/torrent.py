"""Modulo Torrent: libtorrent, selezione file, streaming sequenziale e remux."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QScrollArea, QDialog,
                               QTreeWidget, QTreeWidgetItem, QFileDialog, QHeaderView, QMenu,
                               QApplication, QCheckBox)

from . import icons
from .config import settings, DATA, VIDEO_EXT, AUDIO_EXT, human_size, human_speed
from .theme import theme
from .widgets import (PageHeader, Card, label, button, IconButton, EmptyState, Toggle, animate_in,
                      AnimatedProgress, Pill, SpeedHero)
from .downloads import DownloadCard, reveal, convert_menu
from .debrid import RealDebrid

# libtorrent richiede MSVCP140.dll: PySide6 la include, la rendiamo trovabile come ripiego
if os.name == "nt":
    try:
        import PySide6
        os.add_dll_directory(os.path.dirname(PySide6.__file__))
    except Exception:
        pass
try:
    import libtorrent as lt
    LT_ERROR = None
except Exception as e:
    lt = None
    LT_ERROR = str(e)

TDIR = DATA / "torrents"

# Tracker pubblici aggiunti ai magnet: trovano molti più peer, molto prima.
# La lista si aggiorna da sola ogni giorno (ngosang/trackerslist); questi sono il ripiego.
PUBLIC_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.demonii.com:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
    "udp://explodie.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
    "udp://opentracker.io:6969/announce",
    "udp://tracker.tiny-vps.com:6969/announce",
    "https://tracker.tamersunion.org:443/announce",
    "http://tracker.opentrackr.org:1337/announce",
]


TRACKERS_FILE = DATA / "trackers.txt"
TRACKERS_URL = "https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt"


def _load_cached_trackers():
    try:
        lines = [l.strip() for l in TRACKERS_FILE.read_text("utf-8").splitlines() if l.strip()]
        if lines:
            PUBLIC_TRACKERS[:] = list(dict.fromkeys(lines + PUBLIC_TRACKERS))[:40]
    except OSError:
        pass


def update_trackers():
    """Scarica la lista dei tracker attivi (al massimo una volta al giorno)."""
    _load_cached_trackers()
    try:
        if TRACKERS_FILE.exists() and time.time() - TRACKERS_FILE.stat().st_mtime < 86400:
            return
        import urllib.request
        with urllib.request.urlopen(urllib.request.Request(TRACKERS_URL, headers={"User-Agent": "NOVA"}),
                                    timeout=15) as r:
            txt = r.read().decode("utf-8", "ignore")
        good = [l.strip() for l in txt.splitlines() if l.strip().startswith(("udp://", "http://", "https://"))]
        if len(good) >= 5:
            TRACKERS_FILE.write_text("\n".join(good), "utf-8")
            _load_cached_trackers()
    except Exception:
        pass


def files_of(ti):
    fs = ti.files()
    out = []
    for i in range(fs.num_files()):
        if fs.file_flags(i) & fs.flag_pad_file:
            continue
        out.append((i, fs.file_path(i), fs.file_size(i)))
    return out


# ------------------------------------------------------------------ streaming HTTP
class StreamServer:
    """Serve i file di un torrent in download via HTTP (con Range), attendendo i pezzi mancanti."""

    def __init__(self, mgr: "TorrentManager"):
        self.mgr = mgr
        mgr_ref = mgr

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_HEAD(self):
                self._serve(head=True)

            def do_GET(self):
                self._serve(head=False)

            def _serve(self, head):
                m = re.match(r"^/([0-9a-f]+)/(\d+)/", self.path)
                t = mgr_ref.items.get(m.group(1)) if m else None
                if not t or not t["h"].has_metadata():
                    self.send_error(404)
                    return
                h, idx = t["h"], int(m.group(2))
                ti = h.torrent_file()
                fs = ti.files()
                size = fs.file_size(idx)
                fpath = os.path.join(h.status().save_path, fs.file_path(idx))
                start, end = 0, size - 1
                rng = self.headers.get("Range")
                if rng:
                    mm = re.match(r"bytes=(\d*)-(\d*)", rng)
                    if mm:
                        if mm.group(1):
                            start = int(mm.group(1))
                            if mm.group(2):
                                end = min(size - 1, int(mm.group(2)))
                        elif mm.group(2):
                            start = max(0, size - int(mm.group(2)))
                if start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206 if rng else 200)
                ext = Path(fpath).suffix.lower()
                ctype = {".mkv": "video/x-matroska", ".mp4": "video/mp4", ".webm": "video/webm"}.get(ext, "application/octet-stream")
                self.send_header("Content-Type", ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if rng:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head:
                    return
                plen = ti.piece_length()
                foff = fs.file_offset(idx)
                npieces = ti.num_pieces()
                pos = start
                f = None
                last_piece = None
                try:
                    while pos <= end:
                        piece = (foff + pos) // plen
                        if last_piece is None or piece > last_piece + 64 or piece < last_piece:
                            h.clear_piece_deadlines()   # salto (seek): conta solo la nuova posizione
                        if piece != last_piece:
                            self._prioritize(h, piece, npieces, plen)
                            last_piece = piece
                        waited = 0.0
                        while not h.have_piece(piece):
                            time.sleep(0.05)
                            waited += 0.05
                            if waited > 900 or not h.is_valid():
                                return
                        piece_end = (piece + 1) * plen - foff
                        chunk_end = min(end, piece_end - 1)
                        n = chunk_end - pos + 1
                        data = b""
                        try:
                            if f is None:
                                f = open(fpath, "rb", buffering=0)
                            f.seek(pos)
                            data = f.read(n)
                        except OSError:
                            f = None
                        if len(data) < n:
                            # file bloccato o non ancora scritto su disco: chiedo il pezzo a libtorrent
                            buf = mgr_ref.read_piece(h, piece)
                            if buf is None:
                                time.sleep(0.2)
                                continue
                            off = (foff + pos) - piece * plen
                            data = buf[off:off + n]
                            if len(data) < n:
                                time.sleep(0.2)
                                continue
                        self.wfile.write(data)
                        pos += n
                except (ConnectionError, BrokenPipeError, OSError):
                    return
                finally:
                    if f:
                        f.close()

            @staticmethod
            def _prioritize(h, piece, npieces, plen):
                # finestra di ~48 MB davanti alla posizione di lettura, con scadenze crescenti
                n = max(16, min(256, (48 * 1024 * 1024) // plen))
                for k in range(n):
                    p = piece + k
                    if p >= npieces:
                        break
                    if not h.have_piece(p):
                        h.set_piece_deadline(p, 150 + k * 40)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def url(self, tid, idx, name):
        return f"http://127.0.0.1:{self.port}/{tid}/{idx}/{urllib.parse.quote(Path(name).name)}"


# ------------------------------------------------------------------ manager
class TorrentManager(QObject):
    added = Signal(str)
    removed = Signal(str)
    metadata = Signal(str)       # serve la scelta dei file
    instant_ready = Signal(str)  # link istantaneo pronto
    suspicious = Signal(str, str)  # torrent che sembra un falso: id, motivo
    finished = Signal(str)
    error = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.items: dict[str, dict] = {}
        self.order: list[str] = []
        self.ses = None
        self.server = None
        if lt is None:
            return
        ts = settings.data["torrent"]
        enc = 1 if ts["encryption"] else 2
        self.ses = lt.session(self._session_settings())
        self.server = StreamServer(self)
        self._load()
        self._asked: set = set()
        self._pieces: dict = {}
        self._piece_ev: dict = {}
        self._plock = threading.Lock()
        self.incoming = False
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.pump = QTimer(self, interval=60)   # alert veloci: lo streaming non aspetta
        self.pump.timeout.connect(self._handle_alerts)
        self.pump.start()
        self._last_save = time.time()
        threading.Thread(target=update_trackers, daemon=True).start()

    @staticmethod
    def _session_settings() -> dict:
        """Profilo 'turbo': tante connessioni, DHT veloce, tutti i tracker, code di richiesta profonde."""
        ts = settings.data["torrent"]
        enc = 1 if ts["encryption"] else 2
        return {
            "listen_interfaces": f"0.0.0.0:{ts['port']},[::]:{ts['port']}",
            "enable_dht": True, "enable_lsd": True, "enable_upnp": True, "enable_natpmp": True,
            "dht_bootstrap_nodes": "dht.libtorrent.org:25401,router.bittorrent.com:6881,"
                                   "router.utorrent.com:6881,dht.transmissionbt.com:6881,dht.aelitis.com:6881",
            "alert_mask": lt.alert.category_t.status_notification | lt.alert.category_t.error_notification
            | lt.alert.category_t.storage_notification,
            "download_rate_limit": int(ts["down_limit_kb"]) * 1024,
            "upload_rate_limit": int(ts["up_limit_kb"]) * 1024,
            "out_enc_policy": enc, "in_enc_policy": enc, "prefer_rc4": False,
            # connessioni: più peer, collegati più in fretta
            "connections_limit": 800, "connection_speed": 200, "torrent_connect_boost": 100,
            "peer_connect_timeout": 7, "min_reconnect_time": 20, "max_failcount": 2,
            "max_peerlist_size": 8000, "listen_queue_size": 64, "smooth_connects": False,
            "announce_to_all_trackers": True, "announce_to_all_tiers": True,
            # throughput: code di richiesta lunghe per connessioni veloci
            "request_queue_time": 5, "max_out_request_queue": 1500, "max_allowed_in_request_queue": 4000,
            "send_buffer_watermark": 3 * 1024 * 1024, "send_buffer_low_watermark": 1024 * 1024,
            "send_buffer_watermark_factor": 150, "whole_pieces_threshold": 5,
            "unchoke_slots_limit": 20, "mixed_mode_algorithm": 0,
            # disco
            "aio_threads": 16, "hashing_threads": 4, "max_queued_disk_bytes": 512 * 1024 * 1024,
            "checking_mem_usage": 1024,
            # più torrent attivi insieme
            "active_downloads": 8, "active_seeds": 8, "active_limit": 1000, "auto_manage_startup": 20,
            "dht_upload_rate_limit": 64000,
            "user_agent": "NOVA/1.0 libtorrent/" + lt.__version__,
        }

    # ---- persistenza ----
    def _load(self):
        for f in sorted(TDIR.glob("*.resume"), key=lambda p: p.stat().st_mtime):
            try:
                atp = lt.read_resume_data(f.read_bytes())
                meta_f = f.with_suffix(".json")
                meta = json.loads(meta_f.read_text("utf-8")) if meta_f.exists() else {}
                h = self.ses.add_torrent(atp)
                self._register(h, meta)
            except Exception:
                continue

    def _meta_save(self, tid):
        it = self.items.get(tid)
        if not it:
            return
        meta = {k: it.get(k) for k in ("added", "selected", "stream_idx", "done_notified", "need_select", "instant")}
        (TDIR / f"{tid}.json").write_text(json.dumps(meta), "utf-8")

    def save_all(self, wait=False):
        if not self.ses:
            return
        n = 0
        for it in self.items.values():
            h = it["h"]
            if h.is_valid() and h.need_save_resume_data():
                h.save_resume_data(lt.save_resume_flags_t.save_info_dict)
                n += 1
        if wait:
            end = time.time() + 5
            while n > 0 and time.time() < end:
                self.ses.wait_for_alert(500)
                n -= self._handle_alerts()

    def _check_fake(self, tid):
        from .safety import fake_verdict
        try:
            ti = self.items[tid]["h"].torrent_file()
            why = fake_verdict([(p, sz) for _, p, sz in files_of(ti)]) if ti else None
        except Exception:
            why = None
        if why:
            self.items[tid]["fake"] = why
            self.suspicious.emit(tid, why)

    # ---- aggiunta ----
    def _tid(self, h):
        return str(h.info_hashes().get_best())

    def _register(self, h, meta=None):
        tid = self._tid(h)
        it = {"id": tid, "h": h, "added": time.time(), "selected": None, "stream_idx": None,
              "done_notified": False, "need_select": False, "src": "torrent", "speed_hist": []}
        it.update({k: v for k, v in (meta or {}).items() if v is not None})
        self.items[tid] = it
        if tid not in self.order:
            self.order.insert(0, tid)
        self.added.emit(tid)
        self._meta_save(tid)
        return tid

    def add_magnet(self, uri: str, save_path: str):
        if not self.ses:
            self.error.emit("Torrent non disponibile", LT_ERROR or "")
            return
        atp = lt.parse_magnet_uri(uri)
        atp.save_path = save_path
        atp.trackers = list(atp.trackers) + [t for t in PUBLIC_TRACKERS if t not in atp.trackers]
        atp.flags |= lt.torrent_flags.default_dont_download
        if settings.get("torrent", "sequential"):
            atp.flags |= lt.torrent_flags.sequential_download
        tid = str(atp.info_hashes.get_best()) if hasattr(atp, "info_hashes") else None
        if tid and tid in self.items:
            self.error.emit("Torrent già presente", "Questo torrent è già nell'elenco.")
            return
        h = self.ses.add_torrent(atp)
        self._register(h, {"need_select": True})

    def add_instant(self, src: str, save_path: str):
        """Un clic: niente domande, scarica solo il video principale in sequenziale e avvisa quando è guardabile."""
        if not self.ses:
            self.error.emit("Torrent non disponibile", LT_ERROR or "")
            return None
        if src.startswith("magnet:"):
            atp = lt.parse_magnet_uri(src)
            atp.trackers = list(atp.trackers) + [t for t in PUBLIC_TRACKERS if t not in atp.trackers]
            atp.flags |= lt.torrent_flags.default_dont_download
        else:
            atp = lt.add_torrent_params()
            atp.ti = lt.torrent_info(Path(src).read_bytes())
            atp.trackers = list(PUBLIC_TRACKERS) if not atp.ti.priv() else []
            atp.file_priorities = [0] * atp.ti.files().num_files()
        atp.save_path = save_path
        atp.flags |= lt.torrent_flags.sequential_download
        tid = str(atp.info_hashes.get_best())
        if tid in self.items:
            it = self.items[tid]
            it["instant"] = True
            if it["h"].has_metadata():
                self._instant_select(tid)
            return tid
        h = self.ses.add_torrent(atp)
        self._register(h, {"instant": True})
        if h.has_metadata():
            self._instant_select(tid)
        return tid

    def _instant_select(self, tid):
        it = self.items[tid]
        h = it["h"]
        ti = h.torrent_file()
        vids = [(s, i) for i, p, s in files_of(ti) if Path(p).suffix.lower() in VIDEO_EXT]
        prios = [0] * ti.files().num_files()
        if vids:
            _, idx = max(vids)
            prios[idx] = 7
            it["stream_idx"] = idx
        else:
            prios = [4] * len(prios)
        h.prioritize_files(prios)
        h.set_flags(lt.torrent_flags.sequential_download)
        # primi e ultimi pezzi del file subito: mpv legge l'indice (moov/cues) da lì
        if vids:
            fs = ti.files()
            plen = ti.piece_length()
            first = fs.file_offset(idx) // plen
            last = (fs.file_offset(idx) + fs.file_size(idx) - 1) // plen
            for k, p in enumerate(list(range(first, min(first + 8, last + 1))) + list(range(max(first, last - 2), last + 1))):
                h.set_piece_deadline(p, 500 + k * 100)
        it.update(need_select=False, selected=[i for i, p in enumerate(prios) if p])
        self._meta_save(tid)
        self.instant_ready.emit(tid)

    def add_file(self, ti, save_path: str, priorities: list[int], sequential: bool, stream_idx=None):
        atp = lt.add_torrent_params()
        atp.ti = ti
        atp.save_path = save_path
        atp.file_priorities = priorities
        atp.trackers = list(PUBLIC_TRACKERS) if not ti.priv() else []
        if sequential:
            atp.flags |= lt.torrent_flags.sequential_download
        tid = str(ti.info_hashes().get_best())
        if tid in self.items:
            self.error.emit("Torrent già presente", "Questo torrent è già nell'elenco.")
            return None
        h = self.ses.add_torrent(atp)
        return self._register(h, {"selected": [i for i, p in enumerate(priorities) if p], "stream_idx": stream_idx})

    def apply_selection(self, tid, priorities, sequential, stream_idx=None):
        it = self.items[tid]
        h = it["h"]
        h.prioritize_files(priorities)
        if sequential:
            h.set_flags(lt.torrent_flags.sequential_download)
        else:
            h.unset_flags(lt.torrent_flags.sequential_download)
        it.update(need_select=False, selected=[i for i, p in enumerate(priorities) if p], stream_idx=stream_idx)
        self._meta_save(tid)

    # ---- azioni ----
    def pause(self, tid):
        h = self.items[tid]["h"]
        h.unset_flags(lt.torrent_flags.auto_managed)
        h.pause()

    def resume(self, tid):
        it = self.items[tid]
        h = it["h"]
        it["manual_resume"] = True
        h.set_flags(lt.torrent_flags.auto_managed)
        h.resume()

    def remove(self, tid, delete_files=False):
        it = self.items.pop(tid, None)
        if not it:
            return
        if tid in self.order:
            self.order.remove(tid)
        try:
            self.ses.remove_torrent(it["h"], lt.options_t.delete_files if delete_files else 0)
        except Exception:
            pass
        for ext in (".resume", ".json"):
            (TDIR / f"{tid}{ext}").unlink(missing_ok=True)
        self.removed.emit(tid)

    def set_player_priority(self, on: bool, except_tid: str | None = None):
        """Mentre guardi un film dalla rete, gli altri torrent scendono a 2 MB/s (quello che guardi resta libero)."""
        key = (on, except_tid)
        if getattr(self, "_prio", None) == key or not self.ses:
            return
        self._prio = key
        for tid, it in self.items.items():
            try:
                it["h"].set_download_limit(2 * 1024 * 1024 if on and tid != except_tid else -1)
            except Exception:
                pass

    def apply_settings(self):
        if self.ses:
            self.ses.apply_settings(self._session_settings())

    def best_video(self, tid):
        """Indice e percorso del file video principale (il più grande tra quelli selezionati)."""
        it = self.items.get(tid)
        if not it or not it["h"].has_metadata():
            return None
        h = it["h"]
        ti = h.torrent_file()
        prios = h.get_file_priorities()
        cands = [(s, i, p) for i, p, s in files_of(ti)
                 if Path(p).suffix.lower() in VIDEO_EXT | AUDIO_EXT and prios[i] > 0]
        if it.get("stream_idx") is not None:
            cands = [c for c in cands if c[1] == it["stream_idx"]] or cands
        if not cands:
            return None
        s, i, p = max(cands)
        return i, p

    def stream_url(self, tid):
        bv = self.best_video(tid)
        if not bv:
            return None
        i, p = bv
        it = self.items[tid]
        full = os.path.join(it["h"].status().save_path, p)
        if it["h"].status().is_finished and it["h"].file_progress()[i] >= it["h"].torrent_file().files().file_size(i):
            return full
        return self.server.url(tid, i, p)

    # ---- ciclo ----
    def read_piece(self, h, piece, timeout=10.0):
        """Legge un pezzo dalla memoria di libtorrent (thread dello stream)."""
        key = (self._tid(h), piece)
        with self._plock:
            if key in self._pieces:
                return self._pieces.pop(key)
            ev = self._piece_ev.setdefault(key, threading.Event())
        h.read_piece(piece)
        ev.wait(timeout)
        with self._plock:
            self._piece_ev.pop(key, None)
            return self._pieces.pop(key, None)

    def resolve_stream(self, url):
        """Dal link locale di stream → (tid, indice file, percorso finale, nome)."""
        m = re.match(r"^http://127\.0\.0\.1:\d+/([0-9a-f]+)/(\d+)/", url)
        it = self.items.get(m.group(1)) if m else None
        if not it or not it["h"].has_metadata():
            return None
        idx = int(m.group(2))
        fs = it["h"].torrent_file().files()
        path = os.path.join(it["h"].status().save_path, fs.file_path(idx))
        return m.group(1), idx, path, Path(fs.file_path(idx)).name

    def is_complete(self, tid, idx):
        it = self.items.get(tid)
        if not it:
            return True   # torrent rimosso: il file su disco è quello che resta
        try:
            return it["h"].file_progress()[idx] >= it["h"].torrent_file().files().file_size(idx)
        except Exception:
            return False

    def _handle_alerts(self):
        saved = 0
        if not self.ses:
            return 0
        for a in self.ses.pop_alerts():
            if isinstance(a, lt.read_piece_alert):
                key = (str(a.handle.info_hashes().get_best()), a.piece)
                with self._plock:
                    if key in self._piece_ev:
                        self._pieces[key] = bytes(a.buffer)
                        self._piece_ev[key].set()
                continue
            if isinstance(a, lt.save_resume_data_alert):
                try:
                    tid = str(a.handle.info_hashes().get_best())
                    (TDIR / f"{tid}.resume").write_bytes(lt.write_resume_data_buf(a.params))
                except Exception:
                    pass
                saved += 1
            elif isinstance(a, lt.save_resume_data_failed_alert):
                saved += 1
            elif isinstance(a, lt.metadata_received_alert):
                try:
                    tid = str(a.handle.info_hashes().get_best())
                    if tid in self.items:
                        a.handle.save_resume_data(lt.save_resume_flags_t.save_info_dict)
                        self._check_fake(tid)
                        if self.items[tid].get("instant"):
                            self._instant_select(tid)
                        elif self.items[tid].get("need_select"):
                            self.metadata.emit(tid)
                except Exception:
                    pass
            elif isinstance(a, lt.file_error_alert):
                self.error.emit("Errore file torrent", a.message())
        return saved

    def _tick(self):
        ts = settings.data["torrent"]
        for tid, it in list(self.items.items()):
            h = it["h"]
            if not h.is_valid():
                continue
            s = h.status()
            if s.has_incoming:
                self.incoming = True
            paused = bool(s.flags & lt.torrent_flags.paused)
            st = s.state
            if not s.has_metadata:
                status = "metadata"
            elif paused:
                status = "complete" if s.is_finished else ("error" if s.errc.value() else "paused")
            elif st in (lt.torrent_status.checking_files, lt.torrent_status.checking_resume_data):
                status = "checking"
            elif s.total_wanted == 0:
                status = "choose"           # metadati arrivati ma nessun file scelto: niente da scaricare
            elif s.is_finished:
                status = "seeding"
            else:
                status = "active"
            if s.errc.value():
                status = "error"
            if status == "choose" and tid not in self._asked:
                # recupero automatico (anche per i torrent rimasti così da una sessione precedente)
                self._asked.add(tid)
                if it.get("instant"):
                    self._instant_select(tid)
                elif it.get("need_select") or not it.get("selected"):
                    it["need_select"] = True
                    self.metadata.emit(tid)
            it.update(name=s.name or it.get("name") or "Recupero metadati…", total=s.total_wanted,
                      done=s.total_wanted_done, progress=(s.total_wanted_done / s.total_wanted) if s.total_wanted else 0,
                      speed=s.download_payload_rate, up=s.upload_payload_rate, peers=s.num_peers,
                      seeds=s.num_seeds, status=status, error=s.errc.message() if s.errc.value() else "",
                      eta=((s.total_wanted - s.total_wanted_done) / s.download_payload_rate)
                      if s.download_payload_rate else None,
                      ratio=(s.all_time_upload / s.total_wanted) if s.total_wanted else 0,
                      path=os.path.join(s.save_path, s.name) if s.name else s.save_path,
                      streamable=(s.has_metadata and not it.get("need_select") and self.best_video(tid) is not None)
                      or status == "choose")
            if s.has_metadata and s.is_finished and not it.get("done_notified") and not it.get("need_select") \
                    and s.total_wanted > 0:
                it["done_notified"] = True
                it["finished_at"] = time.time()
                self._meta_save(tid)
                h.save_resume_data(lt.save_resume_flags_t.save_info_dict)
                self.finished.emit(tid)
            # regole di seeding
            if status == "seeding" and not it.get("manual_resume"):
                mode = ts["seed_mode"]
                stop = mode == "off" or \
                    (mode == "ratio" and it["ratio"] >= float(ts["seed_ratio"])) or \
                    (mode == "time" and time.time() - it.get("finished_at", time.time()) >= int(ts["seed_minutes"]) * 60)
                if stop:
                    self.pause(tid)
        if time.time() - self._last_save > 60:
            self._last_save = time.time()
            self.save_all()

    def reannounce_all(self) -> int:
        """Chiede subito nuovi peer a tracker e DHT per tutti i torrent attivi (pulsante Aggiorna)."""
        n = 0
        for it in list(self.items.values()):
            h = it.get("h")
            if not h or it.get("status") in ("paused", "seeding", "complete"):
                continue
            try:
                if it.get("status") == "error":
                    h.clear_error()
                    h.resume()
                h.force_reannounce(0, -1)
                h.force_dht_announce()
                n += 1
            except Exception:
                pass
        return n

    def stats(self):
        act = [i for i in self.items.values() if i.get("status") in ("active", "metadata")]
        return len(act), sum(i.get("speed", 0) for i in act)

    def shutdown(self):
        if self.ses:
            self.timer.stop()
            self.pump.stop()
            for tid in self.items:
                self._meta_save(tid)
            self.save_all(wait=True)


# ------------------------------------------------------------------ dialoghi
class FileSelectDialog(QDialog):
    def __init__(self, parent, ti, save_path):
        super().__init__(parent)
        self.setWindowTitle("Scegli i file")
        self.resize(720, 520)
        self.ti = ti
        self.save_path = save_path
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(label(ti.name(), "sectionTitle", wrap=True))
        self.info = label("", "muted")
        v.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Dimensione"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.files = files_of(ti)
        from .safety import fake_verdict
        why = fake_verdict([(p, s) for _, p, s in self.files])
        if why:
            warn = label("⚠  Attenzione, probabile torrent falso: " + why, wrap=True)
            warn.setStyleSheet(f"background:rgba(255,80,80,0.14);color:{theme.danger};border-radius:10px;"
                               "padding:10px 12px;font-weight:600;")
            v.insertWidget(max(0, v.count() - 1), warn)
        for i, p, s in self.files:
            item = QTreeWidgetItem([p, human_size(s)])
            item.setData(0, Qt.UserRole, i)
            item.setCheckState(0, Qt.Checked)
            ext = Path(p).suffix.lower()
            item.setIcon(0, icons.icon("film" if ext in VIDEO_EXT else "music" if ext in AUDIO_EXT else "file",
                                       theme.text2, 16))
            self.tree.addTopLevelItem(item)
        self.tree.itemChanged.connect(self._update)
        v.addWidget(self.tree, 1)
        q = QHBoxLayout()
        q.addWidget(button("Tutti", "chip", None, lambda: self._set(lambda p: True)))
        q.addWidget(button("Solo video", "chip", None, lambda: self._set(lambda p: Path(p).suffix.lower() in VIDEO_EXT)))
        q.addWidget(button("Nessuno", "chip", None, lambda: self._set(lambda p: False)))
        q.addStretch()
        v.addLayout(q)
        r = QHBoxLayout()
        self.seq = Toggle(settings.get("torrent", "sequential"))
        r.addWidget(self.seq)
        r.addWidget(label("Download sequenziale (guarda mentre scarica)"))
        r.addStretch()
        v.addLayout(r)
        d = QHBoxLayout()
        self.dir_l = label(save_path, "faint")
        d.addWidget(label("Destinazione:", "muted"))
        d.addWidget(self.dir_l, 1)
        d.addWidget(button("Cambia…", None, "folder", self._dir))
        v.addLayout(d)
        b = QHBoxLayout()
        b.addStretch()
        b.addWidget(button("Annulla", None, None, self.reject))
        self.ok = button("Avvia download", "primary", "download", self.accept)
        b.addWidget(self.ok)
        v.addLayout(b)
        self._update()

    def _set(self, pred):
        self.tree.blockSignals(True)
        for k in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(k)
            it.setCheckState(0, Qt.Checked if pred(it.text(0)) else Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update()

    def _update(self, *_):
        tot, n = 0, 0
        for k in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(k)
            if it.checkState(0) == Qt.Checked:
                n += 1
                tot += self.files[k][2]
        self.info.setText(f"{n} file selezionati · {human_size(tot)}")
        if hasattr(self, "ok"):
            self.ok.setEnabled(n > 0)

    def _dir(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella di destinazione", self.save_path)
        if d:
            self.save_path = d
            self.dir_l.setText(d)

    def result_data(self):
        n = self.ti.files().num_files()
        prios = [0] * n
        for k in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(k)
            if it.checkState(0) == Qt.Checked:
                prios[it.data(0, Qt.UserRole)] = 4
        return prios, self.seq.isChecked(), self.save_path


class DebridCard(Card):
    """Risultato Real-Debrid: avanzamento sul cloud e link diretti pronti."""

    def __init__(self, page, title):
        super().__init__()
        self.page = page
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 12, 14)
        top = QHBoxLayout()
        ic = label("")
        ic.setPixmap(icons.pixmap("cloud", theme.info, 22))
        top.addWidget(ic)
        self.title = label(title, "sectionTitle")
        top.addWidget(self.title, 1)
        self.pill = Pill("Real-Debrid", theme.info)
        top.addWidget(self.pill)
        x = IconButton("x", "Chiudi", 30, 14)
        x.clicked.connect(self.deleteLater)
        top.addWidget(x)
        self.v.addLayout(top)
        self.bar = AnimatedProgress(height=5)
        self.bar.set_indeterminate(True)
        self.v.addWidget(self.bar)
        self.status = label("Invio a Real-Debrid…", "faint")
        self.v.addWidget(self.status)

    def progress(self, text, frac):
        self.status.setText(text)
        if frac is not None:
            self.bar.set_indeterminate(False)
            self.bar.set_value(frac, theme.info)

    def links(self, files):
        self.bar.set_value(1.0, theme.success)
        self.pill.set("Pronto", theme.success)
        self.status.setText(f"{len(files)} link diretti pronti")
        for f in files:
            r = QHBoxLayout()
            nm = label(f"{f['filename']}  ·  {human_size(f.get('filesize'))}")
            r.addWidget(nm, 1)
            if Path(f["filename"]).suffix.lower() in VIDEO_EXT | AUDIO_EXT:
                r.addWidget(button("Riproduci", "primary", "play", lambda _=False, u=f["download"]: self.page.play.emit(u)))
            r.addWidget(button("Scarica", None, "download",
                               lambda _=False, u=f["download"]: self.page.download_direct.emit(u)))
            r.addWidget(IconButton("clipboard", "Copia link", 34, 16, ))
            r.itemAt(r.count() - 1).widget().clicked.connect(
                lambda _=False, u=f["download"]: QApplication.clipboard().setText(u))
            self.v.addLayout(r)

    def fail(self, msg):
        self.bar.set_value(1.0, theme.danger)
        self.bar.set_indeterminate(False)
        self.pill.set("Errore", theme.danger)
        self.status.setText(msg)


class InstantCard(Card):
    """⚡ Link istantaneo da torrent: segue i passaggi e, appena c'è abbastanza buffer, parte da solo."""

    def __init__(self, page: "TorrentPage", tid: str, autoplay=True):
        super().__init__()
        self.page, self.mgr, self.tid = page, page.mgr, tid
        self.autoplay = autoplay
        self.t0 = time.time()
        self.ready = False
        self.setStyleSheet(f"#card{{background:{theme.surface};border:1px solid {theme.accent};border-radius:14px;}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 12, 14)
        v.setSpacing(8)
        top = QHBoxLayout()
        ic = label("")
        ic.setPixmap(icons.pixmap("speed", theme.accent, 22))
        top.addWidget(ic)
        self.title = label("Link istantaneo", "sectionTitle")
        top.addWidget(self.title, 1)
        self.pill = Pill("Avvio…", theme.accent)
        top.addWidget(self.pill)
        x = IconButton("x", "Chiudi (il download continua)", 30, 14)
        x.clicked.connect(self._close)
        top.addWidget(x)
        v.addLayout(top)
        self.bar = AnimatedProgress(height=5)
        self.bar.set_indeterminate(True)
        v.addWidget(self.bar)
        self.status = label("Cerco i peer…", "faint")
        v.addWidget(self.status)
        lr = QHBoxLayout()
        self.link = QLineEdit()
        self.link.setReadOnly(True)
        self.link.setPlaceholderText("Il link diretto comparirà qui")
        lr.addWidget(self.link, 1)
        self.b_copy = button("Copia link", None, "clipboard",
                             lambda: (QApplication.clipboard().setText(self.link.text()),
                                      self.page.toast.emit("Link copiato", "Funziona in NOVA, VLC o nel browser "
                                                           "finché NOVA è aperto.", "ok")))
        self.b_play = button("Guarda ora", "primary", "play", self._play)
        lr.addWidget(self.b_copy)
        lr.addWidget(self.b_play)
        v.addLayout(lr)
        self.b_copy.setEnabled(False)
        self.b_play.setEnabled(False)
        self.timer = QTimer(self, interval=300)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _close(self):
        self.timer.stop()
        self.deleteLater()

    def _play(self):
        u = self.mgr.stream_url(self.tid)
        if u:
            self.page.play.emit(u)

    def _buffer_frac(self, it):
        """Quota dei pezzi iniziali (≈ i primi secondi di video) già scaricati."""
        h = it["h"]
        idx = it.get("stream_idx")
        if idx is None:
            return 1.0 if h.status().progress > 0.02 else h.status().progress / 0.02
        ti = h.torrent_file()
        fs, plen = ti.files(), ti.piece_length()
        first = fs.file_offset(idx) // plen
        last = (fs.file_offset(idx) + fs.file_size(idx) - 1) // plen
        need_bytes = max(8 * 1024 * 1024, int(fs.file_size(idx) * 0.0025))
        n = max(4, min(last - first + 1, need_bytes // plen + 1))
        want = sorted(set(list(range(first, min(first + n, last + 1))) + [last - 1, last]) - {first - 1})
        missing = [p for p in want if not h.have_piece(p)]
        # ribadisce le scadenze a ogni giro: inizio del file in ordine, coda (indice MKV/MP4) subito
        for k, p in enumerate(sorted(missing, key=lambda p: (p < last - 1, p))[:64]):
            h.set_piece_deadline(p, 200 + k * 60)
        return 1 - len(missing) / len(want)

    def _tick(self):
        it = self.mgr.items.get(self.tid)
        if not it:
            self._close()
            return
        h = it["h"]
        if not h.is_valid():
            return
        s = h.status()
        el = time.time() - self.t0
        if s.name:
            self.title.setText(s.name[:90])
        if not s.has_metadata:
            self.status.setText(f"Collegamento ai peer e lettura metadati… {el:.0f}s · {s.num_peers} peer")
            if el > 60 and s.num_peers == 0:
                self.pill.set("Nessun peer", theme.danger)
                self.status.setText("Nessun peer dopo 60 s: torrent senza seeder o connessione bloccata dal firewall.")
            return
        if it.get("stream_idx") is None and not it.get("selected"):
            return
        frac = self._buffer_frac(it)
        u = self.mgr.stream_url(self.tid)
        if u and self.link.text() != u:
            self.link.setText(u)
            self.b_copy.setEnabled(True)
        if not self.ready:
            self.bar.set_indeterminate(False)
            self.bar.set_value(frac)
            self.pill.set(f"Buffer {frac * 100:.0f}%", theme.accent)
            self.status.setText(f"Preparo l'inizio del video… {human_speed(s.download_payload_rate)} · "
                                f"{s.num_peers} peer · {el:.0f}s")
            if frac >= 1.0:
                self.ready = True
                self.b_play.setEnabled(True)
                self.pill.set("Pronto", theme.success)
                if self.autoplay:
                    self._play()
        else:
            tot = s.total_wanted or 1
            self.bar.set_value(s.total_wanted_done / tot, theme.success)
            self.status.setText(f"Pronto in {self.ready_time:.0f}s · scaricato {s.total_wanted_done / tot * 100:.0f}% · "
                                f"↓ {human_speed(s.download_payload_rate)} · {s.num_peers} peer"
                                if hasattr(self, "ready_time") else "")
        if self.ready and not hasattr(self, "ready_time"):
            self.ready_time = el


# ------------------------------------------------------------------ pagina
class TorrentPage(QWidget):
    open_firewall = Signal()
    play = Signal(str)
    download_direct = Signal(str)
    toast = Signal(str, str, str)

    def __init__(self, mgr: TorrentManager, parent=None):
        super().__init__(parent)
        self.mgr = mgr
        self.cards: dict[str, DownloadCard] = {}
        root = QVBoxLayout(self)
        m = theme.s(28)
        root.setContentsMargins(m, m - 4, m, m)
        root.setSpacing(theme.s(16))
        root.addWidget(PageHeader("Torrent", "Da .torrent o magnet a un normale file MKV/MP4. Guarda mentre scarica."))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.input = QLineEdit()
        self.input.setObjectName("bigInput")
        self.input.setPlaceholderText("Incolla un link magnet:?xt=…  oppure trascina un file .torrent")
        self.input.returnPressed.connect(self._add)
        row.addWidget(self.input, 1)
        row.addWidget(button("Apri .torrent", None, "folder", self._open))
        self.b_rd = button("Real-Debrid", None, "cloud", self._debrid)
        self.b_rd.setToolTip("Scarica sul cloud Real-Debrid e ottieni un link diretto HTTP")
        self.b_rd.hide()          # versione pubblica: niente servizi a pagamento di terzi
        row.addWidget(button("Aggiungi", None, "plus", self._add))
        b_inst = button("Link istantaneo", "primary", "speed", self._instant)
        b_inst.setToolTip("Un clic: trasforma il torrent in un link diretto e lo fa partire nel player")
        row.addWidget(b_inst)
        root.addLayout(row)
        self.summary = label("", "muted")
        self.hero = SpeedHero()
        root.addWidget(self.hero)
        pr = QHBoxLayout()
        self.port_pill = Pill("Porta: verifica in corso…", theme.text2)
        pr.addWidget(self.port_pill)
        self.port_hint = label("", "faint")
        pr.addWidget(self.port_hint)
        pr.addStretch()
        self.b_port = button("Apri porta nel firewall", None, "check", self.open_firewall.emit)
        self.b_port.hide()
        pr.addWidget(self.b_port)
        root.addLayout(pr)
        self._active_since = None

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(theme.s(10))
        msg = ("Incolla un magnet e premi ⚡ Link istantaneo: NOVA lo trasforma in un link diretto e lo fa partire "
               "nel player appena c'è abbastanza buffer. Con Aggiungi invece lo scarichi alla massima velocità.")
        if LT_ERROR:
            msg = f"libtorrent non disponibile: {LT_ERROR}. Esegui di nuovo setup.bat."
        self.empty = EmptyState("magnet", "Nessun torrent", msg)
        self.list.addWidget(self.empty)
        self.list.addStretch()
        self.scroll.setWidget(host)
        root.addWidget(self.scroll, 1)
        self.update_debrid_button()
        mgr.added.connect(self._added)
        mgr.removed.connect(self._removed)
        mgr.metadata.connect(self._choose_files)
        mgr.finished.connect(self._finished)
        mgr.error.connect(self._mgr_error)
        for tid in list(mgr.order):
            self._added(tid, anim=False)
        self.timer = QTimer(self, interval=500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self._rd_threads = []

    def _mgr_error(self, t, m):
        self.toast.emit(t, m, "err")

    def _update_port(self, active):
        if self.mgr.incoming:
            self.port_pill.set("Porta aperta ✓", theme.success)
            self.port_hint.setText("I peer riescono a collegarsi a te: velocità piena.")
            self.b_port.hide()
            return
        if active:
            self._active_since = self._active_since or time.time()
        if self._active_since and time.time() - self._active_since > 90:
            self.port_pill.set("Porta chiusa", theme.warning)
            self.port_hint.setText("Ti colleghi solo tu agli altri: la velocità può essere molto più bassa.")
            self.b_port.show()
        else:
            self.port_pill.set("Porta: verifica durante il download", theme.text2)
            self.port_hint.setText("")

    def showEvent(self, e):
        self.timer.start()
        self.refresh()

    def hideEvent(self, e):
        self.timer.stop()

    def update_debrid_button(self):
        self.b_rd.setVisible(False)

    def get(self, tid):
        return self.mgr.items.get(tid)

    def _save_dir(self):
        d = settings.get("torrent", "dir")
        Path(d).mkdir(parents=True, exist_ok=True)
        return d

    def _add(self):
        t = self.input.text().strip()
        if not t:
            return
        if t.startswith("magnet:"):
            self.input.clear()
            self.mgr.add_magnet(t, self._save_dir())
        elif t.lower().endswith(".torrent") and os.path.isfile(t):
            self.input.clear()
            self.add_torrent_file(t)
        else:
            self.toast.emit("Link non valido", "Serve un link magnet o un file .torrent.", "warn")

    def _open(self):
        f, _ = QFileDialog.getOpenFileName(self, "Apri file torrent", "", "Torrent (*.torrent)")
        if f:
            self.add_torrent_file(f)

    def add_input(self, text):
        if text.startswith("magnet:"):
            self.mgr.add_magnet(text, self._save_dir())
        elif os.path.isfile(text):
            self.add_torrent_file(text)

    def add_torrent_file(self, path):
        if lt is None:
            self.toast.emit("Torrent non disponibile", LT_ERROR or "", "err")
            return
        ti = self._load_torrent(path)
        if ti is None:
            return
        d = FileSelectDialog(self.window(), ti, self._save_dir())
        if d.exec():
            prios, seq, sp = d.result_data()
            self.mgr.add_file(ti, sp, prios, seq)

    def _load_torrent(self, path):
        """Legge il .torrent in Python (percorsi con accenti/OneDrive ok) e spiega gli errori comuni."""
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            self.toast.emit("Impossibile leggere il file", str(e), "err")
            return None
        head = data[:4096].lstrip()
        text = head.decode("utf-8", "ignore")
        if "magnet:?" in text:
            self.mgr.add_magnet(text[text.index("magnet:?"):].split()[0], self._save_dir())
            return None
        if not data.strip():
            msg = ("Il file è vuoto (0 byte). Se è su OneDrive, aprilo una volta o scegli "
                   "'Mantieni sempre su questo dispositivo', poi riprova.")
        elif head[:1] == b"<" or "<html" in text.lower():
            msg = "Questo file è una pagina web, non un torrent. Riscaricalo dal sito oppure usa il link magnet."
        elif head[:1] != b"d":
            msg = "Il contenuto non è un file .torrent (formato bencode). Riscaricalo oppure usa il link magnet."
        else:
            try:
                return lt.torrent_info(data)
            except Exception as e:
                msg = f"Il file .torrent è incompleto o danneggiato ({e}). Riscaricalo oppure usa il link magnet."
        self.toast.emit("File torrent non valido", msg, "err")
        return None

    def _choose_files(self, tid):
        it = self.mgr.items.get(tid)
        if not it or it.get("_dialog") or not it["h"].has_metadata():
            return
        it["_dialog"] = True
        try:
            ti = it["h"].torrent_file()
            d = FileSelectDialog(self.window(), ti, it["h"].status().save_path)
            if d.exec():
                prios, seq, sp = d.result_data()
                if sp != it["h"].status().save_path:
                    it["h"].move_storage(sp)
                self.mgr.apply_selection(tid, prios, seq)
                self.mgr.resume(tid)
            else:
                self.toast.emit("Nessun file scelto", "Il torrent resta in elenco: premi ▶ o il menu (tasto destro) "
                                "› Scegli file quando vuoi.", "info")
        finally:
            it["_dialog"] = False

    def _added(self, tid, anim=True):
        if tid in self.cards:
            return
        c = DownloadCard(tid, self, torrent=True)
        self.cards[tid] = c
        self.list.insertWidget(0, c)
        self.empty.hide()
        if anim:
            animate_in(c)

    def _removed(self, tid):
        c = self.cards.pop(tid, None)
        if c:
            c.deleteLater()
        self.empty.setVisible(not self.cards)

    def _finished(self, tid):
        it = self.mgr.items.get(tid, {})
        acts = []
        bv = self.mgr.best_video(tid)
        if bv:
            acts.append(("Riproduci", lambda: self.play_item(tid)))
        acts.append(("Apri cartella", lambda: self.open_folder(tid)))
        self.window().notify("Torrent completato", it.get("name", ""), acts)

    def refresh(self):
        for tid, c in list(self.cards.items()):
            it = self.mgr.items.get(tid)
            if it and c.isVisible():
                c.refresh(it)
        n, spd = self.mgr.stats()
        peers = sum(i.get("peers", 0) for i in list(self.mgr.items.values()) if i.get("status") == "active")
        self._update_port(n)
        up = sum(i.get("up", 0) for i in list(self.mgr.items.values()))
        self.hero.update_speed(spd, f"{n} torrent attivi · {peers} peer · ↑ {human_speed(up)}" if n
                               else "Nessun torrent attivo")

    # azioni card
    def pause_item(self, tid):
        self.mgr.pause(tid)

    def resume_item(self, tid):
        it = self.mgr.items.get(tid)
        if it and (it.get("need_select") or it.get("status") == "choose") and it["h"].has_metadata():
            self._choose_files(tid)
            return
        self.mgr.resume(tid)

    def remove_item(self, tid):
        m = QMenu(self)
        m.addAction("Rimuovi (mantieni i file)", lambda: self.mgr.remove(tid, False))
        m.addAction("Rimuovi ed elimina i file", lambda: self.mgr.remove(tid, True))
        from PySide6.QtGui import QCursor
        m.exec(QCursor.pos())

    def play_item(self, tid):
        it = self.mgr.items.get(tid)
        if it and it.get("status") == "choose":
            self._choose_files(tid)
            return
        if it and it["h"].is_valid() and not it["h"].status().is_finished:
            it["h"].set_flags(lt.torrent_flags.sequential_download)  # serve solo mentre guardi
        u = self.mgr.stream_url(tid)
        if u:
            self.play.emit(u)
        else:
            self.toast.emit("Niente da riprodurre", "Nessun file video selezionato in questo torrent.", "warn")

    def open_folder(self, tid):
        it = self.mgr.items.get(tid)
        if it:
            bv = self.mgr.best_video(tid)
            p = os.path.join(it["h"].status().save_path, bv[1]) if bv else it.get("path")
            reveal(p if p and os.path.exists(p) else it["h"].status().save_path)

    def convert_menu(self, tid, anchor):
        bv = self.mgr.best_video(tid)
        it = self.mgr.items.get(tid)
        if bv and it:
            convert_menu(self, os.path.join(it["h"].status().save_path, bv[1]), anchor)

    def context_menu(self, tid, gpos):
        it = self.mgr.items.get(tid)
        if not it:
            return
        h = it["h"]
        m = QMenu(self)
        if h.has_metadata():
            m.addAction("Scegli file…", lambda: self._choose_files(tid))
            seq = bool(h.flags() & lt.torrent_flags.sequential_download)
            a = m.addAction("Download sequenziale")
            a.setCheckable(True)
            a.setChecked(seq)
            a.toggled.connect(lambda on: h.set_flags(lt.torrent_flags.sequential_download) if on
                              else h.unset_flags(lt.torrent_flags.sequential_download))
            try:
                mag = lt.make_magnet_uri(h)
                m.addAction("Copia link magnet", lambda: QApplication.clipboard().setText(mag))
            except Exception:
                pass
        m.addAction("Verifica file", h.force_recheck)
        m.addSeparator()
        m.addAction("Rimuovi (mantieni i file)", lambda: self.mgr.remove(tid, False))
        m.addAction("Rimuovi ed elimina i file", lambda: self.mgr.remove(tid, True))
        m.exec(gpos)

    # ⚡ Link istantaneo
    def _instant(self):
        t = self.input.text().strip()
        if not t.startswith("magnet:") and not (t.lower().endswith(".torrent") and os.path.isfile(t)):
            f, _ = QFileDialog.getOpenFileName(self, "Scegli un .torrent (oppure incolla un magnet)", "",
                                               "Torrent (*.torrent)")
            if not f:
                return
            if self._load_torrent(f) is None:
                return
            t = f
        self.input.clear()
        self.instant(t)

    def instant(self, src):
        if False:
            # 1) Real-Debrid: se è in cache il link HTTP arriva in pochi secondi
            card = self._debrid_card(src, instant=True)
            card.rd.not_cached.connect(lambda: (card.progress("Non in cache su Real-Debrid: lo scarica il cloud. "
                                                              "Intanto parte lo stream via torrent ↓", None),
                                                self._instant_local(src)))
        else:
            self._instant_local(src)

    def _instant_local(self, src):
        tid = self.mgr.add_instant(src, self._save_dir())
        if not tid:
            return
        card = InstantCard(self, tid)
        self.list.insertWidget(0, card)
        self.empty.hide()
        animate_in(card)

    # Real-Debrid
    def _debrid(self):
        t = self.input.text().strip()
        if not t.startswith("magnet:") and not (t.lower().endswith(".torrent") and os.path.isfile(t)):
            f, _ = QFileDialog.getOpenFileName(self, "Torrent da inviare a Real-Debrid", "", "Torrent (*.torrent)")
            if not f:
                self.toast.emit("Real-Debrid", "Incolla un magnet nel campo o scegli un file .torrent.", "info")
                return
            t = f
        self.input.clear()
        self.debrid_send(t)

    def debrid_send(self, src):
        self._debrid_card(src)

    def _debrid_card(self, src, instant=False):
        name = "Magnet" if src.startswith("magnet:") else Path(src).name
        m = re.search(r"dn=([^&]+)", src)
        if m:
            name = urllib.parse.unquote_plus(m.group(1))
        card = DebridCard(self, name)
        self.list.insertWidget(0, card)
        self.empty.hide()
        animate_in(card)
        rd = RealDebrid(settings.get("torrent", "rd_token"), instant_timeout=60 if instant else None)
        card.rd = rd
        rd.progress.connect(card.progress)
        rd.ready.connect(card.links)
        if instant:
            rd.ready.connect(lambda files: files and Path(files[0]["filename"] or "").suffix.lower() in VIDEO_EXT
                             and self.play.emit(files[0]["download"]))
        rd.failed.connect(card.fail)
        self._rd_threads.append(rd)
        rd.run(src)
        return card
