"""Nomi dei file → titolo pulito, anno, stagione/episodio e dettagli tecnici.

Funziona con i nomi delle release (Hollywood e indiane):
  "Spider-Man: Brand New Day (2026) IMAX 2160p BCORE WEB-DL DV HDR 10bit HEVC [Hindi-Tamil] x265.mkv"
  "www.example.com - Some Movie (2024) Malayalam 1080p WEB-DL x264 AAC ESub.mkv"
  "The.Boys.S04E03.1080p.WEB.h264-ETHEL.mkv"
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

VIDEO_SUFFIX = re.compile(r"\.(mkv|mp4|avi|mov|webm|ts|m2ts|m4v|wmv|flv|mpg|mpeg)$", re.I)
SITE_PREFIX = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*(?:(?:www\.)?[a-z0-9-]+\.(?:[a-z]{2,6})(?:\.[a-z]{2,4})?\s*[-–_:|]+\s*)+",
                         re.I)
BRACKETS = re.compile(r"[\[\{][^\]\}]*[\]\}]")
YEAR = re.compile(r"[\(\[\s._-]((?:19[2-9]\d|20[0-4]\d))(?=[\)\]\s._-]|$)")
SXXEYY = re.compile(r"(?i)\bS(\d{1,2})[ ._-]?E(\d{1,3})(?:[ ._-]?E?(\d{1,3}))?\b")
NXNN = re.compile(r"(?i)\b(\d{1,2})x(\d{2,3})\b")
EPISODE_WORD = re.compile(r"(?i)\b(?:ep(?:isode|isodio)?|e)[ ._-]?(\d{1,3})\b")
SEASON_WORD = re.compile(r"(?i)\b(?:season|stagione|s)[ ._-]?(\d{1,2})\b")
RES = re.compile(r"(?i)\b(4320p|2160p|1440p|1080p|1080i|720p|576p|480p|360p|4k|uhd)\b")
CUT_WORDS = [
    r"2160p", r"1080p", r"1080i", r"720p", r"480p", r"576p", r"4k", r"uhd", r"imax", r"hdr10\+?", r"hdr", r"dv",
    r"dovi", r"dolby\s*vision", r"web[ ._-]?dl", r"web[ ._-]?rip", r"webrip", r"web", r"blu[ ._-]?ray", r"bdrip",
    r"brrip", r"remux", r"hdrip", r"dvdrip", r"hdtv", r"hdtc", r"hdcam", r"camrip", r"cam", r"tc", r"hq", r"pre[ ._-]?dvd",
    r"predvd", r"x26[45]", r"h[ ._]?26[45]", r"hevc", r"avc", r"av1", r"10[ ._-]?bit", r"8[ ._-]?bit", r"aac",
    r"ac3", r"e?ac3", r"ddp?\s*\d\.\d", r"ddpa", r"dd\+?", r"atmos", r"truehd", r"dts(?:-?hd)?", r"ma", r"esubs?",
    r"subs?", r"multi", r"dual", r"proper", r"repack", r"extended", r"uncut", r"unrated", r"director'?s\s*cut",
    r"amzn", r"nf", r"dsnp", r"hs", r"zee5", r"sonyliv", r"jio(?:cinema|hotstar)?", r"hotstar", r"sunnxt", r"aha",
    r"true", r"org", r"original", r"line", r"audio", r"bcore", r"part\s*\d+",
    r"malayalam", r"tamil", r"telugu", r"hindi", r"kannada", r"bengali", r"marathi", r"english", r"italian",
    r"ita", r"eng", r"mal", r"tam", r"tel", r"hin", r"\d+(?:\.\d+)?\s*(?:gb|mb)", r"\d+kbps",
]
CUT = re.compile(r"(?i)(?:^|[ ._\-\(\[])(?:" + "|".join(CUT_WORDS) + r")(?=$|[ ._\-\)\]])")
LANGS = {"malayalam": "Malayalam", "mal": "Malayalam", "tamil": "Tamil", "tam": "Tamil", "telugu": "Telugu",
         "tel": "Telugu", "hindi": "Hindi", "hin": "Hindi", "kannada": "Kannada", "english": "English",
         "eng": "English", "italian": "Italian", "ita": "Italian", "bengali": "Bengali", "marathi": "Marathi"}
THEATRE = re.compile(r"(?i)\b(hdcam|hq[ ._-]?cam|camrip|cam|hdtc|tc|telesync|telecine|hdts|ts|ts[ ._-]?rip|"
                     r"hq[ ._-]?pre[ ._-]?dvd|pre[ ._-]?dvd|predvd|pdvd|s[ ._-]?print|hq[ ._-]?s[ ._-]?print)\b")


LINE_AUDIO = re.compile(r"(?i)(line|org|original|true|clean|studio)[ ._-]*(aud(io)?|sound)|\bline\b")


def name_from_url(url: str) -> str:
    """Nome del file da un link (o '' se il link non lo contiene, es. Cloudflare R2 firmati)."""
    try:
        u = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(u.query)
        for k in ("filename", "file", "name", "response-content-disposition"):
            if k in q:
                v = q[k][0]
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', v)
                return urllib.parse.unquote(m.group(1) if m else v)
        name = urllib.parse.unquote(Path(u.path).name)
        return name if VIDEO_SUFFIX.search(name) else ""
    except Exception:
        return ""


def _tidy(s: str) -> str:
    s = re.sub(r"[._]+", " ", s)
    s = re.sub(r"\s*[-–|]+\s*$", "", s)
    s = re.sub(r"^\s*[-–|:]+\s*", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -–_.([")
    return s


def parse(raw: str) -> dict:
    """{'title', 'year', 'season', 'episode', 'res', 'langs', 'theatre', 'kind': 'movie'|'tv'}"""
    name = Path(raw).name if ("/" in raw or "\\" in raw) else raw
    name = VIDEO_SUFFIX.sub("", name)
    name = SITE_PREFIX.sub("", name)
    out = {"title": "", "year": None, "season": None, "episode": None, "res": None, "langs": [],
           "theatre": False, "line_audio": bool(LINE_AUDIO.search(name)), "kind": "movie"}
    low = name.lower()
    for k, v in LANGS.items():
        if re.search(rf"(?<![a-z]){k}(?![a-z])", low) and v not in out["langs"]:
            out["langs"].append(v)
    m = RES.search(name)
    if m:
        r = m.group(1).lower()
        out["res"] = "2160p" if r in ("4k", "uhd") else r
    cut = len(name)
    m = SXXEYY.search(name) or NXNN.search(name)
    if m:
        out["season"], out["episode"], out["kind"] = int(m.group(1)), int(m.group(2)), "tv"
        cut = min(cut, m.start())
    else:
        m = re.search(r"(?i)\b(?:season|stagione)[ ._-]?(\d{1,2})\b.*?\b(?:ep(?:isode|isodio)?)[ ._-]?(\d{1,3})\b", name)
        if m:
            out["season"], out["episode"], out["kind"] = int(m.group(1)), int(m.group(2)), "tv"
            cut = min(cut, m.start())
    years = [y for y in YEAR.finditer(" " + name + " ") if y.start() > 1 and y.start() - 1 < cut]
    if years:
        y = years[-1]          # "Blade Runner 2049 2017" → l'anno è l'ultimo
        out["year"] = int(y.group(1))
        cut = min(cut, max(0, y.start() - 1))
    m = CUT.search(name)
    if m and m.start() > 0:
        cut = min(cut, m.start())
    title = name[:cut]
    title = BRACKETS.sub(" ", title)
    title = _tidy(title)
    if not title:   # nome tutto "tecnico": tieni il pezzo prima del primo blocco
        title = _tidy(BRACKETS.sub(" ", name).split(" - ")[0])
    # Title Case solo se il nome era tutto minuscolo o con i punti
    if title and (title.islower() or "." in raw.split("/")[-1][:len(title) + 2]):
        title = " ".join(w if w.isupper() and len(w) <= 4 else w[:1].upper() + w[1:] for w in title.split())
    out["title"] = title
    return out


def display(info: dict) -> str:
    """'Titolo (anno)' per i film, 'Serie · S01E02' per le serie."""
    t = info.get("title") or ""
    if info.get("kind") == "tv" and info.get("episode") is not None:
        return f"{t} · S{info['season'] or 1:02d}E{info['episode']:02d}"
    return f"{t} ({info['year']})" if info.get("year") else t


def show_key(info: dict) -> str:
    """Chiave per raggruppare gli episodi della stessa serie."""
    return re.sub(r"[^a-z0-9]", "", (info.get("title") or "").lower())
