"""Rete di casa: telecomando dal telefono e trasmissione alla TV (DLNA, es. LG webOS).

Un solo server HTTP sulla rete locale, protetto da un codice casuale nel percorso:
  /<code>/            pagina del telecomando (si apre col QR dal telefono)
  /<code>/state       stato del player (JSON)
  /<code>/cmd?a=...   comandi (play, pausa, salti, volume, tracce)
  /<code>/m/<id>      il video per la TV, con salti (Range)
  /<code>/live/<id>   il video per la TV con l'audio convertito in AC3 (per DTS/TrueHD che le LG 2019+ non leggono)
  /<code>/pc/<id>     "il PC fa tutto": il PC decodifica, mette i sottotitoli nell'immagine e ricomprime al volo
                      (NVIDIA se c'è) in uno stream leggero; la TV deve solo mostrarlo
"""
from __future__ import annotations

import html
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import tool

NOWIN = 0x08000000 if sys.platform == "win32" else 0
TV_AUDIO_OK = {"aac", "ac3", "eac3", "mp3", "mp2", "pcm_s16le", "opus", "vorbis", "flac"}
MIME = {".mkv": "video/x-matroska", ".mp4": "video/mp4", ".m4v": "video/mp4", ".avi": "video/x-msvideo",
        ".ts": "video/mp2t", ".m2ts": "video/mp2t", ".mov": "video/quicktime", ".webm": "video/webm"}


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.1.1", 9))          # nessun pacchetto inviato: serve solo a scegliere la scheda di rete
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


REMOTE_HTML = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="theme-color" content="#0e0e12"><title>NOVA · Telecomando</title>
<style>
:root{--a:%ACCENT%;--bg:#0e0e12;--s:#1b1b22;--t:#f2f2f5;--m:#9a9aa8}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--t);font:16px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
padding:20px 16px calc(24px + env(safe-area-inset-bottom));min-height:100vh;display:flex;flex-direction:column;gap:18px}
h1{font-size:13px;letter-spacing:3px;color:var(--a);margin:4px 0 0;font-weight:800}
#t{font-size:21px;font-weight:700;min-height:28px;word-break:break-word}
#time{color:var(--m);font-variant-numeric:tabular-nums;font-size:14px;display:flex;justify-content:space-between}
input[type=range]{width:100%;accent-color:var(--a);height:28px}
.row{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.row.three{grid-template-columns:repeat(3,1fr)}
button{background:var(--s);color:var(--t);border:0;border-radius:18px;height:62px;font-size:17px;font-weight:600}
button:active{transform:scale(.96);background:#26262f}
#pp{height:96px;font-size:34px;background:var(--a);color:#fff;border-radius:28px;width:100%}
.lbl{color:var(--m);font-size:12px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:-8px}
#off{display:none;color:#ff7a7a;text-align:center}
</style></head><body>
<h1>NOVA</h1><div id="t">…</div>
<div><input id="seek" type="range" min="0" max="1000" value="0"><div id="time"><span id="p">0:00</span><span id="d">0:00</span></div></div>
<button id="pp" onclick="c('toggle')">⏯</button>
<div class="row"><button onclick="c('seek',-60)">−1m</button><button onclick="c('seek',-10)">−10s</button>
<button onclick="c('seek',10)">+10s</button><button onclick="c('seek',60)">+1m</button></div>
<div class="lbl">Volume</div>
<div class="row three"><button onclick="c('vol',-5)">🔉</button><button onclick="c('mute')">🔇</button><button onclick="c('vol',5)">🔊</button></div>
<div class="lbl">Film</div>
<div class="row"><button onclick="c('audio')">Audio</button><button onclick="c('sub')">Sub</button>
<button onclick="c('fs')">⛶</button><button onclick="c('next')">⏭</button></div>
<div id="off">NOVA non risponde: è aperto sul PC?</div>
<script>
const B=location.pathname.replace(/\\/$/,'');let drag=false,dur=0;
function f(s){s=Math.max(0,s|0);const h=s/3600|0,m=(s%3600)/60|0,x=s%60;return(h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')}
function c(a,v){fetch(B+'/cmd?a='+a+(v!==undefined?'&v='+v:''),{method:'POST'}).then(()=>setTimeout(u,150));if(navigator.vibrate)navigator.vibrate(12)}
const sk=document.getElementById('seek');sk.oninput=()=>{drag=true;document.getElementById('p').textContent=f(sk.value/1000*dur)};
sk.onchange=()=>{c('goto',(sk.value/1000*dur).toFixed(1));drag=false};
function u(){fetch(B+'/state').then(r=>r.json()).then(s=>{document.getElementById('off').style.display='none';
document.getElementById('t').textContent=s.title||'Nessun video';dur=s.dur||0;
if(!drag){sk.value=dur?s.pos/dur*1000:0;document.getElementById('p').textContent=f(s.pos)}
document.getElementById('d').textContent=f(dur);document.getElementById('pp').textContent=s.paused?'▶':'❚❚'})
.catch(()=>{document.getElementById('off').style.display='block'})}
setInterval(u,1000);u();
</script></body></html>"""


class LanServer(QObject):
    command = Signal(str, str)         # azione, valore (dal telefono)

    def __init__(self, state_fn):
        super().__init__()
        self.state_fn = state_fn
        self.code = secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")
        self.media: dict[str, dict] = {}
        self.httpd = None
        self.port = 0
        self.accent = "#22D3EE"

    def start(self, port=47800) -> bool:
        if self.httpd:
            return True
        mgr = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _parts(self):
                u = urllib.parse.urlparse(self.path)
                parts = [p for p in u.path.split("/") if p]
                if not parts or parts[0] != mgr.code:
                    return None, u
                return parts[1:], u

            def _send(self, code, body: bytes, ctype="text/plain; charset=utf-8"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                parts, u = self._parts()
                if parts is None:
                    return self._send(404, b"")
                if parts[:1] == ["cmd"]:
                    q = urllib.parse.parse_qs(u.query)
                    mgr.command.emit(q.get("a", [""])[0], q.get("v", [""])[0])
                    return self._send(200, b"ok")
                self._send(404, b"")

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head=False):
                parts, u = self._parts()
                if parts is None:
                    return self._send(404, b"")
                if not parts:
                    return self._send(200, REMOTE_HTML.replace("%ACCENT%", mgr.accent).encode(),
                                      "text/html; charset=utf-8")
                if parts[0] == "state":
                    return self._send(200, json.dumps(mgr.state_fn()).encode(), "application/json")
                if parts[0] == "cmd":          # anche via GET (comodo da browser vecchi)
                    q = urllib.parse.parse_qs(u.query)
                    mgr.command.emit(q.get("a", [""])[0], q.get("v", [""])[0])
                    return self._send(200, b"ok")
                if parts[0] in ("m", "live", "pc") and len(parts) >= 2:
                    m = mgr.media.get(parts[1].split(".")[0])
                    if not m:
                        return self._send(404, b"")
                    if parts[0] == "pc":
                        return mgr._serve_pc(self, m, head)
                    if parts[0] == "live":
                        return mgr._serve_live(self, m, head)
                    return mgr._serve_media(self, m, head)
                self._send(404, b"")

        for p in range(port, port + 20):
            try:
                self.httpd = ThreadingHTTPServer(("0.0.0.0", p), H)
                break
            except OSError:
                continue
        if not self.httpd:
            return False
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def base(self) -> str:
        return f"http://{lan_ip()}:{self.port}/{self.code}"

    def remote_url(self) -> str:
        return self.base() + "/"

    # ---------- video per la TV ----------
    def add_media(self, src: str, live_audio: int | None = None, start: float = 0.0) -> str:
        mid = secrets.token_hex(5)
        name = Path(urllib.parse.urlparse(src).path).name if src.startswith("http") else Path(src).name
        self.media[mid] = {"src": src, "audio": live_audio, "start": start, "name": name or "video"}
        return mid

    def _serve_media(self, h, m, head):
        src = m["src"]
        dlna = {"transferMode.dlna.org": "Streaming",
                "contentFeatures.dlna.org": "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000",
                "Accept-Ranges": "bytes"}
        if src.startswith("http"):
            # link (anche tramite Stream Turbo): inoltra la richiesta con lo stesso Range
            u = urllib.parse.urlparse(src)
            conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(
                u.hostname, u.port, timeout=60)
            hdr = {"User-Agent": "NOVA"}
            if h.headers.get("Range"):
                hdr["Range"] = h.headers["Range"]
            try:
                conn.request("HEAD" if head else "GET", u.path + ("?" + u.query if u.query else ""), headers=hdr)
                r = conn.getresponse()
                h.send_response(r.status)
                for k in ("Content-Length", "Content-Range", "Content-Type"):
                    if r.getheader(k):
                        h.send_header(k, r.getheader(k))
                for k, v in dlna.items():
                    h.send_header(k, v)
                h.end_headers()
                if not head:
                    while True:
                        b = r.read(256 * 1024)
                        if not b:
                            break
                        h.wfile.write(b)
            except (OSError, http.client.HTTPException):
                pass
            finally:
                conn.close()
            return
        try:
            size = os.path.getsize(src)
        except OSError:
            return h._send(404, b"")
        start, end = 0, size - 1
        rng = re.match(r"bytes=(\d*)-(\d*)", h.headers.get("Range") or "")
        if rng:
            if rng.group(1):
                start = int(rng.group(1))
                if rng.group(2):
                    end = min(size - 1, int(rng.group(2)))
            elif rng.group(2):
                start = max(0, size - int(rng.group(2)))
        h.send_response(206 if rng else 200)
        h.send_header("Content-Type", MIME.get(Path(src).suffix.lower(), "video/x-matroska"))
        h.send_header("Content-Length", str(end - start + 1))
        if rng:
            h.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        for k, v in dlna.items():
            h.send_header(k, v)
        h.end_headers()
        if head:
            return
        try:
            with open(src, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    b = f.read(min(1024 * 1024, left))
                    if not b:
                        break
                    h.wfile.write(b)
                    left -= len(b)
        except OSError:
            pass

    def _serve_live(self, h, m, head):
        h.send_response(200)
        h.send_header("Content-Type", "video/mp2t")
        h.send_header("transferMode.dlna.org", "Streaming")
        h.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=00;DLNA.ORG_CI=1;DLNA.ORG_FLAGS=01700000000000000000000000000000")
        h.send_header("Connection", "close")
        h.end_headers()
        if head:
            return
        a = m.get("audio")
        cmd = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-ss", f"{m.get('start', 0):.1f}", "-i", m["src"],
               "-map", "0:v:0", "-map", f"0:a:{a or 0}", "-c:v", "copy", "-c:a", "ac3", "-b:a", "640k",
               "-f", "mpegts", "pipe:1"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWIN)
        try:
            while True:
                b = p.stdout.read(256 * 1024)
                if not b:
                    break
                h.wfile.write(b)
        except OSError:
            pass
        finally:
            p.kill()
        h.close_connection = True


    # ---------- "il PC fa tutto" ----------
    def add_pc(self, info: dict) -> str:
        mid = secrets.token_hex(5)
        self.media[mid] = dict(info, pc=True, enc_t=info.get("start", 0.0), first_byte=None, proc=None,
                               failed=False, plan=None)
        # tiene solo gli ultimi stream (ogni salto ne crea uno nuovo)
        for old in list(self.media)[:-6]:
            o = self.media.pop(old)
            _kill(o.get("proc"))
        return mid

    def _serve_pc(self, h, m, head):
        h.send_response(200)
        h.send_header("Content-Type", "video/mp2t")
        h.send_header("transferMode.dlna.org", "Streaming")
        h.send_header("contentFeatures.dlna.org",
                      "DLNA.ORG_OP=00;DLNA.ORG_CI=1;DLNA.ORG_FLAGS=01700000000000000000000000000000")
        h.send_header("Cache-Control", "no-store")
        h.send_header("Connection", "close")
        h.end_headers()
        h.close_connection = True
        if head:
            return
        _kill(m.get("proc"))            # la TV a volte riapre il link: un solo ffmpeg per stream
        plans = tv_plans(m)
        first = TV_PLAN_OK.get(m.get("plan_key"), 0)
        for i in range(min(first, len(plans) - 1), len(plans)):
            label, args = plans[i]
            try:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NOWIN)
            except OSError:
                continue
            m["proc"], m["plan"] = p, label
            threading.Thread(target=_progress, args=(p, m), daemon=True).start()
            try:
                b = p.stdout.read(188 * 512)
            except OSError:
                b = b""
            if not b:
                _kill(p)
                if m.get("proc") is not p:
                    return                  # sostituito da una nuova richiesta
                continue                    # questa ricetta non parte su questo PC: la prossima
            TV_PLAN_OK[m.get("plan_key")] = i
            m["first_byte"] = time.time()
            try:
                while b:
                    h.wfile.write(b)
                    b = p.stdout.read(256 * 1024)
                m["ended"] = True
            except OSError:
                pass                        # la TV ha chiuso (salto, stop)
            finally:
                _kill(p)
            return
        m["failed"] = True


TV_PLAN_OK: dict = {}
# qualità per la TV, dalla migliore: (altezza, kbit/s)
TV_LADDER = [(1080, 14000), (1080, 9000), (720, 5000), (720, 3000), (540, 1800)]
TV_QUALITY = {"auto": 1, "high": 0, "medium": 1, "low": 2, "slow": 3}
HDR_GAMMA = {"pq", "hlg"}


def _kill(p):
    if p and p.poll() is None:
        try:
            p.kill()
        except OSError:
            pass


def _progress(p, m):
    """Legge -progress di ffmpeg: fin dove è arrivato lo stream (secondi del film)."""
    err = []
    try:
        for line in iter(p.stderr.readline, b""):
            line = line.decode(errors="ignore").strip()
            if line.startswith("out_time_us="):
                try:
                    v = int(line.split("=", 1)[1])
                    if v > 0 and m.get("proc") is p:
                        m["enc_t"] = m.get("start", 0.0) + v / 1e6
                except ValueError:
                    pass
            elif line and "=" not in line:
                err.append(line)
                m["err"] = "\n".join(err[-4:])
    except (OSError, ValueError):
        pass


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _filter_path(p: str) -> str:
    """Percorso per il filtro subtitles di ffmpeg (Windows: C\\:/cartella/file.srt)."""
    p = p.replace("\\", "/")
    return p.replace(":", "\\:").replace("'", "\\'")


def tv_plans(m: dict) -> list[tuple[str, list[str]]]:
    """Ricette ffmpeg dalla più veloce alla più sicura (se una non parte si passa alla successiva)."""
    from .remux import _nvenc_ok
    src, start = m["src"], float(m.get("start") or 0)
    th, kbps = TV_LADDER[m.get("level", 1)]
    sw, sh = int(m.get("w") or 1920), int(m.get("h") or 1080)
    th = min(th, sh)
    tw, th = _even(sw * th / sh), _even(th)
    hdr = bool(m.get("hdr"))
    sub = m.get("sub") or {}
    net = src.startswith(("http://", "https://"))
    base = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", "-fflags", "+genpts"]
    if net:
        base += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                 "-reconnect_delay_max", "10"]
    seek = ["-ss", f"{start:.2f}"] if start > 0.5 else []
    # catena video su CPU (dopo la decodifica): HDR→SDR rimpicciolendo prima, poi i sottotitoli
    if hdr:
        cpu_v = (f"zscale=w={tw}:h={th}:f=bicubic:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                 "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    else:
        cpu_v = (f"scale={tw}:{th}:flags=bicubic," if (tw, th) != (sw, sh) else "") + "format=yuv420p"
    text = sub.get("file") if sub.get("kind") == "text" else None
    if text:
        style = "FontName=Arial,FontSize=22,Outline=1.6,Shadow=0.8,MarginV=26,BorderStyle=1"
        cpu_v += (f",setpts=PTS+{start:.3f}/TB,subtitles='{_filter_path(text)}':force_style='{style}',"
                  f"setpts=PTS-{start:.3f}/TB")
    image = sub.get("stream") if sub.get("kind") == "image" else None
    a = m.get("audio")
    amap = ["-map", f"0:{a}"] if a is not None else ["-map", "0:a:0?"]
    ach = int(m.get("ach") or 2)
    af = []
    if m.get("gain"):
        af = ["-af", f"volume={float(m['gain']):.1f}dB"]
    aud = amap + af + ["-c:a", "ac3", "-b:a", "448k" if ach > 2 else "224k", "-ac", str(min(6, max(1, ach)))]
    rate = ["-b:v", f"{kbps}k", "-maxrate", f"{int(kbps * 1.25)}k", "-bufsize", f"{kbps}k", "-g", "50",
            "-keyint_min", "25"]
    nv = ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-rc", "vbr", "-spatial-aq", "1",
          "-bf", "2", "-forced-idr", "1"] + rate + ["-profile:v", "high", "-level", "4.1"]
    x264 = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency"] + rate + \
           ["-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"]
    out = ["-f", "mpegts", "-mpegts_flags", "+resend_headers", "-muxdelay", "0", "-flush_packets", "1",
           "-progress", "pipe:2", "-stats_period", "0.5", "pipe:1"]

    def mk(label, hw, vchain, enc):
        if image is not None:
            fc = (f"[0:v:0]{vchain}[v];[0:{image}]scale={tw}:{th}[s];"
                  f"[v][s]overlay=eof_action=pass:repeatlast=0,format=yuv420p[o]")
            v = ["-filter_complex", fc, "-map", "[o]"]
        else:
            v = ["-map", "0:v:0", "-vf", vchain]
        return label, base + hw + seek + ["-i", src] + v + aud + enc + out

    plans = []
    if _nvenc_ok():
        if not hdr and not text and image is None:
            plans.append(("GPU NVIDIA (tutto sulla scheda video)",
                          base + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] + seek + ["-i", src] +
                          ["-map", "0:v:0", "-vf", f"scale_cuda={tw}:{th}:format=yuv420p"] + aud + nv + out))
        if hdr:
            pl = (f"libplacebo=w={tw}:h={th}:tonemapping=bt.2390:colorspace=bt709:color_primaries=bt709:"
                  "color_trc=bt709:range=tv:format=yuv420p")
            if text:
                pl += cpu_v[cpu_v.index(",setpts"):]
            plans.append(mk("GPU NVIDIA (HDR con la GPU)",
                            ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk", "-hwaccel", "cuda"], pl, nv))
        plans.append(mk("GPU NVIDIA", ["-hwaccel", "cuda"], cpu_v, nv))
        plans.append(mk("GPU NVIDIA (decodifica dal processore)", [], cpu_v, nv))
    plans.append(mk("Processore (decodifica hardware)", ["-hwaccel", "auto"], cpu_v, x264))
    plans.append(mk("Processore", [], cpu_v, x264))
    return plans


# ---------------------------------------------------------------- DLNA
def discover(timeout=3.0) -> list[dict]:
    """TV e lettori DLNA della rete: [{'name', 'control', 'location'}]."""
    msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
           "ST: urn:schemas-upnp-org:service:AVTransport:1\r\n\r\n").encode()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        s.bind((lan_ip(), 0))
    except OSError:
        pass
    s.settimeout(0.5)
    locs = set()
    end = time.time() + timeout
    try:
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
        while time.time() < end:
            try:
                data, _ = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                locs.add(m.group(1).decode())
    finally:
        s.close()
    out = []
    for loc in locs:
        try:
            d = _describe(loc)
            if d:
                out.append(d)
        except Exception:
            pass
    return out


def _describe(location: str) -> dict | None:
    with urllib.request.urlopen(location, timeout=4) as r:
        xml = r.read()
    root = ET.fromstring(xml)
    ns = {"d": "urn:schemas-upnp-org:device-1-0"}
    name = root.findtext(".//d:friendlyName", default="TV", namespaces=ns)
    for svc in root.iter("{urn:schemas-upnp-org:device-1-0}service"):
        st = svc.findtext("d:serviceType", default="", namespaces=ns)
        if "AVTransport" in st:
            ctrl = svc.findtext("d:controlURL", default="", namespaces=ns)
            return {"name": name, "control": urllib.parse.urljoin(location, ctrl), "location": location}
    return None


def _soap(control: str, action: str, args: str):
    body = (f'<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="urn:schemas-upnp-org:service:AVTransport:1"><InstanceID>0</InstanceID>{args}'
            f'</u:{action}></s:Body></s:Envelope>').encode()
    req = urllib.request.Request(control, data=body, method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"urn:schemas-upnp-org:service:AVTransport:1#{action}"'})
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read()


def cast(tv: dict, url: str, title: str, mime: str, live: bool):
    flags = "DLNA.ORG_OP=00;DLNA.ORG_CI=1" if live else "DLNA.ORG_OP=01;DLNA.ORG_CI=0"
    didl = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            f'<item id="0" parentID="-1" restricted="1"><dc:title>{html.escape(title)}</dc:title>'
            '<upnp:class>object.item.videoItem.movie</upnp:class>'
            f'<res protocolInfo="http-get:*:{mime}:{flags};DLNA.ORG_FLAGS=01700000000000000000000000000000">'
            f'{html.escape(url)}</res></item></DIDL-Lite>')
    try:
        _soap(tv["control"], "Stop", "")
    except Exception:
        pass
    _soap(tv["control"], "SetAVTransportURI",
          f"<CurrentURI>{html.escape(url)}</CurrentURI><CurrentURIMetaData>{html.escape(didl)}</CurrentURIMetaData>")
    _soap(tv["control"], "Play", "<Speed>1</Speed>")


def tv_position(tv: dict) -> float | None:
    """Secondi riprodotti dalla TV nello stream attuale (None se la TV non lo dice)."""
    try:
        x = _soap(tv["control"], "GetPositionInfo", "").decode(errors="ignore")
    except Exception:
        return None
    m = re.search(r"<RelTime>(\d+):(\d+):(\d+)", x)
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def tv_state(tv: dict) -> str:
    """PLAYING, PAUSED_PLAYBACK, STOPPED, TRANSITIONING… ('' se non risponde)."""
    try:
        x = _soap(tv["control"], "GetTransportInfo", "").decode(errors="ignore")
    except Exception:
        return ""
    m = re.search(r"<CurrentTransportState>([A-Z_]+)<", x)
    return m.group(1) if m else ""


def tv_command(tv: dict, action: str, seconds: float | None = None):
    if action == "Seek":
        t = int(max(0, seconds or 0))
        _soap(tv["control"], "Seek", f"<Unit>REL_TIME</Unit><Target>{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}</Target>")
    elif action == "Play":
        _soap(tv["control"], "Play", "<Speed>1</Speed>")
    else:
        _soap(tv["control"], action, "")
