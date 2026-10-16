"""TMDB: poster ufficiali e titoli puliti "Nome (anno)" per film e serie (chiave gratuita dell'utente)."""
from __future__ import annotations

import json
import queue
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

from .config import DATA, settings

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"
POSTERS = DATA / "posters"
POSTERS.mkdir(exist_ok=True)
CACHE_FILE = DATA / "tmdb_cache.json"
SSL_CTX = ssl.create_default_context()


def _key() -> str:
    return (settings.get("library", "tmdb_key") or "").strip()


def _get(path: str, params: dict, key: str | None = None, timeout=12) -> dict:
    key = key if key is not None else _key()
    params = dict(params)
    headers = {"Accept": "application/json", "User-Agent": "NOVA"}
    if key.startswith("eyJ"):            # "API Read Access Token" (v4)
        headers["Authorization"] = f"Bearer {key}"
    else:                                # "API Key" (v3)
        params["api_key"] = key
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout,
                                context=SSL_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def check_key(key: str) -> tuple[bool, str]:
    try:
        _get("/configuration", {}, key=key.strip())
        return True, "Chiave valida: i poster verranno scaricati da soli."
    except urllib.error.HTTPError as e:
        return False, "Chiave non valida." if e.code == 401 else f"Errore TMDB ({e.code})."
    except Exception as e:
        return False, f"TMDB non raggiungibile: {e}"


def search(title: str, year: int | None, kind: str) -> list[dict]:
    """Risultati TMDB (film o serie), i più probabili per primi."""
    lang = settings.get("library", "tmdb_lang") or "en-US"
    path = "/search/tv" if kind == "tv" else "/search/movie"
    params = {"query": title, "language": lang, "include_adult": "false"}
    if year:
        params["first_air_date_year" if kind == "tv" else "year"] = year
    res = _get(path, params).get("results", [])
    if not res and year:
        params.pop("year", None)
        params.pop("first_air_date_year", None)
        res = _get(path, params).get("results", [])
    if not res and kind != "tv":      # a volte una "serie" è un film e viceversa
        res = _get("/search/tv", {"query": title, "language": lang}).get("results", [])
    out = []
    for r in res[:8]:
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append({"id": r["id"], "kind": "tv" if "first_air_date" in r or "name" in r else "movie",
                    "title": r.get("title") or r.get("name") or "",
                    "original": r.get("original_title") or r.get("original_name") or "",
                    "year": int(date[:4]) if date[:4].isdigit() else None,
                    "poster": r.get("poster_path"), "backdrop": r.get("backdrop_path"),
                    "overview": r.get("overview") or "", "vote": r.get("vote_average") or 0})
    if year:
        out.sort(key=lambda r: r["year"] != year)     # stesso anno prima, poi l'ordine di TMDB
    return out


def fetch_image(path: str, size="w342") -> str | None:
    if not path:
        return None
    dest = POSTERS / f"{size}_{path.strip('/').replace('/', '_')}"
    if dest.exists() and dest.stat().st_size > 1000:
        return str(dest)
    try:
        with urllib.request.urlopen(IMG + size + path, timeout=15, context=SSL_CTX) as r:
            data = r.read()
        dest.write_bytes(data)
        return str(dest)
    except Exception:
        return None


class Tmdb(QObject):
    """Coda in background: per ogni elemento trova il film/serie, scarica il poster e risponde con 'found'."""
    found = Signal(str, dict)      # chiave cronologia, dati
    failed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.q: queue.Queue = queue.Queue()
        self.pending: set[str] = set()
        try:
            self.cache = json.loads(CACHE_FILE.read_text("utf-8"))
        except Exception:
            self.cache = {}
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def enabled(self) -> bool:
        return bool(_key())

    def lookup(self, key: str, title: str, year, kind: str):
        if not self.enabled() or not title or key in self.pending:
            return
        self.pending.add(key)
        self.q.put((key, title, year, kind, None))

    def choose(self, key: str, result: dict):
        """Scelta manuale da 'Correggi titolo'."""
        self.q.put((key, None, None, None, result))

    def _save_cache(self):
        with self._lock:
            tmp = CACHE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cache, ensure_ascii=False), "utf-8")
            tmp.replace(CACHE_FILE)

    def _loop(self):
        while True:
            key, title, year, kind, chosen = self.q.get()
            try:
                if chosen:
                    best = chosen
                else:
                    ck = f"{kind}|{title.lower()}|{year or ''}|{settings.get('library', 'tmdb_lang')}"
                    best = self.cache.get(ck)
                    if best is None:
                        res = search(title, year, kind)
                        best = res[0] if res else {}
                        self.cache[ck] = best
                        self._save_cache()
                if not best:
                    self.failed.emit(key, "non trovato")
                    continue
                data = dict(best)
                data["poster_file"] = fetch_image(best.get("poster"), "w342")
                data["backdrop_file"] = fetch_image(best.get("backdrop"), "w780")
                self.found.emit(key, data)
            except Exception as e:
                self.failed.emit(key, str(e))
            finally:
                self.pending.discard(key)


# ---------------------------------------------------------------- scheda completa (stile OTT)
DETAILS = DATA / "tmdb_details"
DETAILS.mkdir(exist_ok=True)


def details(kind: str, tmdb_id: int, force: bool = False) -> dict:
    """Generi, durata, voto, età consigliata, slogan, cast con foto, regia, trailer, logo del titolo e sfondo
    in alta risoluzione. Scaricata una volta e tenuta su disco (immagini comprese)."""
    kind = "tv" if kind == "tv" else "movie"
    lang = settings.get("library", "tmdb_lang") or "en-US"
    f = DETAILS / f"{kind}_{tmdb_id}_{lang}.json"
    if f.exists() and not force:
        try:
            return json.loads(f.read_text("utf-8"))
        except Exception:
            pass
    extra = "credits,videos,images," + ("content_ratings" if kind == "tv" else "release_dates")
    d = _get(f"/{kind}/{tmdb_id}", {"language": lang, "append_to_response": extra,
                                    "include_image_language": f"{lang[:2]},en,null",
                                    "include_video_language": f"{lang[:2]},en,null"})
    out = {"id": tmdb_id, "kind": kind,
           "title": d.get("title") or d.get("name") or "",
           "original": d.get("original_title") or d.get("original_name") or "",
           "tagline": d.get("tagline") or "",
           "overview": d.get("overview") or "",
           "genres": [g["name"] for g in d.get("genres", [])][:4],
           "vote": round(float(d.get("vote_average") or 0), 1),
           "votes": int(d.get("vote_count") or 0),
           "runtime": int(d.get("runtime") or (d.get("episode_run_time") or [0] or [0])[0] or 0),
           "year": (d.get("release_date") or d.get("first_air_date") or "")[:4],
           "lang": d.get("original_language") or "",
           "seasons": d.get("number_of_seasons"), "episodes": d.get("number_of_episodes"),
           "status": d.get("status") or ""}
    # età consigliata (Italia, poi India, poi USA)
    cert = ""
    if kind == "movie":
        rd = {r["iso_3166_1"]: r for r in d.get("release_dates", {}).get("results", [])}
        for c in ("IT", "IN", "US", "GB"):
            for x in (rd.get(c) or {}).get("release_dates", []):
                if x.get("certification"):
                    cert = x["certification"]
                    break
            if cert:
                break
    else:
        cr = {r["iso_3166_1"]: r.get("rating") for r in d.get("content_ratings", {}).get("results", [])}
        cert = next((cr[c] for c in ("IT", "IN", "US", "GB") if cr.get(c)), "")
    out["cert"] = cert
    cr = d.get("credits", {})
    out["cast"] = [{"name": c.get("name", ""), "role": c.get("character", ""), "photo": c.get("profile_path")}
                   for c in cr.get("cast", [])[:12]]
    crew = cr.get("crew", [])
    out["director"] = ", ".join(c["name"] for c in crew if c.get("job") == "Director")[:80] or \
        ", ".join(c.get("name", "") for c in d.get("created_by", []))[:80]
    out["music"] = ", ".join(c["name"] for c in crew if c.get("job") in ("Original Music Composer", "Music"))[:60]
    vids = [v for v in d.get("videos", {}).get("results", []) if v.get("site") == "YouTube"]
    vids.sort(key=lambda v: (v.get("type") != "Trailer", not v.get("official"), v.get("iso_639_1") != lang[:2]))
    out["trailer"] = vids[0]["key"] if vids else ""
    imgs = d.get("images", {})
    logos = sorted(imgs.get("logos", []), key=lambda x: (x.get("iso_639_1") not in (lang[:2], "en"),
                                                         -(x.get("vote_average") or 0)))
    out["logo_file"] = fetch_image(logos[0]["file_path"], "w500") if logos else None
    bd = d.get("backdrop_path") or (imgs.get("backdrops") or [{}])[0].get("file_path")
    out["backdrop_file"] = fetch_image(bd, "w1280") if bd else None
    out["poster_file"] = fetch_image(d.get("poster_path"), "w342") if d.get("poster_path") else None
    for c in out["cast"][:10]:
        c["photo_file"] = fetch_image(c["photo"], "w185") if c.get("photo") else None
    try:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), "utf-8")
        tmp.replace(f)
    except OSError:
        pass
    _MEM[str(f)] = out
    return out


_MEM: dict = {}


def cached_details(kind: str, tmdb_id) -> dict | None:
    """Scheda già scaricata (tenuta in memoria: nessuna lettura dal disco mentre si disegna)."""
    if not tmdb_id:
        return None
    lang = settings.get("library", "tmdb_lang") or "en-US"
    f = DETAILS / f"{'tv' if kind == 'tv' else 'movie'}_{tmdb_id}_{lang}.json"
    k = str(f)
    if k in _MEM:
        return _MEM[k]
    try:
        d = json.loads(f.read_text("utf-8"))
    except Exception:
        d = None
    if d is not None:
        _MEM[k] = d
    return d


class DetailsLoader(QObject):
    """Scarica le schede in background, una per volta (non pesa mai sul player)."""
    ready = Signal(str, dict)          # chiave cronologia, scheda

    def __init__(self):
        super().__init__()
        self.q: queue.Queue = queue.Queue()
        self.busy: set = set()
        threading.Thread(target=self._loop, daemon=True).start()

    def want(self, key: str, kind: str, tmdb_id):
        if not tmdb_id or not _key() or (kind, tmdb_id) in self.busy:
            return
        self.busy.add((kind, tmdb_id))
        self.q.put((key, kind, tmdb_id))

    def _loop(self):
        while True:
            key, kind, tid = self.q.get()
            try:
                d = details(kind, tid)
                self.ready.emit(key, d)
            except Exception:
                pass
            finally:
                self.busy.discard((kind, tid))


_LOADER = None


def loader() -> DetailsLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = DetailsLoader()
    return _LOADER
