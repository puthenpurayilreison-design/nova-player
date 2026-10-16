"""TV: "il PC fa tutto".

Il PC legge il film, mette i sottotitoli nell'immagine e lo ricomprime al volo (NVIDIA se c'è) in uno stream
H.264 leggero; la TV (DLNA, es. LG webOS) deve solo mostrarlo. Si comanda tutto da NOVA (barra, frecce,
telefono): ogni salto fa ripartire lo stream dal punto nuovo in pochi secondi.
Se il Wi-Fi non regge la qualità, NOVA scende da sola di un gradino invece di far scattare il film.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

from . import lan as L
from .config import DATA, settings, tool

NOWIN = 0x08000000 if sys.platform == "win32" else 0
TEXT_SUBS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
IMAGE_SUBS = {"hdmv_pgs_subtitle", "pgssub", "dvd_subtitle", "dvdsub", "dvb_subtitle"}


class CastSession(QObject):
    status = Signal(str, str)          # testo, tipo (info/err)
    changed = Signal()                 # stato/qualità cambiati (per aggiornare i controlli)
    _tvpos = Signal(object, int)       # (secondi dalla TV, generazione)
    _started = Signal(bool, str, int)

    def __init__(self, page, tv: dict, srv, quality: str = "auto"):
        super().__init__(page)
        self.page, self.tv, self.srv = page, tv, srv
        self.quality = quality
        self.auto = quality == "auto"
        self.level = L.TV_QUALITY.get(quality, 1)
        if self.auto:
            # parte dalla qualità che il Wi-Fi verso questa TV ha retto l'ultima volta
            learned = (settings.get("player", "tv_learned") or {}).get(tv.get("control", ""))
            if isinstance(learned, int) and 0 <= learned < len(L.TV_LADDER):
                self.level = learned
        self.base = 0.0                # punto del film da cui parte lo stream attuale
        self.mid = None
        self.gen = 0                   # cambia a ogni ripartenza: risposte vecchie ignorate
        self.paused = False
        self._paused_at = 0.0
        self._pause_t = 0.0
        self._wall0 = None             # quando la TV ha iniziato a ricevere
        self._paused_total = 0.0
        self._tv_rel = None            # posizione dichiarata dalla TV
        self._tv_rel_t = 0.0
        self._hist: list[tuple[float, float]] = []
        self._last_down = 0.0
        self._healthy_since = None
        self._pending = None
        self._sub_file = None
        self._sub_key = None
        self.active = True
        self.duration = float(page.get_prop("duration", 0) or 0)
        self._seek_t = QTimer(self, singleShot=True, interval=450)
        self._seek_t.timeout.connect(self._do_seek)
        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self._tick)
        self._tvpos.connect(self._got_tvpos)
        self._started.connect(self._on_started)

    # ---------- informazioni sul film ----------
    def _media_info(self, start: float) -> dict:
        p = self.page
        src = p.current_url
        if p.turbo_sid:
            src = p.get_prop("path", src) or src          # passa dallo Stream Turbo (veloce, con salti)
        tl = p.track_list
        vid = next((t for t in tl if t.get("type") == "video" and t.get("selected") and not t.get("albumart")), None)
        aud = next((t for t in tl if t.get("type") == "audio" and t.get("selected")), None)
        vp = p.get_prop("video-params", {}) or {}
        info = {"src": src, "start": max(0.0, start), "level": self.level,
                "w": (vid or {}).get("demux-w") or vp.get("w") or 1920,
                "h": (vid or {}).get("demux-h") or vp.get("h") or 1080,
                "hdr": (vp.get("gamma") or "") in L.HDR_GAMMA,
                "audio": (aud or {}).get("ff-index"),
                "ach": (aud or {}).get("demux-channel-count") or 2,
                "gain": getattr(p, "_lgain", 0.0) or 0.0,
                "sub": self._sub_info(src)}
        info["plan_key"] = (bool(info["hdr"]), (info["sub"] or {}).get("kind"))
        return info

    def _sub_info(self, src: str):
        sub = next((t for t in self.page.track_list if t.get("type") == "sub" and t.get("selected")), None)
        if not sub:
            return None
        codec = (sub.get("codec") or "").lower()
        ext = sub.get("external-filename")
        if ext and os.path.isfile(ext):
            return {"kind": "text", "file": ext}
        if codec in IMAGE_SUBS and sub.get("ff-index") is not None:
            return {"kind": "image", "stream": sub["ff-index"]}
        if codec in TEXT_SUBS and os.path.isfile(src):
            key = (src, sub.get("ff-index"))
            if self._sub_key == key and self._sub_file and os.path.isfile(self._sub_file):
                return {"kind": "text", "file": self._sub_file}
            return {"kind": "text-pending", "key": key, "ff": sub.get("ff-index"), "codec": codec}
        if codec in TEXT_SUBS:
            return {"kind": "text-link"}
        return None

    def _extract(self, src, ff, codec, key, wait: float) -> bool:
        """Estrae i sottotitoli di testo dal file (a priorità bassa). True se pronti entro 'wait' secondi."""
        out = DATA / "cast"
        out.mkdir(parents=True, exist_ok=True)
        dst = out / f"subs_{abs(hash(key)) % 10**8}.{'ass' if codec in ('ass', 'ssa') else 'srt'}"
        done = threading.Event()

        def work():
            try:
                if not dst.exists() or dst.stat().st_size == 0:
                    flags = NOWIN | (0x00004000 if sys.platform == "win32" else 0)
                    subprocess.run([tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", src, "-map", f"0:{ff}",
                                    "-vn", "-an", "-dn", str(dst)], capture_output=True, timeout=900,
                                   creationflags=flags)
                if dst.exists() and dst.stat().st_size > 0:
                    self._sub_file, self._sub_key = str(dst), key
            finally:
                done.set()
        threading.Thread(target=work, daemon=True).start()
        done.wait(wait)
        return self._sub_file is not None and self._sub_key == key

    # ---------- avvio e ripartenza ----------
    def start(self, pos: float):
        self.timer.start()
        self._restart(pos, first=True)

    def _restart(self, pos: float, first=False, why=""):
        self.gen += 1
        gen = self.gen
        self.base = max(0.0, min(pos, self.duration - 2 if self.duration > 5 else pos))
        self._wall0 = None
        self._paused_total = 0.0
        self._tv_rel = None
        self._hist = []
        self.paused = False
        info = self._media_info(self.base)
        old = self.mid

        def work():
            sub = info.get("sub") or {}
            note = ""
            if sub.get("kind") == "text-pending":
                # sottotitoli dentro il file: estratti una volta (pochi secondi su SSD), poi restano pronti
                ok = self._extract(info["src"], sub["ff"], sub["codec"], sub["key"], 8.0 if first else 0.5)
                info["sub"] = {"kind": "text", "file": self._sub_file} if ok else None
                if not ok:
                    note = "subs-later"
                    threading.Thread(target=self._subs_when_ready, args=(sub["key"],), daemon=True).start()
            elif sub.get("kind") == "text-link":
                info["sub"] = None
                note = "subs-link"
            info["plan_key"] = (bool(info["hdr"]), (info.get("sub") or {}).get("kind"))
            mid = self.srv.add_pc(info)
            url = f"{self.srv.base()}/pc/{mid}.ts"
            try:
                L.cast(self.tv, url, self.page.title.text() or "NOVA", "video/mp2t", True)
                self.mid = mid
                self._started.emit(True, note, gen)
            except Exception as e:
                self._started.emit(False, str(e)[:140], gen)
            if old:
                m = self.srv.media.get(old)
                if m:
                    L._kill(m.get("proc"))
        threading.Thread(target=work, daemon=True).start()
        h, kb = L.TV_LADDER[self.level]
        if why:
            self.status.emit(why, "info")
        self.changed.emit()
        return h, kb

    def _subs_when_ready(self, key):
        for _ in range(900):
            time.sleep(1)
            if not self.active:
                return
            if self._sub_key == key and self._sub_file:
                QTimer.singleShot(0, self, lambda: self._restart(self.position(),
                                                                why="Sottotitoli pronti: li aggiungo sulla TV…"))
                return

    def _on_started(self, ok, note, gen):
        if gen != self.gen:
            return
        if not ok:
            self.status.emit(f"La TV non ha accettato lo stream ({note}). Controlla che sia accesa e sullo stesso "
                             "Wi-Fi, e che Windows permetta a NOVA le reti private.", "err")
            return
        if note == "subs-link":
            self.status.emit("Sulla TV i sottotitoli dentro un link non si possono mettere (servirebbe scaricare "
                             "tutto il film): scaricalo, oppure carica un file .srt.", "info")
        elif note == "subs-later":
            self.status.emit("Preparo i sottotitoli per la TV: compaiono tra poco.", "info")

    # ---------- comandi ----------
    def seek(self, pos: float):
        """Salti ravvicinati (frecce premute più volte) vengono uniti in uno solo."""
        self._pending = max(0.0, pos if self.duration <= 0 else min(pos, self.duration - 2))
        self._seek_t.start()
        self.changed.emit()

    def seek_rel(self, s: float):
        self.seek((self._pending if self._pending is not None else self.position()) + s)

    def _do_seek(self):
        pos, self._pending = self._pending, None
        if pos is None:
            return
        # rete in salute da un minuto: al salto si può risalire di qualità senza interruzioni in più
        if self.auto and self.level > L.TV_QUALITY["auto"] and self._healthy_since \
                and time.time() - self._healthy_since > 60:
            self.level -= 1
        self._restart(pos)

    def toggle_pause(self):
        if self.paused:
            away = time.time() - self._pause_t
            self.paused = False
            if away > 90:
                # pausa lunga: la TV può aver chiuso la connessione, si riparte pulito dallo stesso punto
                self._restart(self._paused_at)
                return
            self._paused_total += away
            threading.Thread(target=self._cmd, args=("Play",), daemon=True).start()
        else:
            self._paused_at = self.position()
            self._pause_t = time.time()
            self.paused = True
            threading.Thread(target=self._cmd, args=("Pause",), daemon=True).start()
        self.changed.emit()

    def _cmd(self, a):
        try:
            L.tv_command(self.tv, a)
        except Exception:
            pass

    def set_quality(self, q: str):
        self.quality, self.auto = q, q == "auto"
        self.level = L.TV_QUALITY.get(q, 1)
        self._restart(self.position())

    def _learn(self):
        if not self.auto:
            return
        d = dict(settings.get("player", "tv_learned") or {})
        if d.get(self.tv.get("control", "")) != self.level:
            d[self.tv.get("control", "")] = self.level
            settings.set("player", "tv_learned", d, notify=False)

    def stop(self) -> float:
        pos = self.position()
        self._learn()
        self.active = False
        self.timer.stop()
        self._seek_t.stop()
        for m in list(self.srv.media.values()):
            L._kill(m.get("proc"))
        threading.Thread(target=self._cmd, args=("Stop",), daemon=True).start()
        return pos

    # ---------- posizione e salute della rete ----------
    def _media(self):
        return self.srv.media.get(self.mid) if self.mid else None

    def position(self) -> float:
        if self._pending is not None:
            return self._pending
        if self.paused:
            return self._paused_at
        m = self._media()
        if self._tv_rel is not None:
            p = self.base + self._tv_rel + (time.time() - self._tv_rel_t)
        elif m and m.get("first_byte"):
            # la TV parte dopo aver riempito un po' di buffer (circa 1,5 s)
            p = self.base + max(0.0, time.time() - m["first_byte"] - 1.5 - self._paused_total)
        else:
            p = self.base
        if m:
            p = min(p, float(m.get("enc_t") or p))      # non può essere più avanti di quanto inviato
        return max(0.0, min(p, self.duration or p))

    def buffer_ahead(self) -> float:
        m = self._media()
        if not m or not m.get("first_byte"):
            return 0.0
        return max(0.0, float(m.get("enc_t") or 0) - self.position())

    def info_text(self) -> str:
        h, kb = L.TV_LADDER[self.level]
        m = self._media() or {}
        h = min(h, int(m.get("h") or h))
        if self._pending is not None:
            return f"TV · salto a {_t(self._pending)}…"
        if not m.get("first_byte"):
            return f"TV · avvio {h}p…"
        q = "auto" if self.auto else "fissa"
        return f"TV · {h}p {kb / 1000:g} Mbit/s ({q}) · buffer {self.buffer_ahead():.0f}s"

    def _got_tvpos(self, rel, gen):
        if gen == self.gen and rel is not None and rel > 0 and not self.paused:
            self._tv_rel, self._tv_rel_t = float(rel), time.time()

    def _tick(self):
        if not self.active:
            return
        m = self._media()
        now = time.time()
        if not m:
            return
        if m.get("failed"):
            m["failed"] = False
            self.status.emit("Non riesco a preparare il video per la TV: " + (m.get("err") or "errore di ffmpeg")[:160],
                             "err")
            return
        if self.duration and self.position() >= self.duration - 1.5 and m.get("ended"):
            self.status.emit("Film finito sulla TV.", "info")
            self.page.stop_cast()
            return
        # chiede alla TV dove si trova (ogni 3 s, in background)
        if int(now) % 3 == 0 and not self.paused:
            gen = self.gen
            threading.Thread(target=lambda: self._tvpos.emit(L.tv_position(self.tv), gen), daemon=True).start()
        if self.paused or not m.get("first_byte") or now - m["first_byte"] < 4:
            self.changed.emit()
            return
        enc = float(m.get("enc_t") or 0)
        self._hist.append((now, enc))
        self._hist = [x for x in self._hist if now - x[0] <= 8]
        ahead = self.buffer_ahead()
        if len(self._hist) >= 5:
            dt = self._hist[-1][0] - self._hist[0][0]
            rate = (self._hist[-1][1] - self._hist[0][1]) / dt if dt > 0 else 1.0
            if rate >= 0.98 or ahead > 15:
                self._healthy_since = self._healthy_since or now
            else:
                self._healthy_since = None
            # il Wi-Fi (o il PC) non sta al passo e il buffer della TV si svuota: salta subito alla qualità
            # che la rete regge davvero (velocità misurata × 0,8 di margine), senza scendere un gradino per volta
            if self.auto and rate < 0.9 and ahead < 3.5 and now - self._last_down > 15 \
                    and self.level < len(L.TV_LADDER) - 1:
                target = L.TV_LADDER[self.level][1] * max(0.1, rate) * 0.8
                new = next((i for i in range(self.level + 1, len(L.TV_LADDER)) if L.TV_LADDER[i][1] <= target),
                           len(L.TV_LADDER) - 1)
                self.level = new
                self._last_down = now
                self._learn()
                h, kb = L.TV_LADDER[self.level]
                self._restart(self.position(), why=f"Wi-Fi lento: passo a {h}p {kb / 1000:g} Mbit/s per non "
                                                    "far scattare il film.")
                return
        self.changed.emit()


def _t(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"
