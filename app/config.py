"""Percorsi, impostazioni e storico di NOVA."""
from __future__ import annotations

import json
import os
import sys
import copy
from pathlib import Path

APP_NAME = "NOVA"
FROZEN = getattr(sys, "frozen", False)          # True quando gira come NOVA.exe
# cartella dell'app: accanto a NOVA.exe se compilata, altrimenti la cartella del progetto
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
VERSION = "4.6"

# progetto pubblico (GitHub): link per le donazioni, vuoti = pulsante nascosto
REPO_URL = "https://github.com/puthenpurayilreison-design/nova-player"
DONATE_URL = ""
CRYPTO = {}          # es. {"USDT (TRON)": "T...", "Bitcoin": "bc1..."}

if sys.platform == "win32":
    DATA = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
else:
    DATA = Path.home() / ".config" / APP_NAME
DATA.mkdir(parents=True, exist_ok=True)
(DATA / "logs").mkdir(exist_ok=True)
(DATA / "torrents").mkdir(exist_ok=True)
(DATA / "watch_later").mkdir(exist_ok=True)
(DATA / "covers").mkdir(exist_ok=True)

SETTINGS_FILE = DATA / "settings.json"
HISTORY_FILE = DATA / "history.json"
EXE = ".exe" if sys.platform == "win32" else ""


def tool(name: str) -> str:
    """Restituisce il percorso di un binario incluso (bin/) o il nome nel PATH."""
    p = BIN / f"{name}{EXE}"
    if p.exists():
        return str(p)
    if name == "yt-dlp":
        q = Path(sys.executable).parent / f"yt-dlp{EXE}"
        if q.exists():
            return str(q)
    return name


def cover_path(key: str) -> Path:
    """Copertina (fotogramma) associata a un elemento della cronologia."""
    import hashlib
    return DATA / "covers" / (hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:20] + ".jpg")


DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads" / "NOVA")

DEFAULTS: dict = {
    "appearance": {
        "theme": "midnight",        # midnight | oled | ocean | forest | sakura | light
        "accent": "#22D3EE",
        "animations": "full",       # full | balanced | minimal | none
        "density": "normal",        # compact | normal | spacious
        "font_scale": 1.0,
        "intro": True,              # breve animazione del logo all'avvio
    },
    "player": {
        "hwdec": True,
        "quality": "max",           # max | balanced | saver
        "audio_lang": "",            # vuoto = traccia predefinita del file
        "sub_lang": "",
        "sub_size": 46,
        "sub_color": "#FFFFFF",
        "sub_background": False,
        "resume": True,
        "smooth": True,             # movimento fluido (sync al refresh + anti-judder)
        "refresh_match": True,      # (vecchia impostazione, sostituita da refresh_mode)
        "refresh_mode": "off",        # off | fullscreen | always (off = 200 Hz fissi + movimento fluido)
        "end_action": "stop",       # stop | next
        "volume": 100,
        "subs_with_english_audio": True,   # sottotitoli inglesi anche quando l'audio è già inglese
        "remember_per_film": True,         # ogni film ricorda audio, sottotitoli, ritardo e volume
        "film_colors": True,               # barra e play prendono il colore del film
        "sleep_pc": False,                 # timer spegnimento: sospendi anche il PC
        "rtx_vsr": True,                   # RTX Video Super Resolution sui video ≤720p (solo GPU NVIDIA)
        "theatre_auto": False,
        "loudness": True,                  # volume uniforme tra film (EBU R128)
        "smart_resume": True,              # riprende qualche secondo prima (di più dopo pause lunghe)
        "tv_quality": "auto",              # TV "il PC fa tutto": auto | high | medium | low | slow
        "tv_learned": {},                  # qualità che il Wi-Fi ha retto per ogni TV (si parte da lì)
    },
    "audio": {
        "profile": "auto",          # auto | normal | headphones | dialogue | night | subwoofer | monitor
        "device": "auto",           # uscita audio di mpv ('auto' = quella di Windows)
        "exclusive": False,         # uscita esclusiva: salta il mixer di Windows ed effetti come FxSound
        "devices": {},              # per uscita: {"profile": ..., "delay": secondi}
        "fx_warned": False,
    },
    "library": {
        "tmdb_key": "",             # chiave gratuita TMDB (API Key o Read Access Token)
        "tmdb_lang": "en-US",       # lingua dei titoli TMDB
        "next_episode": True,       # a fine episodio propone il successivo
        "detect_intro": True,       # trova la sigla confrontando due episodi (solo file sul PC)
        "skip_intro_auto": False,   # salta la sigla da solo invece di mostrare il pulsante
    },
    "stream": {
        "turbo": True,              # Stream Turbo: più connessioni, salti rapidi, rinnovo link
        "turbo_connections": 16,
        "cache_mb": 1024,
        "back_cache_mb": 256,
        "readahead_s": 60,
        "cache_secs": 120,
        "max_height": 2160,
        "user_agent": "",
        "proxy": "",
    },
    "downloads": {
        "dir": DEFAULT_DOWNLOAD_DIR,
        "connections": 16,
        "parallel": 3,
        "limit_kb": 0,
        "organize": True,
        "clipboard": True,
        "ytdlp_container": "mkv",
        "tray_on_close": True,
        "player_priority": True,    # mentre guardi da rete, gli altri download rallentano
        "wifi_streaming": True,     # Wi-Fi in modalità streaming (niente scansioni in background) mentre guardi
    },
    "torrent": {
        "port": 6881,
        "dir": DEFAULT_DOWNLOAD_DIR,
        "sequential": False,         # rarest-first = massima velocità; il play attiva il sequenziale
        "seed_mode": "ratio",       # off | ratio | time
        "seed_ratio": 1.0,
        "seed_minutes": 60,
        "down_limit_kb": 0,
        "up_limit_kb": 0,
        "encryption": True,
        "rd_token": "",
    },
    "shortcuts": {
        "play_pause": "Space",
        "seek_fwd": "Right",
        "seek_back": "Left",
        "seek_fwd_big": "Up",
        "seek_back_big": "Down",
        "fullscreen": "F",
        "mute": "M",
        "stats": "I",
        "next_audio": "A",
        "next_sub": "V",
        "speed_up": "]",
        "speed_down": "[",
        "ab_loop": "L",
        "pip": "P",
        "cinema": "C",
        "cam": "T",
        "sub_search": "Ctrl+F",
    },
    "advanced": {
        "mpv_conf": "",
    },
    "meta": {"version": 6},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Settings:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.listeners: list = []
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text("utf-8"))
                self.data = _merge(DEFAULTS, raw)
                ver = raw.get("meta", {}).get("version", 1)
                if self.data["appearance"]["theme"] == "dark":
                    self.data["appearance"]["theme"] = "midnight"
                if ver < 4:
                    # v4: niente screenshot; lingue predefinite Malayalam › Inglese, sottotitoli Inglese
                    self.data["shortcuts"].pop("screenshot", None)
                    self.data["player"].pop("screenshot_dir", None)
                    self.data["meta"]["version"] = 6
                    self.save()
                if ver < 5:
                    # v5: Stream Turbo con 16 connessioni (più margine sui 4K da 70-80 Mbps)
                    if self.data["stream"].get("turbo_connections", 8) <= 8:
                        self.data["stream"]["turbo_connections"] = 16
                    self.data["meta"]["version"] = 6
                    self.save()
                if ver < 6:
                    # v6: niente cambi di refresh (schermo nero): 200 Hz fissi con movimento fluido
                    self.data["player"]["refresh_mode"] = "off"
                    self.data["player"]["smooth"] = True
                    self.data["meta"]["version"] = 6
                    self.save()
                if ver < 2:
                    # v2: rarest-first per la massima velocità torrent, movimento fluido attivo
                    self.data["torrent"]["sequential"] = False
                    self.data["player"]["smooth"] = True
                    self.data["meta"]["version"] = 6
                    self.save()
            except Exception:
                pass

    def get(self, section: str, key: str):
        return self.data[section][key]

    def set(self, section: str, key: str, value, notify=True):
        self.data[section][key] = value
        self.save()
        if notify:
            for cb in list(self.listeners):
                cb(section, key)

    def save(self):
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(SETTINGS_FILE)

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.save()
        for cb in list(self.listeners):
            cb("*", "*")

    def export(self, path: str):
        Path(path).write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")

    def import_(self, path: str):
        self.data = _merge(DEFAULTS, json.loads(Path(path).read_text("utf-8")))
        self.save()
        for cb in list(self.listeners):
            cb("*", "*")


class History:
    """Cronologia di file e link riprodotti, con posizione per la ripresa."""

    def __init__(self):
        self.items: list[dict] = []
        if HISTORY_FILE.exists():
            try:
                self.items = json.loads(HISTORY_FILE.read_text("utf-8"))
            except Exception:
                self.items = []
            # gli episodi dentro gli ZIP non sono più supportati (4.4)
            self.items = [i for i in self.items if not str(i.get("url", "")).startswith("zip+")]
        self.listeners: list = []

    def add(self, url: str, title: str, kind: str, extra: dict | None = None):
        """url = chiave stabile (percorso file, link, o percorso finale del file di un torrent)."""
        import time
        old = next((i for i in self.items if i["url"] == url), None)
        self.items = [i for i in self.items if i["url"] != url]
        item = {"url": url, "title": title, "kind": kind, "time": time.time(),
                "pos": old["pos"] if old else 0, "dur": old["dur"] if old else 0}
        for k in ("state", "tmdb", "poster", "backdrop", "source", "clean", "fid", "fname", "size", "overview",
                  "tmdb_title", "tmdb_year", "manual"):
            if old and k in old:
                item[k] = old[k]
        item.update(extra or {})
        self.items.insert(0, item)
        self.items = self.items[:300]
        self._save()

    def get(self, url: str):
        return next((i for i in self.items if i["url"] == url), None)

    def touch(self):
        """Avvisa chi mostra la cronologia (es. una copertina nuova)."""
        for cb in list(self.listeners):
            cb()

    def update_pos(self, url: str, pos: float, dur: float):
        import time
        for i in self.items:
            if i["url"] == url:
                i["pos"], i["dur"], i["seen"] = pos, dur, time.time()
                break
        self._save(notify=False)

    def update_state(self, url: str, state: dict):
        """Audio, sottotitoli, ritardo e volume scelti per questo film."""
        for i in self.items:
            if i["url"] == url:
                if i.get("state") == state:
                    return
                i["state"] = state
                break
        self._save(notify=False)

    def update_meta(self, url: str, meta: dict, notify=True):
        for i in self.items:
            if i["url"] == url:
                i.update(meta)
                break
        self._save(notify=notify)

    def find(self, **kw):
        return next((i for i in self.items if all(i.get(k) == v for k, v in kw.items())), None)

    def rekey(self, old: str, new: str, keep_new_fields=("url", "time", "kind")):
        """Stesso film con un link nuovo: sposta posizione, scelte, poster e copertina sul nuovo link."""
        o = self.get(old)
        if not o or old == new:
            return None
        n = self.get(new)
        merged = dict(o)
        if n:
            for k in keep_new_fields:
                merged[k] = n[k]
            for k, v in n.items():
                if k not in merged:
                    merged[k] = v
        merged["url"] = new
        self.items = [i for i in self.items if i["url"] not in (old, new)]
        self.items.insert(0, merged)
        try:
            src, dst = cover_path(old), cover_path(new)
            if src.exists():
                src.replace(dst)
        except Exception:
            pass
        self._save()
        return merged

    def set_title(self, url: str, title: str):
        for i in self.items:
            if i["url"] == url and title:
                i["title"] = title
        self._save()

    def remove(self, url: str):
        self.items = [i for i in self.items if i["url"] != url]
        self._save()

    def clear(self):
        self.items = []
        self._save()

    def _save(self, notify=True):
        HISTORY_FILE.write_text(json.dumps(self.items, ensure_ascii=False), "utf-8")
        if notify:
            for cb in list(self.listeners):
                cb()


settings = Settings()
history = History()

VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov", ".webm", ".ts", ".m2ts", ".mts", ".flv", ".wmv",
             ".mpg", ".mpeg", ".m4v", ".ogv", ".3gp", ".vob", ".rmvb"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ac3", ".dts", ".mka"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup", ".idx"}


def human_size(n: float) -> str:
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_speed(n: float) -> str:
    if not n:
        return "0 MB/s"
    return f"{n / 1048576:.2f} MB/s" if n >= 1048576 * 0.1 else f"{n / 1024:.0f} KB/s"


def resume_point(it: dict | None):
    """Da dove riprendere un film (None = dall'inizio). Ripresa intelligente: torna indietro di qualche
    secondo per ritrovare il filo, di più se è passato tanto tempo dall'ultima volta."""
    import time
    if not it or not it.get("dur"):
        return None
    pos, dur = float(it.get("pos") or 0), float(it["dur"])
    if not (10 < pos < dur - 30):
        return None
    if not settings.get("player", "smart_resume"):
        return pos
    gap = time.time() - float(it.get("seen") or it.get("time") or 0)
    back = 3 if gap < 120 else 6 if gap < 3600 else 10 if gap < 86400 else 15 if gap < 7 * 86400 else 25
    return max(0.0, pos - back)


def human_time(s) -> str:
    if s is None or s < 0 or s != s:
        return "--:--"
    s = int(s)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def human_eta(s) -> str:
    if s is None or s < 0 or s == float("inf"):
        return "∞"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"
