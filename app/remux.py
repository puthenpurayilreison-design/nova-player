"""Conversione MKV ↔ MP4 senza perdita (remux con ffmpeg -c copy)."""
from __future__ import annotations

import json
import os
import re
import time
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QProcess

from .config import tool

MP4_AUDIO_OK = {"aac", "ac3", "eac3", "mp3", "opus", "alac", "flac"}
TEXT_SUBS = {"subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
NOWIN = 0x08000000 if sys.platform == "win32" else 0


def probe(path: str) -> dict:
    out = subprocess.run([tool("ffprobe"), "-v", "quiet", "-print_format", "json", "-show_streams",
                          "-show_format", path], capture_output=True, timeout=60, creationflags=NOWIN).stdout
    return json.loads(out or b"{}")


def build_args(src: str, dst: str, target: str, info: dict) -> tuple[list[str], list[str]]:
    """Restituisce (argomenti ffmpeg, avvisi)."""
    notes: list[str] = []
    args = ["-hide_banner", "-y", "-i", src, "-map_metadata", "0", "-map_chapters", "0"]
    streams = info.get("streams", [])
    if target == "mkv":
        args += ["-map", "0", "-c", "copy"]
    else:
        a_idx = s_idx = 0
        maps, codecs = [], []
        for s in streams:
            t, c, i = s.get("codec_type"), s.get("codec_name", ""), s["index"]
            if t == "video":
                if s.get("disposition", {}).get("attached_pic"):
                    continue
                maps += ["-map", f"0:{i}"]
            elif t == "audio":
                maps += ["-map", f"0:{i}"]
                if c not in MP4_AUDIO_OK:
                    ch = int(s.get("channels") or 2)
                    codecs += [f"-c:a:{a_idx}", "eac3", f"-b:a:{a_idx}", "640k" if ch > 2 else "256k"]
                    notes.append(f"{c.upper()} audio converted to E-AC3 (not supported in MP4).")
                a_idx += 1
            elif t == "subtitle":
                if c in TEXT_SUBS:
                    maps += ["-map", f"0:{i}"]
                    codecs += [f"-c:s:{s_idx}", "mov_text"]
                    s_idx += 1
                else:
                    notes.append(f"{c.upper()} subtitles (image) left out: MP4 doesn't support them.")
        args += maps + ["-c", "copy"] + codecs + ["-movflags", "+faststart"]
        hevc = any(s.get("codec_name") == "hevc" for s in streams if s.get("codec_type") == "video")
        if hevc:
            args += ["-tag:v", "hvc1"]
    args += ["-progress", "pipe:1", "-nostats", dst]
    return args, sorted(set(notes))


class RemuxJob(QObject):
    progress = Signal(float)
    finished = Signal(bool, str, list)  # ok, percorso/errore, avvisi

    def __init__(self, src: str, target: str, parent=None):
        super().__init__(parent)
        self.src = src
        self.target = target
        p = Path(src)
        dst = p.with_suffix(f".{target}")
        if dst == p or dst.exists():
            dst = p.with_name(f"{p.stem} (NOVA).{target}")
        self.dst = str(dst)
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.duration = 0.0
        self.notes: list[str] = []
        self._err = b""
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_err", (self._err + bytes(self.proc.readAllStandardError()))[-4000:]))

    def start(self):
        try:
            info = probe(self.src)
        except Exception as e:
            self.finished.emit(False, f"Can't read the file: {e}", [])
            return
        self.duration = float(info.get("format", {}).get("duration") or 0)
        args, self.notes = build_args(self.src, self.dst, self.target, info)
        self.proc.start(tool("ffmpeg"), args)

    def cancel(self):
        self.proc.kill()

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="ignore")
        for m in re.finditer(r"out_time_us=(\d+)", data):
            if self.duration:
                self.progress.emit(min(1.0, int(m.group(1)) / 1e6 / self.duration))

    def _done(self, code, status):
        if code == 0:
            self.progress.emit(1.0)
            self.finished.emit(True, self.dst, self.notes)
        else:
            try:
                Path(self.dst).unlink(missing_ok=True)
            except Exception:
                pass
            msg = self._err.decode(errors="ignore").strip().splitlines()[-1:] or ["unknown error"]
            self.finished.emit(False, f"ffmpeg: {msg[0]}", [])


# ------------------------------------------------------------------ versione per telefono
PHONE_MAX_BYTES = 1_400_000_000          # 1,4 GB
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


def _nvenc_ok() -> bool:
    """La GPU NVIDIA può codificare H.264? (prova reale di mezzo secondo, il risultato resta in memoria)."""
    global _NVENC
    try:
        return _NVENC
    except NameError:
        pass
    try:
        r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                            "color=black:s=256x144:d=0.5", "-c:v", "h264_nvenc", "-f", "null", "-"],
                           capture_output=True, timeout=30, creationflags=NOWIN)
        _NVENC = r.returncode == 0
    except Exception:
        _NVENC = False
    return _NVENC


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def phone_plans(src: str, dst: str, info: dict, langs: list[str], nvenc: bool) -> list[tuple[str, list[str]]]:
    """MP4 H.264 720p + AAC stereo sotto 1,4 GB. Restituisce più "ricette" dalla più veloce alla più sicura:
    se una non parte su questo PC (driver, GPU), si passa subito alla successiva.
    - NVIDIA: decodifica, ridimensiona e codifica tutto sulla GPU (il processore resta libero);
      HDR → colori normali con libplacebo (GPU, Vulkan).
    - Altrimenti: decodifica hardware se c'è, prima rimpicciolisce e poi converte l'HDR (molto più leggero)."""
    streams = info.get("streams", [])
    dur = float(info.get("format", {}).get("duration") or 0) or 7200.0
    vids = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    auds = [s for s in streams if s.get("codec_type") == "audio"]
    v = vids[0] if vids else None
    a = None
    for lang in langs:                                   # lingua audio preferita
        a = next((s for s in auds if (s.get("tags", {}).get("language") or "").lower().startswith(lang)), None)
        if a:
            break
    a = a or next((s for s in auds if s.get("disposition", {}).get("default")), None) or (auds[0] if auds else None)
    audio_k = 128
    budget_k = PHONE_MAX_BYTES * 0.96 * 8 / dur / 1000 - audio_k - 8      # margine per il contenitore
    sh = int(v.get("height") or 720) if v else 720
    sw = int(v.get("width") or sh * 16 / 9) if v else 1280
    th = min(720, sh)
    tw = _even(sw * th / sh)
    th = _even(th)
    video_k = int(max(500, min(2800 if th >= 700 else 1600, budget_k)))
    hdr = bool(v and v.get("color_transfer") in HDR_TRANSFERS)
    net = src.startswith(("http://", "https://"))
    inp = ["-hide_banner", "-y", "-nostdin"]
    if net:
        inp += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_on_network_error", "1",
                "-reconnect_delay_max", "15", "-rw_timeout", "30000000"]
    maps = ["-map_metadata", "-1", "-map_chapters", "-1"]
    if v:
        maps += ["-map", f"0:{v['index']}"]
    if a:
        maps += ["-map", f"0:{a['index']}"]
    tail = ["-c:a", "aac", "-b:a", f"{audio_k}k", "-ac", "2",
            "-movflags", "+faststart", "-progress", "pipe:1", "-stats_period", "1", "-nostats", dst]
    rate = ["-b:v", f"{video_k}k", "-maxrate", f"{int(video_k * 1.5)}k", "-bufsize", f"{video_k * 2}k"]
    nv = ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-multipass", "qres",
          "-spatial-aq", "1", "-rc-lookahead", "20", "-bf", "3"] + rate + ["-profile:v", "high", "-level", "4.1"]
    cores = os.cpu_count() or 4
    x264 = ["-c:v", "libx264", "-preset", "veryfast", "-threads", str(max(2, cores - 2))] + rate + \
           ["-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"]
    # HDR → SDR su CPU: prima rimpicciolisce (9 volte meno pixel da un 4K), poi converte i colori
    cpu_hdr = (f"zscale=w={tw}:h={th}:f=bicubic:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
               "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
    cpu_sdr = (f"scale={tw}:{th}:flags=bicubic," if (tw, th) != (sw, sh) else "") + "format=yuv420p"
    plans: list[tuple[str, list[str]]] = []
    if not v:
        return [("Audio only", inp + ["-i", src] + maps + tail)]
    if nvenc:
        if hdr:
            pl = (f"libplacebo=w={tw}:h={th}:tonemapping=bt.2390:colorspace=bt709:color_primaries=bt709:"
                  "color_trc=bt709:range=tv:format=yuv420p")
            plans.append(("NVIDIA GPU (HDR → normal colours on the GPU)",
                          inp + ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk", "-hwaccel", "cuda",
                                 "-i", src] + maps + ["-vf", pl] + nv + tail))
            plans.append(("NVIDIA GPU (HDR converted on the CPU)",
                          inp + ["-hwaccel", "cuda", "-i", src] + maps + ["-vf", cpu_hdr] + nv + tail))
        else:
            plans.append(("NVIDIA GPU (everything on the graphics card)",
                          inp + ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda", "-i", src] + maps +
                          ["-vf", f"scale_cuda={tw}:{th}:interp_algo=lanczos:format=yuv420p"] + nv + tail))
            plans.append(("GPU NVIDIA", inp + ["-hwaccel", "cuda", "-i", src] + maps + ["-vf", cpu_sdr] + nv + tail))
        plans.append(("NVIDIA GPU (decoding on the CPU)",
                      inp + ["-i", src] + maps + ["-vf", cpu_hdr if hdr else cpu_sdr] + nv + tail))
    vf = cpu_hdr if hdr else cpu_sdr
    plans.append(("CPU (hardware decoding)",
                  inp + ["-hwaccel", "auto", "-i", src] + maps + ["-vf", vf] + x264 + tail))
    plans.append(("CPU", inp + ["-i", src] + maps + ["-vf", vf] + x264 + tail))
    return plans


def phone_args(src: str, dst: str, info: dict, langs: list[str], nvenc: bool) -> list[str]:
    """La ricetta preferita (compatibilità con il codice vecchio)."""
    return phone_plans(src, dst, info, langs, nvenc)[0][1]


class PhoneJob(RemuxJob):
    """Versione per telefono di un file o di un link (MP4 720p leggero)."""

    def __init__(self, src: str, out_dir: str, title: str, langs: list[str], parent=None):
        QObject.__init__(self, parent)
        self.src = src
        safe = re.sub(r'[<>:"/\\|?*]+', " ", title).strip() or "video"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        dst = Path(out_dir) / f"{safe} (phone).mp4"
        n = 2
        while dst.exists():
            dst = Path(out_dir) / f"{safe} (phone {n}).mp4"
            n += 1
        self.dst = str(dst)
        self.langs = langs
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._done)
        self.duration = 0.0
        self.notes: list[str] = []
        self._err = b""
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_err", (self._err + bytes(self.proc.readAllStandardError()))[-4000:]))

    def start(self):
        import threading

        def prep():
            try:
                info = probe(self.src)
                nv = _nvenc_ok()
            except Exception as e:
                info, nv = {"_err": str(e)}, False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self, lambda: self._go(info, nv))
        threading.Thread(target=prep, daemon=True).start()

    def _go(self, info, nv):
        if not info.get("streams"):
            self.finished.emit(False, "Can't read the video (expired link or invalid file).", [])
            return
        self.duration = float(info.get("format", {}).get("duration") or 0)
        self.plans = phone_plans(self.src, self.dst, info, self.langs, nv)
        self._next_plan()

    def _next_plan(self):
        label, args = self.plans.pop(0)
        self.notes = [f"Conversion: {label}."]
        self._got_progress = False
        self._err = b""
        self._t0 = time.time()
        self.proc.start(tool("ffmpeg"), args)
        if self.proc.waitForStarted(5000):
            from . import winutil
            winutil.lower_priority(self.proc.processId())

    def _read(self):
        data = bytes(self.proc.readAllStandardOutput()).decode(errors="ignore")
        last = None
        for m in re.finditer(r"out_time_us=(\d+)", data):
            last = int(m.group(1))
        if last and self.duration:
            if last > 5_000_000:       # almeno 5 s di film già convertiti: la ricetta funziona
                self._got_progress = True
            self.progress.emit(min(1.0, last / 1e6 / self.duration))

    def cancel(self):
        self.plans = []
        self.proc.kill()

    def _done(self, code, status):
        if code != 0 and self.plans and not self._got_progress and status != QProcess.CrashExit \
                and time.time() - self._t0 < 120:
            # questa ricetta non parte su questo PC: prova subito la successiva
            try:
                Path(self.dst).unlink(missing_ok=True)
            except Exception:
                pass
            self._next_plan()
            return
        super()._done(code, status)
