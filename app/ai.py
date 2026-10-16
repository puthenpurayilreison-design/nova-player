"""Funzioni "intelligenti" di NOVA, tutte in locale sul PC (niente servizi online):

- Sincronizzazione automatica dei sottotitoli: confronta quando si parla nel film con quando compaiono le frasi.
- Salta intro: trova la sigla uguale tra due episodi della stessa serie (impronta audio), o usa i capitoli.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .config import DATA, tool

NOWIN = 0x08000000 if sys.platform == "win32" else 0
LOWPRIO = 0x00004000 if sys.platform == "win32" else 0      # BELOW_NORMAL: non toglie risorse al film
SUBS_DIR = DATA / "subs"


class Cancelled(Exception):
    pass


def _run(cmd, timeout=None, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, errors="ignore", timeout=timeout,
                          creationflags=NOWIN | LOWPRIO, **kw)


# ---------------------------------------------------------------- utilità audio
def probe_audio(src: str) -> list[dict]:
    out = _run([tool("ffprobe"), "-v", "quiet", "-print_format", "json", "-show_streams", "-select_streams", "a",
                src], timeout=60).stdout
    import json
    try:
        return json.loads(out or "{}").get("streams", [])
    except ValueError:
        return []


def voice_filter(stream: dict | None) -> str:
    """Per i multicanale tiene solo il canale centrale, dove stanno i dialoghi."""
    lay = (stream or {}).get("channel_layout", "") or ""
    ch = int((stream or {}).get("channels") or 2)
    if ch >= 3 and ("5.1" in lay or "7.1" in lay or "3.0" in lay or "3.1" in lay or ch in (6, 8)):
        return "pan=mono|c0=FC"
    return "aresample=async=0"


def _parse_time(s: str) -> float:
    s = s.strip().replace(",", ".")
    h, m, sec = s.split(":")
    return int(h) * 3600 + int(m) * 60 + float(sec)


def _fmt_time(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def read_srt(path: str) -> list[tuple[float, float, str]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    out = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        m = re.search(r"(\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d{1,3})", block)
        if not m:
            continue
        body = block[m.end():].strip("\r\n")
        out.append((_parse_time(m.group(1)), _parse_time(m.group(2)), body))
    return out


def write_srt(path: str, cues):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(cues, 1):
            f.write(f"{i}\n{_fmt_time(a)} --> {_fmt_time(b)}\n{t}\n\n")


def subs_dir_for(src: str) -> Path:
    if os.path.isfile(src):
        d = Path(src).parent
        if os.access(d, os.W_OK):
            return d
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    return SUBS_DIR


# ---------------------------------------------------------------- sincronizzazione sottotitoli
STEP = 0.02           # risoluzione 20 ms


def speech_intervals(src, audio_index, start, length, cancel=lambda: False) -> list[tuple[float, float]]:
    """Quando si parla (relativo a 'start'): energia della banda delle voci ogni 50 ms, soglia adattiva."""
    streams = probe_audio(src)
    st = streams[audio_index] if 0 <= audio_index < len(streams) else (streams[0] if streams else None)
    af = (voice_filter(st) + ",aresample=16000,highpass=f=300,lowpass=f=3400,asetnsamples=n=800:p=0,"
          "astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
          "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-")
    cmd = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", src,
           "-map", f"0:a:{audio_index}", "-af", af, "-f", "null", "-"]
    r = _run(cmd, timeout=1800)
    if cancel():
        raise Cancelled()
    rows = []
    for m in re.finditer(r"pts_time:([\d.]+)[^\n]*\n[^\n]*RMS_level=(-?inf|nan|-?[\d.]+)", r.stdout):
        v = m.group(2)
        rows.append((float(m.group(1)), -120.0 if v in ("-inf", "inf", "nan") else float(v)))
    if len(rows) < 100:
        return []
    vals = sorted(v for _, v in rows)
    lo, hi = vals[int(len(vals) * 0.2)], vals[int(len(vals) * 0.95)]
    thr = lo + 0.45 * (hi - lo)
    # isteresi + chiusura dei buchi brevi (le pause tra parole)
    out, cur, last_on = [], None, -9.0
    for t, v in rows:
        if v >= thr:
            if cur is None:
                cur = t if t - last_on > 0.25 else (out.pop()[0] if out and t - out[-1][1] <= 0.25 else t)
            last_on = t + 0.05
        elif cur is not None and t - last_on > 0.15:
            if last_on - cur >= 0.2:
                out.append((cur, last_on))
            cur = None
    if cur is not None:
        out.append((cur, last_on))
    return out


def _mask(intervals, length) -> int:
    n = int(length / STEP) + 1
    bits = bytearray(n)
    for a, b in intervals:
        i, j = max(0, int(a / STEP)), min(n, int(b / STEP))
        if j > i:
            bits[i:j] = b"\x01" * (j - i)
    # bit i = campione i (stringa rovesciata: il primo campione è il bit meno significativo)
    return int(bytes(bits).translate(_BITS).decode()[::-1], 2) if n else 0


_BITS = bytes.maketrans(b"\x00\x01", b"01")


def best_offset(speech, cues, start, length, max_shift=120.0, ratios=(1.0,)):
    """(offset in secondi da aggiungere ai sottotitoli, rapporto di velocità, affidabilità 0-1)."""
    a = _mask(speech, length)
    a_cnt = a.bit_count() or 1
    best = (0.0, 1.0, 0, 0)
    for ratio in ratios:
        iv = [(c0 * ratio - start, c1 * ratio - start) for c0, c1, _ in cues]
        iv = [(x, y) for x, y in iv if y > -max_shift and x < length + max_shift]
        if not iv:
            continue
        pad = int(max_shift / STEP)
        b = _mask([(x + max_shift, y + max_shift) for x, y in iv], length + 2 * max_shift)
        # sub spostati di s secondi → bit (t + max_shift - s)
        coarse_best, cb = None, -1
        for k in range(0, 2 * pad + 1, 25):                # passo 0,5 s
            ov = (a & (b >> k)).bit_count()
            if ov > cb:
                cb, coarse_best = ov, k
        lo, hi = max(0, coarse_best - 30), min(2 * pad, coarse_best + 30)
        fine_best, fb = coarse_best, -1
        for k in range(lo, hi + 1):
            ov = (a & (b >> k)).bit_count()
            if ov > fb:
                fb, fine_best = ov, k
        zero = (a & (b >> pad)).bit_count()
        if fb > best[2]:
            best = (max_shift - fine_best * STEP, ratio, fb, zero)
    off, ratio, ov, zero = best
    conf = ov / a_cnt
    return off, ratio, conf, zero / a_cnt


def sync_subtitles(src, audio_index, sub_path, local=True, at=0.0, cancel=lambda: False):
    """Restituisce (offset, rapporto, affidabilità, affidabilità_prima). Rapporto≠1 = sottotitoli per un altro fps."""
    cues = read_srt(sub_path)
    if len(cues) < 10:
        raise RuntimeError("too few lines in the subtitles")
    if local:
        start, length = 0.0, min(1800.0, max(300.0, cues[-1][1] + 60))
        ratios = (1.0, 25 / 23.976, 23.976 / 25, 25 / 24, 24 / 25)
    else:                                   # link: solo 6 minuti intorno a dove sei, per non scaricare tutto
        start, length = max(0.0, at - 60), 360.0
        ratios = (1.0,)
    speech = speech_intervals(src, audio_index, start, length, cancel)
    if sum(b - a for a, b in speech) < 20:
        raise RuntimeError("no speech heard in the analysed part")
    return best_offset(speech, cues, start, length, ratios=ratios)


def extract_text_sub(src, sub_index, dest) -> str:
    r = _run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", src, "-map", f"0:s:{sub_index}",
              "-f", "srt", str(dest)], timeout=600)
    if r.returncode != 0 or not Path(dest).exists():
        raise RuntimeError("these subtitles are images (PGS/VobSub): they can't be synced")
    return str(dest)


def convert_sub(path, dest) -> str:
    """ASS/VTT → SRT per l'analisi."""
    if path.lower().endswith(".srt"):
        return path
    r = _run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-i", path, str(dest)], timeout=120)
    if r.returncode != 0:
        raise RuntimeError("unsupported subtitle format")
    return str(dest)


# ---------------------------------------------------------------- salta intro
BANDS = [(150, 300), (300, 500), (500, 800), (800, 1250), (1250, 1900), (1900, 2800), (2800, 4000)]
FRAME = 0.1


def fingerprint(src: str, seconds=480.0) -> list[int]:
    """Impronta audio dei primi minuti: 1 codice da 6 bit ogni 0,1 s (come Shazam, in piccolo)."""
    import tempfile
    n = len(BANDS)
    tmp = Path(tempfile.mkdtemp(prefix="nova_fp_"))
    try:
        parts = ["[0:a:0]aresample=8000,pan=mono|c0=0.5*c0+0.5*c1,asplit=%d" % n + "".join(f"[s{i}]" for i in range(n))]
        for i, (lo, hi) in enumerate(BANDS):
            parts.append(f"[s{i}]highpass=f={lo},lowpass=f={hi},asetnsamples=n=800:p=0,"
                         f"astats=metadata=1:reset=1:measure_perchannel=none:measure_overall=RMS_level,"
                         f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=b{i}.txt[o{i}]")
        parts.append("".join(f"[o{i}]" for i in range(n)) + f"amix=inputs={n}[out]")
        cmd = [tool("ffmpeg"), "-hide_banner", "-v", "error", "-t", f"{seconds:.0f}", "-i", os.path.abspath(src)
               if os.path.exists(src) else src, "-filter_complex", ";".join(parts), "-map", "[out]", "-f", "null", "-"]
        _run(cmd, timeout=900, cwd=str(tmp))
        bands = []
        for i in range(n):
            try:
                txt = (tmp / f"b{i}.txt").read_text(errors="ignore")
            except OSError:
                return []
            vals = re.findall(r"RMS_level=(-?inf|nan|-?[\d.]+)", txt)
            bands.append([-120.0 if v in ("-inf", "inf", "nan") else float(v) for v in vals])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    m = min(len(b) for b in bands)
    if m < 50:
        return []
    rows = [[bands[b][t] for b in range(n)] for t in range(m)]
    out = []
    for t in range(1, m):
        code = 0
        for b in range(n - 1):
            d = (rows[t][b] - rows[t][b + 1]) - (rows[t - 1][b] - rows[t - 1][b + 1])
            code = (code << 1) | (1 if d > 0 else 0)
        out.append(code if max(rows[t]) > -55 else -1)
    return out


def find_common(fa: list[int], fb: list[int], min_len=12.0):
    """Tratto uguale più lungo tra due impronte: ((inizio_a, fine_a), (inizio_b, fine_b)) in secondi, o None."""
    if not fa or not fb:
        return None
    idx: dict[tuple, list[int]] = {}
    for j in range(len(fb) - 3):
        key = tuple(fb[j:j + 4])
        if -1 in key:
            continue
        idx.setdefault(key, []).append(j)
    votes: dict[int, int] = {}
    for i in range(len(fa) - 3):
        key = tuple(fa[i:i + 4])
        for j in idx.get(key, ()):
            votes[j - i] = votes.get(j - i, 0) + 1
    if not votes:
        return None
    best = None
    for d, _ in sorted(votes.items(), key=lambda kv: -kv[1])[:8]:
        cur_s, last_hit, hits = None, -99, 0
        best_run = (0, 0, 0)
        for i in range(max(0, -d), min(len(fa), len(fb) - d)):
            x, y = fa[i], fb[i + d]
            if x != -1 and y != -1 and bin(x ^ y).count("1") <= 1:
                if cur_s is None or i - last_hit > 5:      # più di 0,5 s diverso: nuovo tratto
                    cur_s, hits = i, 0
                hits += 1
                last_hit = i
                if hits / (i - cur_s + 1) >= 0.6 and i - cur_s > best_run[1] - best_run[0]:
                    best_run = (cur_s, i, hits)
        a0, a1, _ = best_run
        if (a1 - a0) * FRAME >= min_len and (best is None or a1 - a0 > best[0][1] - best[0][0]):
            best = ((a0, a1), (a0 + d, a1 + d))
    if not best:
        return None
    (a0, a1), (b0, b1) = best
    return (a0 * FRAME, (a1 + 1) * FRAME), (b0 * FRAME, (b1 + 1) * FRAME)


INTRO_CHAPTER = re.compile(r"(?i)\b(intro|opening|op|recap|previously|riassunto|sigla|title sequence|titles)\b")
CREDITS_CHAPTER = re.compile(r"(?i)\b(credits|ending|end credits|outro|titoli di coda)\b")


def chapter_ranges(chapters: list[dict], duration: float):
    """Intro e titoli di coda dai nomi dei capitoli (molti WEB-DL li hanno)."""
    intro = credits = None
    for i, c in enumerate(chapters):
        t = c.get("title") or ""
        s = float(c.get("time") or 0)
        e = float(chapters[i + 1]["time"]) if i + 1 < len(chapters) else duration
        if intro is None and INTRO_CHAPTER.search(t) and e - s < 300:
            intro = (s, e)
        elif credits is None and CREDITS_CHAPTER.search(t) and s > duration * 0.6:
            credits = (s, e)
    return intro, credits
