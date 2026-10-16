"""Catalogo: titoli puliti, serie/episodi, poster TMDB, link multipli, episodio successivo."""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QTimer

from . import names
from .config import history, settings, VIDEO_EXT
from .tmdb import Tmdb
from .turbo import probe, link_expiry


STATS_FILE = None


def _stats_file():
    from .config import DATA
    return DATA / "stats.json"


def load_stats() -> dict:
    import json
    try:
        return json.loads(_stats_file().read_text("utf-8"))
    except Exception:
        return {"days": {}, "finished": {}}


def add_watch(seconds: float, finished_key: str | None = None):
    """Statistiche: secondi guardati per giorno e film finiti (per mese)."""
    import json
    st = load_stats()
    day = time.strftime("%Y-%m-%d")
    st.setdefault("days", {})[day] = round(st["days"].get(day, 0) + seconds, 1)
    if finished_key:
        st.setdefault("finished", {}).setdefault(time.strftime("%Y-%m"), [])
        lst = st["finished"][time.strftime("%Y-%m")]
        if finished_key not in lst:
            lst.append(finished_key)
    try:
        _stats_file().write_text(json.dumps(st), "utf-8")
    except OSError:
        pass


def month_summary() -> str:
    st = load_stats()
    m = time.strftime("%Y-%m")
    secs = sum(v for k, v in st.get("days", {}).items() if k.startswith(m))
    fin = len(st.get("finished", {}).get(m, []))
    if secs < 60:
        return ""
    h = secs / 3600
    t = f"{h:.0f} hours" if h >= 1.5 else f"{secs / 60:.0f} minutes"
    return f"This month: {t} watched" + (f" · {fin} {'movie finished' if fin == 1 else 'movies finished'}" if fin else "")


def item_title(it: dict) -> str:
    return it.get("clean") or it.get("title") or ""


def is_expired(it: dict) -> bool:
    if it.get("kind") != "link":
        return False
    if it.get("dead"):
        return True
    exp = link_expiry(it.get("url", ""))
    return bool(exp and exp < time.time())


class Catalog(QObject):
    links_added = Signal(int, int)          # aggiunti, già presenti/rinnovati
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.tmdb = Tmdb()
        self.tmdb.found.connect(self._found)
        self.tmdb.failed.connect(self._failed)
        self._last_key = settings.get("library", "tmdb_key")
        history.listeners.insert(0, self._scan)
        settings.listeners.append(self._setting)
        QTimer.singleShot(1200, self._scan)

    # ---------- titoli e poster ----------
    def _source_name(self, it) -> str:
        """Il nome più informativo: file con estensione video, altrimenti il titolo (es. quello dentro all'MKV)."""
        fname = it.get("fname") or ""
        if not fname and it.get("kind") != "link":
            fname = Path(it["url"]).name
        if not fname:
            fname = names.name_from_url(it["url"])
        title = it.get("title") or ""
        good_file = bool(names.VIDEO_SUFFIX.search(fname)) and not re.fullmatch(r"[0-9a-f]{16,}\.\w+", fname, re.I)
        if good_file:
            return fname
        if title and not title.startswith(("http://", "https://")) and title not in ("Loading…",) \
                and not re.fullmatch(r"[0-9a-f]{16,}", title, re.I):
            return title
        return fname if not re.fullmatch(r"[0-9a-f]{16,}", fname, re.I) else ""

    def _scan(self):
        if getattr(self, "_scanning", False):
            return
        self._scanning = True
        try:
            self._scan_inner()
        finally:
            self._scanning = False

    def _scan_inner(self):
        dirty = False
        for it in history.items[:300]:
            src = self._source_name(it)
            if it.get("parsed") != src:
                info = names.parse(src) if src else {}
                it["parsed"] = src
                if info.get("title"):
                    if not it.get("manual"):
                        it["clean"] = names.display(info)
                    it["year"] = info.get("year")
                    it["mkind"] = info.get("kind")
                    it["season"], it["episode"] = info.get("season"), info.get("episode")
                    it["show"] = names.show_key(info) if info.get("kind") == "tv" else ""
                    it["res"] = info.get("res")
                    it["langs"] = info.get("langs") or []
                    it["theatre"] = info.get("theatre", False)
                    it["line_audio"] = info.get("line_audio", False)
                    it["ptitle"] = info["title"]
                dirty = True
            if (self.tmdb.enabled() and it.get("ptitle") and not it.get("tmdb") and not it.get("tmdb_fail")):
                self.tmdb.lookup(it["url"], it["ptitle"], it.get("year"), it.get("mkind") or "movie")
        if dirty:
            history._save(notify=True)      # Home e Libreria mostrano subito i titoli puliti

    def _found(self, key, d):
        it = history.get(key)
        if not it:
            return
        meta = {"tmdb": d.get("id"), "poster": d.get("poster_file"), "backdrop": d.get("backdrop_file"),
                "overview": d.get("overview", ""), "tmdb_title": d.get("title"), "tmdb_year": d.get("year"),
                "tmdb_kind": d.get("kind")}
        if not it.get("manual") or d.get("_manual"):
            t = d.get("title") or it.get("ptitle")
            if it.get("mkind") == "tv" and it.get("episode") is not None:
                meta["clean"] = f"{t} · S{it.get('season') or 1:02d}E{it['episode']:02d}"
            else:
                y = d.get("year") or it.get("year")
                meta["clean"] = f"{t} ({y})" if y else t
        if d.get("_manual"):
            meta["manual"] = True
        history.update_meta(key, meta)

    def _failed(self, key, msg):
        if msg == "non trovato":
            history.update_meta(key, {"tmdb_fail": True}, notify=False)

    def _setting(self, sec, key):
        if sec == "library" and key == "tmdb_lang":
            for it in history.items:
                if not it.get("manual"):
                    for k in ("tmdb", "tmdb_fail", "parsed"):
                        it.pop(k, None)
            self._scan()
        if sec == "library" and key == "tmdb_key":
            new = settings.get("library", "tmdb_key")
            if new != self._last_key:
                self._last_key = new
                for it in history.items:
                    it.pop("tmdb_fail", None)
                self._scan()

    def choose(self, key: str, result: dict):
        r = dict(result)
        r["_manual"] = True
        self.tmdb.choose(key, r)

    def set_title(self, key: str, text: str):
        history.update_meta(key, {"clean": text.strip(), "manual": True})

    # ---------- link multipli ----------
    def add_links(self, text: str):
        """Aggiunge alla libreria tanti link insieme (uno per riga). Riconosce lo stesso film con un link nuovo."""
        urls = [u.strip() for u in re.split(r"[\s,]+", text) if u.strip().startswith(("http://", "https://"))]
        urls = list(dict.fromkeys(urls))
        if not urls:
            self.links_added.emit(0, 0)
            return
        ua = settings.get("stream", "user_agent") or ""

        def work():
            res = []
            for u in urls:
                info = probe(u, ua) if ua else probe(u)
                res.append((u, info))
            QTimer.singleShot(0, self, lambda: self._links_probed(res))
        threading.Thread(target=work, daemon=True).start()

    def _links_probed(self, res):
        added = renewed = 0
        for u, info in reversed(res):
            name = (info.get("name") if info.get("ok") else "") or names.name_from_url(u)
            size = info.get("size") or 0
            fid = f"{name}|{size}" if name and size else ""
            old = history.find(fid=fid) if fid else None
            if old and old["url"] != u:
                history.rekey(old["url"], u)
                history.update_meta(u, {"dead": False}, notify=False)
                renewed += 1
                continue
            if history.get(u):
                continue
            history.add(u, name or u, "link", {"fid": fid, "fname": name, "size": size,
                                               "dead": bool(info.get("expired"))})
            added += 1
        self.links_added.emit(added, renewed)

    @staticmethod
    def sibling_episode(path: str) -> str | None:
        """Un altro episodio della stessa serie nella stessa cartella (per trovare la sigla in comune)."""
        info = names.parse(Path(path).name)
        if info.get("kind") != "tv" or info.get("episode") is None:
            return None
        show, s, e = names.show_key(info), info.get("season") or 1, info["episode"]
        best = None
        try:
            for f in Path(path).parent.iterdir():
                if f.suffix.lower() not in VIDEO_EXT or str(f) == path:
                    continue
                i = names.parse(f.name)
                if names.show_key(i) != show or i.get("episode") is None:
                    continue
                d = abs((i.get("season") or 1) - s) * 100 + abs(i["episode"] - e)
                if best is None or d < best[0]:
                    best = (d, str(f))
        except OSError:
            return None
        return best[1] if best else None

    # ---------- episodio successivo ----------
    def next_episode(self, key: str):
        """(target, titolo) del prossimo episodio, cercando nella stessa cartella e nella libreria."""
        it = history.get(key)
        src = (it and (it.get("fname") or it.get("parsed"))) or Path(key).name
        info = names.parse(src)
        if info.get("kind") != "tv" or info.get("episode") is None:
            return None
        show, s, e = names.show_key(info), info.get("season") or 1, info["episode"]
        want = [(s, e + 1), (s + 1, 1)]
        cands = []
        if os.path.isfile(key):
            folder = Path(key).parent
            try:
                for f in folder.iterdir():
                    if f.suffix.lower() in VIDEO_EXT:
                        i = names.parse(f.name)
                        if names.show_key(i) == show and i.get("episode") is not None:
                            cands.append(((i.get("season") or 1, i["episode"]), str(f), names.display(i)))
            except OSError:
                pass
        for h in history.items:
            if h.get("show") == show and h.get("episode") is not None and h["url"] != key and not is_expired(h):
                cands.append(((h.get("season") or 1, h["episode"]), h["url"], item_title(h)))
        for w in want:
            for se, target, title in cands:
                if se == w:
                    return target, title
        return None
