"""Suono: profili per cuffie, casse e subwoofer, dialoghi chiari, volume notte, uscita e ritardo per dispositivo.

Tutti i profili sono filtri ffmpeg standard (pan, crossfeed, acompressor, equalizer, highpass, alimiter),
costruiti sui canali reali della traccia: un 5.1/7.1 viene mixato a stereo tenendo il canale dei bassi (LFE),
che il downmix normale butta via.
"""
from __future__ import annotations

PROFILES = [
    ("auto", "Automatico", "Sceglie da solo in base all'uscita (cuffie, monitor, casse)"),
    ("normal", "Originale", "Suono così com'è, nessun filtro"),
    ("headphones", "Cinema in cuffia 3D", "Suono intorno a te: ogni canale del 5.1/7.1 arriva da dove sta nella sala (davanti, lati, dietro)"),
    ("indian", "Cinema indiano", "Per i mix indiani: voci sempre chiare sopra musica e BGM forti, bassi pieni"),
    ("dialogue", "Dialoghi chiari", "Voci più avanti, effetti e musica più bassi"),
    ("night", "Volume notte", "Esplosioni più basse, voci più alte: niente su e giù col volume"),
    ("subwoofer", "Casse + subwoofer", "Tiene i bassi del film (LFE) e protegge le casse dalla distorsione"),
    ("monitor", "Casse del monitor", "Taglia i bassi che le casse piccole non riescono a fare, voci più chiare"),
]
PROFILE_NAMES = {k: n for k, n, _ in PROFILES}

# ordine dei canali dei layout più comuni (nomi ffmpeg)
LAYOUTS = {
    "mono": ["FC"], "1.0": ["FC"], "stereo": ["FL", "FR"], "2.0": ["FL", "FR"], "2.1": ["FL", "FR", "LFE"],
    "3.0": ["FL", "FR", "FC"], "3.1": ["FL", "FR", "FC", "LFE"], "4.0": ["FL", "FR", "FC", "BC"],
    "quad": ["FL", "FR", "BL", "BR"], "quad(side)": ["FL", "FR", "SL", "SR"],
    "5.0": ["FL", "FR", "FC", "BL", "BR"], "5.0(side)": ["FL", "FR", "FC", "SL", "SR"],
    "5.1": ["FL", "FR", "FC", "LFE", "BL", "BR"], "5.1(side)": ["FL", "FR", "FC", "LFE", "SL", "SR"],
    "6.1": ["FL", "FR", "FC", "LFE", "BC", "SL", "SR"],
    "7.1": ["FL", "FR", "FC", "LFE", "BL", "BR", "SL", "SR"],
    "7.1(wide)": ["FL", "FR", "FC", "LFE", "BL", "BR", "FLC", "FRC"],
    "7.1(wide-side)": ["FL", "FR", "FC", "LFE", "FLC", "FRC", "SL", "SR"],
}
_MPV_NAMES = {"fl": "FL", "fr": "FR", "fc": "FC", "lfe": "LFE", "bl": "BL", "br": "BR", "sl": "SL", "sr": "SR",
              "bc": "BC", "flc": "FLC", "frc": "FRC", "na": None}


def channels_of(layout: str, count: int = 0) -> list[str]:
    """Nomi dei canali da 'audio-params/channels' di mpv (es. '5.1(side)' o 'fl-fr-fc-lfe-sl-sr')."""
    layout = (layout or "").lower().strip()
    if layout in LAYOUTS:
        return LAYOUTS[layout]
    if "-" in layout:
        out = [_MPV_NAMES.get(c) for c in layout.split("-")]
        if all(out):
            return out
    return {1: ["FC"], 2: ["FL", "FR"], 6: LAYOUTS["5.1"], 8: LAYOUTS["7.1"]}.get(count, [])


def _downmix(ch: list[str], c: float, s: float, lfe: float, b: float | None = None) -> str:
    """pan da multicanale a stereo con pesi per centro (voci), surround e LFE (bassi)."""
    b = s if b is None else b

    def side(L):  # L = "L" o "R"
        terms = [f"F{L}"]
        if "FC" in ch:
            terms.append(f"{c:g}*FC")
        if "LFE" in ch:
            terms.append(f"{lfe:g}*LFE")
        for name, w in ((f"S{L}", s), (f"B{L}", b), (f"F{L}C", 0.8)):
            if name in ch:
                terms.append(f"{w:g}*{name}")
        if "BC" in ch:
            terms.append(f"{b * 0.7:g}*BC")
        return "+".join(terms)
    return f"pan=stereo|FL={side('L')}|FR={side('R')}"


# audio registrato in sala (CAM/TS): fruscio, rimbombo della sala, voci "ovattate", pubblico
CAM_AUDIO = ["highpass=f=95:poles=2", "lowpass=f=14500", "afftdn=nr=16:nf=-30:tn=1",
             "equalizer=f=230:t=q:w=1.0:g=-4",          # meno rimbombo della sala
             "equalizer=f=3000:t=q:w=1.3:g=4",          # voci in avanti
             "equalizer=f=7500:t=q:w=1.0:g=2",          # un po' di aria persa nella registrazione
             "acompressor=threshold=-26dB:ratio=4:attack=6:release=260:makeup=6dB",
             "alimiter=limit=0.92:attack=5:release=80:level=disabled"]


def _binaural(ch: list[str]) -> list[str]:
    """Cinema in cuffia 3D: ogni canale diventa un altoparlante virtuale intorno alla testa.
    Per ogni lato: suono diretto all'orecchio vicino; all'orecchio lontano arriva più tardi (ITD, 0.3 ms davanti,
    0.6 ms ai lati/dietro) e più scuro (ombra della testa); i canali dietro perdono un po' di acuti (come dal vero);
    una prima riflessione corta dà la sensazione di "stanza" invece del suono dentro la testa."""
    has = set(ch)

    def j(*terms):
        t = [f"{w:g}*{n}" if w != 1 else n for w, n in terms if n in has]
        return "+".join(t) or "0*" + ch[0]
    left_f, right_f = [(1, "FL"), (0.71, "FC"), (0.5, "LFE"), (0.8, "FLC")], [(1, "FR"), (0.71, "FC"), (0.5, "LFE"), (0.8, "FRC")]
    sur_l, sur_r = [(1, "SL"), (0.9, "BL"), (0.65, "BC")], [(1, "SR"), (0.9, "BR"), (0.65, "BC")]
    surround = bool(has & {"SL", "SR", "BL", "BR", "BC"})
    paths = [
        f"pan=stereo|FL={j(*left_f)}|FR={j(*right_f)}",
        f"pan=stereo|FL={j((1, 'FR'), (0.8, 'FRC'))}|FR={j((1, 'FL'), (0.8, 'FLC'))},adelay=0.3|0.3,"
        "lowpass=f=2600:poles=1,volume=0.5",
    ]
    if surround:
        paths += [f"pan=stereo|FL={j(*sur_l)}|FR={j(*sur_r)},treble=g=-3.5:f=5500,volume=0.85",
                  f"pan=stereo|FL={j(*sur_r)}|FR={j(*sur_l)},adelay=0.62|0.62,lowpass=f=1700:poles=1,volume=0.42"]
    room_l = j((1, "FL"), (0.5, "FC"), (0.7, "SL"), (0.7, "BL"), (0.5, "FLC"))
    room_r = j((1, "FR"), (0.5, "FC"), (0.7, "SR"), (0.7, "BR"), (0.5, "FRC"))
    paths.append(f"pan=stereo|FL={room_r}|FR={room_l},adelay=11|16,highpass=f=250,lowpass=f=5000,volume=0.16")
    n = len(paths)
    labels = "".join(f"[p{i}]" for i in range(n))
    graph = f"asplit={n}{labels};" + ";".join(f"[p{i}]{p}[q{i}]" for i, p in enumerate(paths))
    graph += ";" + "".join(f"[q{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0"
    return [graph]


def build_af(profile: str, layout: str, count: int, theatre: bool = False, clean_audio: bool = False) -> str:
    """Catena di filtri mpv ('af') per il profilo e la traccia attuali. '' = nessun filtro.
    theatre=True: registrazione dal cinema (CAM/HDTC) → meno fruscio e rimbombo, voci più chiare."""
    ch = channels_of(layout, count)
    if theatre and ch and not clean_audio:
        base = build_af("normal" if profile in ("auto", "") else profile, layout, count)
        inner = base[len("lavfi=["):-1].split(",") if base else []
        inner = [f for f in inner if not f.startswith("alimiter")]
        return "lavfi=[" + ",".join(inner + CAM_AUDIO) + "]"
    if profile in ("normal", "auto", "") or not ch:
        return ""
    multi = len(ch) > 2 and any(c not in ("FL", "FR") for c in ch)
    mono = ch == ["FC"]
    f: list[str] = []
    limiter = "alimiter=limit=0.94:attack=5:release=60:level=disabled"
    if profile == "headphones":
        if not mono:
            f += _binaural(ch)
            f.append("alimiter=limit=0.94:attack=3:release=60:level=disabled")
    elif profile == "indian":
        if multi:
            f.append(_downmix(ch, 1.15, 0.5, 0.6, 0.45))
        f.append("equalizer=f=2900:t=q:w=1.2:g=2.5")
        f.append("acompressor=threshold=-24dB:ratio=2.5:attack=10:release=300:makeup=3dB:knee=4")
        f.append(limiter)
    elif profile == "dialogue":
        if multi:
            f.append(_downmix(ch, 1.25, 0.35, 0.25, 0.3))
        f.append("highpass=f=70")
        f.append("equalizer=f=2800:t=q:w=1.1:g=4")
        f.append("equalizer=f=180:t=q:w=1:g=-2")
        f.append("acompressor=threshold=-22dB:ratio=3:attack=8:release=220:makeup=2dB")
        f.append(limiter)
    elif profile == "night":
        if multi:
            f.append(_downmix(ch, 1.1, 0.45, 0.25, 0.4))
        f.append("acompressor=threshold=-30dB:ratio=6:attack=5:release=350:makeup=9dB:knee=4")
        f.append(limiter)
    elif profile == "subwoofer":
        if multi:
            f.append(_downmix(ch, 0.71, 0.55, 0.9, 0.5))
        else:
            f.append("bass=g=2:f=90:w=0.7")
        f.append("alimiter=limit=0.9:attack=5:release=80:level=disabled")
    elif profile == "monitor":
        if multi:
            f.append(_downmix(ch, 1.0, 0.45, 0.15, 0.4))
        f.append("highpass=f=140:poles=2")
        f.append("equalizer=f=3000:t=q:w=1:g=3")
        f.append("acompressor=threshold=-24dB:ratio=3:attack=10:release=250:makeup=3dB")
        f.append(limiter)
    if not f:
        return ""
    return "lavfi=[" + ",".join(f) + "]"


_HEADPHONE_WORDS = ("soundcore", "anker", "headphone", "headset", "cuffie", "auricolari", "earbuds", "buds",
                    "airpods", "hands-free", "airdots", "wh-1000", "bluetooth")
_MONITOR_WORDS = ("aoc", "nvidia high definition", "hdmi", "displayport", "monitor", "lg tv", "samsung")
_FX_WORDS = ("fxsound", "fx sound", "dfx")


def is_fxsound(desc: str) -> bool:
    d = (desc or "").lower()
    return any(w in d for w in _FX_WORDS)


def is_bluetooth(desc: str) -> bool:
    d = (desc or "").lower()
    return any(w in d for w in _HEADPHONE_WORDS)


def auto_profile(device_desc: str) -> str:
    """Profilo consigliato per un'uscita audio, dal suo nome."""
    d = (device_desc or "").lower()
    if any(w in d for w in _HEADPHONE_WORDS):
        return "headphones"
    if any(w in d for w in _MONITOR_WORDS):
        return "monitor"
    return "normal"
