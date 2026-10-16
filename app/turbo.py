"""Stream Turbo: proxy locale che scarica un link con più connessioni persistenti e lo serve al player.

Perché: un solo collegamento HTTP spesso è limitato dal server (2-5 MB/s) e ogni salto ne apre uno nuovo.
Qui N connessioni keep-alive scaricano a blocchi la zona davanti alla posizione di lettura, quindi:
- velocità piena anche se il server limita la singola connessione;
- dopo un salto i primi byte arrivano subito (nessun nuovo handshake TLS, più blocchi in parallelo);
- se il link scade, la riproduzione si ferma sul punto esatto e riparte incollando un link nuovo.
"""
from __future__ import annotations

import http.client
import re
import secrets
import select
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

CHUNK = 512 * 1024              # dimensione di un blocco (piccolo = salti più rapidi)
AHEAD = 192                     # blocchi da tenere pronti davanti a chi legge (~96 MB)
URGENT = 4                      # vicino al punto di lettura: richieste da 1 blocco (salti rapidi)
RUN_MAX = 4                     # più avanti: una richiesta copre fino a 4 blocchi (2 MB), meno attese tra blocchi
MAX_CACHED = 768                # blocchi in memoria (~384 MB); mpv ha già la sua cache
READ_STEP = 64 * 1024
STALL = 2.0                     # secondi senza dati su un blocco atteso = connessione piantata
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
EXPIRED_CODES = {401, 403, 404, 410}
SSL_CTX = ssl.create_default_context()


class Expired(Exception):
    pass


class Chunk:
    __slots__ = ("idx", "data", "filled", "size", "done", "busy", "last", "conn")

    def __init__(self, idx, size):
        self.idx = idx
        self.size = size
        self.data = bytearray()
        self.filled = 0
        self.done = False
        self.busy = False
        self.last = time.time()
        self.conn = None


def filename_from(url, headers) -> str:
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    if m:
        return urllib.parse.unquote(m.group(1)).strip()
    return urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name) or "video"


def probe(url: str, ua: str = UA, timeout=15) -> dict:
    """Segue i redirect e legge dimensione, supporto ai salti (Range) e nome del file."""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Range": "bytes=0-0", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
            cr = r.headers.get("Content-Range") or ""
            m = re.search(r"/(\d+)", cr)
            size = int(m.group(1)) if m else int(r.headers.get("Content-Length") or 0)
            return {"ok": True, "final": r.geturl(), "size": size, "ranges": r.status == 206 and bool(m),
                    "ctype": (r.headers.get("Content-Type") or "").lower(), "name": filename_from(r.geturl(), r.headers)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "code": e.code, "expired": e.code in EXPIRED_CODES}
    except Exception as e:
        return {"ok": False, "code": 0, "error": str(e)}


class Source:
    """Un file remoto servito in streaming a blocchi."""

    def __init__(self, sid, url, info, ua, connections, on_state):
        self.id = sid
        self.url = url
        self.final = info["final"]
        self.size = info["size"]
        self.name = info["name"]
        self.offset = int(info.get("offset") or 0)          # episodio dentro uno ZIP: dove inizia
        self.total = int(info.get("total") or self.size)     # dimensione del file remoto intero
        self.ctype = info["ctype"] or "application/octet-stream"
        self.ua = ua
        self.n = self.n_max = max(1, connections)
        self.cond = threading.Condition()
        self.chunks: dict[int, Chunk] = {}
        self.readers: dict[int, int] = {}       # lettore -> posizione corrente
        self.state = "ok"                        # ok | expired | closed
        self.on_state = on_state
        self.samples = deque(maxlen=40)          # (t, byte) per la velocità
        self.got = 0
        self.nchunks = (self.size + CHUNK - 1) // CHUNK
        self.backoff_until = 0.0
        self.stalls = 0
        self.workers = [threading.Thread(target=self._worker, args=(i,), daemon=True) for i in range(self.n)]
        for w in self.workers:
            w.start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        """Ogni mezzo secondo: le connessioni ferme da più di 3 s vengono chiuse e il blocco riparte da un'altra."""
        while self.state != "closed":
            time.sleep(0.5)
            now = time.time()
            with self.cond:
                stuck = {id(c.conn): c for c in self.chunks.values()
                         if c.busy and not c.done and c.conn is not None and now - c.last > STALL * 1.5}
            for c in stuck.values():
                c.last = now
                self.stalls += 1
                try:
                    if c.conn.sock is not None:
                        c.conn.sock.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass

    # ---------- pianificazione ----------
    def _wanted(self):
        """Blocchi da scaricare, in ordine di urgenza (prima il lettore con meno dati pronti)."""
        order = []
        seen = set()
        readers = sorted(self.readers.values(), key=self._ready_ahead)
        for pos in readers:
            start = pos // CHUNK
            for i in range(start, min(self.nchunks, start + AHEAD)):
                if i not in seen:
                    seen.add(i)
                    order.append(i)
        return order

    def _ready_ahead(self, pos):
        i = pos // CHUNK
        n = 0
        while n < AHEAD:
            c = self.chunks.get(i + n)
            if not c or not c.done:
                break
            n += 1
        return n

    def _still_wanted(self, idx):
        return any(p // CHUNK <= idx < p // CHUNK + AHEAD for p in self.readers.values())

    def _evict(self):
        if len(self.chunks) <= MAX_CACHED:
            return
        keep = set()
        for p in self.readers.values():
            s = p // CHUNK
            keep.update(range(max(0, s - 8), s + AHEAD))
        victims = sorted((c for i, c in self.chunks.items() if i not in keep and not c.busy), key=lambda c: c.last)
        for c in victims[: len(self.chunks) - MAX_CACHED]:
            self.chunks.pop(c.idx, None)

    # ---------- connessioni ----------
    def _conn(self, u):
        if u.scheme == "https":
            return http.client.HTTPSConnection(u.hostname, u.port or 443, timeout=8, context=SSL_CTX)
        return http.client.HTTPConnection(u.hostname, u.port or 80, timeout=8)

    def _worker(self, wid):
        conn, host = None, None
        while True:
            with self.cond:
                while True:
                    if self.state == "closed":
                        if conn:
                            conn.close()
                        return
                    now = time.time()
                    if self.state == "ok" and now >= self.backoff_until and wid < self.n:
                        pick = next((i for i in self._wanted()
                                     if not (self.chunks.get(i) and (self.chunks[i].done or self.chunks[i].busy))), None)
                        if pick is not None:
                            run = self._run_from(pick)
                            for c in run:
                                c.busy = True
                                c.data = bytearray()
                                c.filled = 0
                                c.last = time.time()
                            self._evict()
                            break
                    self.cond.wait(0.5)
                final = self.final
            u = urllib.parse.urlparse(final)
            try:
                if conn is None or host != (u.scheme, u.hostname, u.port):
                    if conn:
                        conn.close()
                    conn, host = self._conn(u), (u.scheme, u.hostname, u.port)
                self._fetch(conn, u, run)
            except Expired:
                with self.cond:
                    self._release(run)
                    flowing = self.samples and time.time() - self.samples[-1][0] < 4
                    if flowing and self.n > 1:
                        # gli altri collegamenti funzionano: non è scaduto, il sito vuole meno connessioni
                        self.n = max(1, self.n // 2)
                        self.backoff_until = time.time() + 1
                        self.cond.notify_all()
                    elif self.state == "ok":
                        self.state = "expired"
                        self.cond.notify_all()
                        self.on_state(self.id, "expired")
                if conn:
                    conn.close()
                conn = None
            except _Redirect as r:
                with self.cond:
                    self._release(run)
                    self.final = r.location
                    self.cond.notify_all()
                conn.close()
                conn = None
            except _Throttled:
                with self.cond:
                    self._release(run)
                    # il server rifiuta troppe connessioni: ne usiamo meno
                    self.n = max(2, self.n // 2)
                    self.backoff_until = time.time() + 2
                    self.cond.notify_all()
                conn.close()
                conn = None
            except _Abandon:
                with self.cond:
                    self._release(run, drop=True)
                    self.cond.notify_all()
                conn.close()
                conn = None
            except Exception:
                with self.cond:
                    self._release(run)
                    self.cond.notify_all()
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = None
                time.sleep(0.15)

    def _run_from(self, pick):
        """Blocchi consecutivi da chiedere con una sola richiesta (1 vicino al lettore, fino a RUN_MAX più avanti)."""
        dist = min((pick - p // CHUNK for p in self.readers.values() if p // CHUNK <= pick), default=0)
        limit = 1 if dist < URGENT else max(1, min(RUN_MAX, dist // URGENT))   # più lontano = richieste più grandi
        run = []
        i = pick
        while len(run) < limit and i < self.nchunks and self._still_wanted(i):
            c = self.chunks.get(i)
            if c and (c.done or c.busy):
                break
            if not c:
                c = Chunk(i, min(CHUNK, self.size - i * CHUNK))
                self.chunks[i] = c
            run.append(c)
            i += 1
        if not run:   # pick fuori finestra (nessun lettore): almeno quello
            c = self.chunks.get(pick) or Chunk(pick, min(CHUNK, self.size - pick * CHUNK))
            self.chunks[pick] = c
            run.append(c)
        return run

    def _urgent(self, idx):
        return any(p // CHUNK <= idx < p // CHUNK + URGENT for p in self.readers.values())

    def _starving(self):
        """Dopo un salto: un lettore aspetta un blocco che nessuno sta scaricando."""
        for p in self.readers.values():
            c = self.chunks.get(p // CHUNK)
            if not c or not (c.done or c.busy):
                return True
        return False

    def _release(self, run, drop=False):
        for c in run:
            if not c.done:
                c.busy = False
                if drop:
                    self.chunks.pop(c.idx, None)

    def _fetch(self, conn, u, run):
        for c in run:
            c.conn = conn
        start = run[0].idx * CHUNK + self.offset
        end = run[-1].idx * CHUNK + run[-1].size - 1 + self.offset
        path = u.path + ("?" + u.query if u.query else "")
        conn.request("GET", path or "/", headers={"User-Agent": self.ua, "Range": f"bytes={start}-{end}",
                                                  "Accept": "*/*", "Connection": "keep-alive",
                                                  "Accept-Encoding": "identity"})
        r = conn.getresponse()
        if r.status in (301, 302, 303, 307, 308):
            loc = r.getheader("Location")
            r.read()
            raise _Redirect(urllib.parse.urljoin(self.final, loc))
        if r.status in EXPIRED_CODES:
            r.read()
            raise Expired()
        if r.status in (429, 503):
            r.read()
            raise _Throttled()
        if r.status != 206:
            r.read(0)
            raise IOError(f"HTTP {r.status}")
        for c in run:
            while c.filled < c.size:
                with self.cond:
                    # dopo un salto questa zona non serve più (o qualcuno aspetta): libera la connessione
                    if not self._still_wanted(c.idx) or \
                            (len(run) > 1 and not self._urgent(c.idx) and self._starving()):
                        raise _Abandon()
                buf = r.read(min(READ_STEP, c.size - c.filled))
                if not buf:
                    raise IOError("incomplete block")
                with self.cond:
                    c.data += buf
                    c.filled += len(buf)
                    c.last = time.time()
                    self.got += len(buf)
                    self.samples.append((time.time(), self.got))
                    self.cond.notify_all()
            with self.cond:
                c.done = True
                c.busy = False
                self.cond.notify_all()
        r.read()   # svuota per riusare la connessione

    # ---------- lettura (thread del server HTTP) ----------
    def read(self, rid, pos, maxlen, alive=None):
        """Restituisce i byte disponibili da pos (attende quelli mancanti). b'' = chiuso."""
        idx = pos // CHUNK
        off = pos - idx * CHUNK
        with self.cond:
            self.readers[rid] = pos
            self.cond.notify_all()
            deadline = time.time() + 1800
            while True:
                if self.state == "closed":
                    return b""
                c = self.chunks.get(idx)
                if c and c.filled > off:
                    c.last = time.time()
                    return bytes(c.data[off: min(c.filled, off + maxlen)])
                if time.time() > deadline:
                    return b""
                if c and c.busy and c.filled <= off and time.time() - c.last > STALL:
                    # la connessione che porta questo blocco si è piantata: chiudila, un'altra lo riprende subito
                    c.last = time.time()
                    self.stalls += 1
                    try:
                        if c.conn is not None and c.conn.sock is not None:
                            c.conn.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                if alive and not alive():
                    # il player ha chiuso questa lettura (salto): smetti subito di chiedere questa zona
                    self.readers.pop(rid, None)
                    self.cond.notify_all()
                    return b""
                self.cond.wait(0.15)

    def drop_reader(self, rid):
        with self.cond:
            self.readers.pop(rid, None)
            self.cond.notify_all()

    def speed(self) -> float:
        with self.cond:
            if len(self.samples) < 2:
                return 0.0
            (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
            if time.time() - t1 > 2:
                return 0.0
            return (b1 - b0) / max(0.2, t1 - t0)

    def renew(self, url, info):
        with self.cond:
            self.url = url
            self.final = info["final"]
            for c in list(self.chunks.values()):
                if not c.done:
                    self.chunks.pop(c.idx, None)
            self.state = "ok"
            self.n = self.n_max
            self.cond.notify_all()

    def close(self):
        with self.cond:
            self.state = "closed"
            self.chunks.clear()
            self.cond.notify_all()


class _Redirect(Exception):
    def __init__(self, location):
        self.location = location


class _Throttled(Exception):
    pass


class _Abandon(Exception):
    pass


class TurboServer(QObject):
    """Server locale (solo 127.0.0.1) che espone le sorgenti a mpv con supporto ai salti."""
    state = Signal(str, str)      # id, "expired"
    ready = Signal(str, dict)     # token richiesta, info (url locale o errore)
    renewed = Signal(str, bool, str)

    def __init__(self):
        super().__init__()
        self.sources: dict[str, Source] = {}
        self._rid = 0
        mgr = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_HEAD(self):
                self._serve(True)

            def do_GET(self):
                self._serve(False)

            def _serve(self, head):
                m = re.match(r"^/s/([0-9a-f]+)/", self.path)
                src = mgr.sources.get(m.group(1)) if m else None
                if not src:
                    self.send_error(404)
                    return
                size = src.size
                start, end = 0, size - 1
                rng = self.headers.get("Range")
                mm = re.match(r"bytes=(\d*)-(\d*)", rng or "")
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
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(206 if rng else 200)
                self.send_header("Content-Type", src.ctype)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if rng:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.end_headers()
                if head:
                    return
                mgr._rid += 1
                rid = mgr._rid
                sock = self.connection

                def alive():
                    try:
                        r, _, _ = select.select([sock], [], [], 0)
                        return not r or sock.recv(1, socket.MSG_PEEK) != b""
                    except OSError:
                        return False
                pos = start
                try:
                    while pos <= end:
                        data = src.read(rid, pos, min(READ_STEP * 4, end - pos + 1), alive)
                        if not data:
                            return
                        self.wfile.write(data)
                        pos += len(data)
                except (ConnectionError, BrokenPipeError, OSError):
                    return
                finally:
                    src.drop_reader(rid)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    # ---------- API ----------
    def open(self, url: str, ua: str, connections: int, token: str):
        """In background: controlla il link e prepara la sorgente. Risponde con il segnale ready."""
        def go():
            info = probe(url, ua or UA)
            if not info.get("ok"):
                self.ready.emit(token, {"ok": False, **info})
                return
            big_media = info["ranges"] and info["size"] > 8 * 1024 * 1024 and not info["ctype"].startswith(
                ("text/", "application/json", "application/vnd.apple.mpegurl", "application/dash"))
            if not big_media:
                self.ready.emit(token, {"ok": True, "local": None, **info})
                return
            sid = secrets.token_hex(8)
            self.sources[sid] = Source(sid, url, info, ua or UA, connections, self._on_state)
            local = f"http://127.0.0.1:{self.port}/s/{sid}/{urllib.parse.quote(info['name'] or 'video')}"
            self.ready.emit(token, {"ok": True, "local": local, "sid": sid, **info})
        threading.Thread(target=go, daemon=True).start()

    def _on_state(self, sid, st):
        self.state.emit(sid, st)

    def renew(self, sid: str, url: str):
        src = self.sources.get(sid)
        if not src:
            return

        def go():
            info = probe(url, src.ua)
            if not info.get("ok"):
                self.renewed.emit(sid, False, "This link doesn't work either." if info.get("expired")
                                  else "Link unreachable.")
                return
            if info["size"] != src.total:
                self.renewed.emit(sid, False, "It's a different file (different size): you need the link to the same movie.")
                return
            src.renew(url, info)
            self.renewed.emit(sid, True, "")
        threading.Thread(target=go, daemon=True).start()

    def speed(self, sid) -> float:
        s = self.sources.get(sid)
        return s.speed() if s else 0.0

    def close(self, sid):
        s = self.sources.pop(sid, None)
        if s:
            s.close()

    def close_all(self):
        for sid in list(self.sources):
            self.close(sid)


# ---------------------------------------------------------------- scadenza dei link
_EXP_KEYS = ("expires", "expire", "expiry", "exp", "e", "x-expires", "deadline", "validto", "valid_until", "ttl_end")


def link_expiry(url: str) -> float | None:
    """Prova a leggere dal link quando scade (epoch). None se non si capisce."""
    try:
        q = {k.lower(): v for k, v in urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)}
    except Exception:
        return None
    now = time.time()

    def plausible(t):
        return 1.6e9 < t < now + 86400 * 60      # anche scadenze passate da tempo (link vecchi in libreria)

    for k in _EXP_KEYS:
        v = q.get(k)
        if v and v.isdigit():
            t = int(v)
            if t > 1e12:
                t /= 1000
            if plausible(t):
                return float(t)
    for date_k, exp_k in (("x-amz-date", "x-amz-expires"), ("x-goog-date", "x-goog-expires")):
        if date_k in q and q.get(exp_k, "").isdigit():
            try:
                import calendar
                t = calendar.timegm(time.strptime(q[date_k], "%Y%m%dT%H%M%SZ")) + int(q[exp_k])
                if plausible(t):
                    return float(t)
            except Exception:
                pass
    return None
