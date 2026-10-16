"""Integrazioni native con Windows 11 (no-op su altri sistemi)."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"


def dark_background(hwnd: int, color: str):
    """Sfondo nativo della finestra nel colore del tema: quando Windows ridisegna (cambio pagina, chiusura del
    video, ridimensionamento) non compare mai il bianco di default nemmeno per un frame."""
    if not IS_WIN or not hwnd:
        return
    try:
        c = color.lstrip("#")
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        brush = ctypes.windll.gdi32.CreateSolidBrush(r | (g << 8) | (b << 16))
        set_cls = getattr(ctypes.windll.user32, "SetClassLongPtrW", None) or ctypes.windll.user32.SetClassLongW
        set_cls.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        set_cls(ctypes.c_void_p(hwnd), -10, ctypes.c_void_p(brush))       # GCLP_HBRBACKGROUND
    except Exception:
        pass


def dark_titlebar(hwnd: int, dark: bool = True, mica: bool = False):
    """Barra del titolo scura/chiara nativa e angoli arrotondati Windows 11."""
    if not IS_WIN:
        return
    try:
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(val), ctypes.sizeof(val))
        corner = ctypes.c_int(2)  # DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 33, ctypes.byref(corner), ctypes.sizeof(corner))
        if mica:
            bd = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 38, ctypes.byref(bd), ctypes.sizeof(bd))
    except Exception:
        pass


def caption_color(hwnd: int, hex_color: str):
    if not IS_WIN:
        return
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        val = ctypes.c_int(r | (g << 8) | (b << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 35, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def keep_awake(on: bool):
    """Impedisce standby e spegnimento schermo durante la riproduzione."""
    if not IS_WIN:
        return
    ES_CONTINUOUS, ES_SYSTEM, ES_DISPLAY = 0x80000000, 0x00000001, 0x00000002
    try:
        flags = ES_CONTINUOUS | (ES_SYSTEM | ES_DISPLAY if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def set_app_id():
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NOVA.MediaHub")
        except Exception:
            pass


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" "%1"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if pyw.exists():
        exe = pyw
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{exe}" "{main}" "%1"'


def register_associations(video_ext, audio_ext) -> str:
    """Registra NOVA in 'Apri con', nel menu contestuale, per magnet: e .torrent (solo utente corrente)."""
    if not IS_WIN:
        return "Only available on Windows."
    import winreg
    cmd = _launch_command()
    from .config import ROOT
    icon = str(sys.executable) if getattr(sys, "frozen", False) else str(ROOT / "assets" / "nova.ico")
    C = winreg.HKEY_CURRENT_USER
    base = r"Software\Classes"

    def setv(path, name, value):
        k = winreg.CreateKeyEx(C, path, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.CloseKey(k)

    setv(rf"{base}\NOVA.Media", "", "Media file")
    setv(rf"{base}\NOVA.Media\DefaultIcon", "", icon)
    setv(rf"{base}\NOVA.Media\shell\open\command", "", cmd)
    setv(rf"{base}\NOVA.Torrent", "", "Torrent file")
    setv(rf"{base}\NOVA.Torrent\DefaultIcon", "", icon)
    setv(rf"{base}\NOVA.Torrent\shell\open\command", "", cmd)
    for ext in sorted(set(video_ext) | set(audio_ext)):
        setv(rf"{base}\{ext}\OpenWithProgids", "NOVA.Media", "")
        setv(rf"{base}\SystemFileAssociations\{ext}\shell\NOVA", "", "Open with NOVA")
        setv(rf"{base}\SystemFileAssociations\{ext}\shell\NOVA", "Icon", icon)
        setv(rf"{base}\SystemFileAssociations\{ext}\shell\NOVA\command", "", cmd)
    setv(rf"{base}\.torrent\OpenWithProgids", "NOVA.Torrent", "")
    setv(rf"{base}\magnet", "", "URL:Magnet")
    setv(rf"{base}\magnet", "URL Protocol", "")
    setv(rf"{base}\magnet\DefaultIcon", "", icon)
    setv(rf"{base}\magnet\shell\open\command", "", cmd)
    try:
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    except Exception:
        pass
    return ("Done. NOVA now shows up in 'Open with' and in the context menu, and opens magnet links. To make it the default player: Windows Settings › Apps › Default apps › NOVA.")


def set_autostart(on: bool):
    """Avvio automatico con Windows (ridotto a icona nella tray)."""
    if not IS_WIN:
        return
    import winreg
    k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                       winreg.KEY_SET_VALUE)
    if on:
        cmd = _launch_command().replace(' "%1"', " --tray")
        winreg.SetValueEx(k, "NOVA", 0, winreg.REG_SZ, cmd)
    else:
        try:
            winreg.DeleteValue(k, "NOVA")
        except FileNotFoundError:
            pass
    winreg.CloseKey(k)


def is_autostart() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(k, "NOVA")
        return True
    except OSError:
        return False


def set_topmost(hwnd: int, on: bool):
    if not IS_WIN:
        return
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x2, 0x1, 0x10
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), ctypes.c_void_p(HWND_TOPMOST if on else HWND_NOTOPMOST),
                                      0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


_GPU = None


def discrete_gpu_name() -> str | None:
    """Nome della GPU dedicata (NVIDIA/AMD Radeon RX/Intel Arc) letto dal registro, o None."""
    global _GPU
    if _GPU is not None or not IS_WIN:
        return _GPU or None
    import winreg
    names = []
    try:
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base)
        for i in range(32):
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            try:
                sk = winreg.OpenKey(k, sub)
                names.append(winreg.QueryValueEx(sk, "DriverDesc")[0])
            except OSError:
                pass
    except OSError:
        pass
    pick = next((n for n in names if "NVIDIA" in n.upper()), None) or \
        next((n for n in names if "RADEON RX" in n.upper() or "INTEL(R) ARC" in n.upper()), None)
    _GPU = pick or ""
    return pick


def prefer_high_performance_gpu():
    """Dice a Windows di usare la GPU dedicata per NOVA (come 'Prestazioni elevate' in Impostazioni › Grafica)."""
    if not IS_WIN:
        return
    import os
    import winreg
    exes = set()
    for e in (sys.executable, getattr(sys, "_base_executable", ""), sys.exec_prefix + "\\pythonw.exe",
              sys.base_exec_prefix + "\\pythonw.exe", sys.base_exec_prefix + "\\python.exe"):
        if e:
            p = Path(e)
            for n in ("python.exe", "pythonw.exe"):
                q = p.with_name(n)
                if q.exists():
                    exes.add(os.path.normcase(str(q.resolve())))
    try:
        k = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectX\UserGpuPreferences",
                               0, winreg.KEY_WRITE)
        for e in exes:
            winreg.SetValueEx(k, e, 0, winreg.REG_SZ, "GpuPreference=2;")
        winreg.CloseKey(k)
    except OSError:
        pass


def open_firewall(port: int) -> bool:
    """Apre la porta torrent (TCP+UDP in ingresso) nel firewall di Windows. Chiede conferma admin una volta."""
    if not IS_WIN:
        return False
    cmds = " & ".join([
        'netsh advfirewall firewall delete rule name="NOVA Torrent"',
        f'netsh advfirewall firewall add rule name="NOVA Torrent" dir=in action=allow protocol=TCP localport={port}',
        f'netsh advfirewall firewall add rule name="NOVA Torrent" dir=in action=allow protocol=UDP localport={port}',
    ])
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f"/c {cmds}", None, 0)
    return r > 32


# ---------------------------------------------------------------- refresh del monitor per i film
class _DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_uint16 * 32), ("dmSpecVersion", ctypes.c_uint16),
                ("dmDriverVersion", ctypes.c_uint16), ("dmSize", ctypes.c_uint16), ("dmDriverExtra", ctypes.c_uint16),
                ("dmFields", ctypes.c_uint32), ("dmPositionX", ctypes.c_int32), ("dmPositionY", ctypes.c_int32),
                ("dmDisplayOrientation", ctypes.c_uint32), ("dmDisplayFixedOutput", ctypes.c_uint32),
                ("dmColor", ctypes.c_int16), ("dmDuplex", ctypes.c_int16), ("dmYResolution", ctypes.c_int16),
                ("dmTTOption", ctypes.c_int16), ("dmCollate", ctypes.c_int16), ("dmFormName", ctypes.c_uint16 * 32),
                ("dmLogPixels", ctypes.c_uint16), ("dmBitsPerPel", ctypes.c_uint32), ("dmPelsWidth", ctypes.c_uint32),
                ("dmPelsHeight", ctypes.c_uint32), ("dmDisplayFlags", ctypes.c_uint32),
                ("dmDisplayFrequency", ctypes.c_uint32), ("dmICMMethod", ctypes.c_uint32),
                ("dmICMIntent", ctypes.c_uint32), ("dmMediaType", ctypes.c_uint32), ("dmDitherType", ctypes.c_uint32),
                ("dmReserved1", ctypes.c_uint32), ("dmReserved2", ctypes.c_uint32),
                ("dmPanningWidth", ctypes.c_uint32), ("dmPanningHeight", ctypes.c_uint32)]


_ENUM_CURRENT = 0xFFFFFFFF
_DM_W, _DM_H, _DM_HZ = 0x80000, 0x100000, 0x400000
_CDS_FULLSCREEN = 0x4


def _devmode():
    dm = _DEVMODEW()
    dm.dmSize = ctypes.sizeof(_DEVMODEW)
    return dm


def display_mode(device: str):
    """(larghezza, altezza, Hz) attuali del monitor, es. device='\\\\.\\DISPLAY5'."""
    if not IS_WIN:
        return None
    dm = _devmode()
    if ctypes.windll.user32.EnumDisplaySettingsExW(device, _ENUM_CURRENT, ctypes.byref(dm), 0):
        return dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency
    return None


def display_rates(device: str, w: int, h: int) -> list[int]:
    """Frequenze supportate dal monitor alla risoluzione indicata."""
    if not IS_WIN:
        return []
    rates, i = set(), 0
    dm = _devmode()
    while ctypes.windll.user32.EnumDisplaySettingsExW(device, i, ctypes.byref(dm), 0):
        if dm.dmPelsWidth == w and dm.dmPelsHeight == h and dm.dmDisplayFrequency > 1:
            rates.add(int(dm.dmDisplayFrequency))
        i += 1
        if i > 2000:
            break
    return sorted(rates)


def best_rate_for(fps: float, rates: list[int], current: int) -> int | None:
    """La frequenza più alta (≤ quella attuale) multipla esatta dei fps del film. None se non serve cambiare."""
    if not fps or fps < 10:
        return None

    def exact(hz):
        k = round(hz / fps)
        return k >= 2 and abs(hz / (k * fps) - 1) < 0.004

    if exact(current):
        return None
    good = [r for r in rates if r <= current and exact(r)]
    return max(good) if good else None


def set_refresh(device: str, hz: int) -> bool:
    """Cambia solo la frequenza (temporaneo: non tocca le impostazioni salvate di Windows)."""
    if not IS_WIN:
        return False
    dm = _devmode()
    if not ctypes.windll.user32.EnumDisplaySettingsExW(device, _ENUM_CURRENT, ctypes.byref(dm), 0):
        return False
    dm.dmDisplayFrequency = hz
    dm.dmFields = _DM_W | _DM_H | _DM_HZ
    return ctypes.windll.user32.ChangeDisplaySettingsExW(device, ctypes.byref(dm), None, _CDS_FULLSCREEN, None) == 0


def restore_refresh(device: str):
    """Torna alla modalità salvata in Windows."""
    if IS_WIN:
        try:
            ctypes.windll.user32.ChangeDisplaySettingsExW(device, None, None, 0, None)
        except Exception:
            pass


# ---------------------------------------------------------------- Wi-Fi in modalità streaming
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]


class _WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", _GUID), ("strInterfaceDescription", ctypes.c_wchar * 256),
                ("isState", ctypes.c_uint32)]


class _WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", ctypes.c_uint32), ("dwIndex", ctypes.c_uint32),
                ("InterfaceInfo", _WLAN_INTERFACE_INFO * 1)]


_wlan_handle = None


def wifi_streaming(on: bool) -> bool:
    """Mentre guardi un film dalla rete: Windows smette di fare le scansioni Wi-Fi in background (che ogni
    minuto o due bloccano la connessione per qualche centinaio di ms) e mette la scheda in 'media streaming
    mode'. È l'API ufficiale pensata per i lettori video; tutto torna normale quando la chiudiamo."""
    global _wlan_handle
    if not IS_WIN:
        return False
    try:
        wlan = ctypes.windll.wlanapi
    except OSError:
        return False                    # PC senza Wi-Fi
    if not on:
        if _wlan_handle is not None:
            try:
                wlan.WlanCloseHandle(_wlan_handle, None)     # chiudendo l'handle Windows ripristina tutto
            except Exception:
                pass
            _wlan_handle = None
        return True
    if _wlan_handle is not None:
        return True
    try:
        ver = ctypes.c_uint32()
        h = ctypes.c_void_p()
        if wlan.WlanOpenHandle(2, None, ctypes.byref(ver), ctypes.byref(h)) != 0:
            return False
        plist = ctypes.POINTER(_WLAN_INTERFACE_INFO_LIST)()
        if wlan.WlanEnumInterfaces(h, None, ctypes.byref(plist)) != 0:
            wlan.WlanCloseHandle(h, None)
            return False
        n = plist.contents.dwNumberOfItems
        arr = ctypes.cast(ctypes.addressof(plist.contents.InterfaceInfo),
                          ctypes.POINTER(_WLAN_INTERFACE_INFO * n)).contents if n else []
        off = ctypes.c_uint32(0)
        yes = ctypes.c_uint32(1)
        ok = False
        for info in arr:
            if info.isState != 1:        # wlan_interface_state_connected
                continue
            g = ctypes.byref(info.InterfaceGuid)
            # 2 = wlan_intf_opcode_background_scan_enabled, 3 = wlan_intf_opcode_media_streaming_mode
            a = wlan.WlanSetInterface(h, g, 2, ctypes.sizeof(off), ctypes.byref(off), None)
            b = wlan.WlanSetInterface(h, g, 3, ctypes.sizeof(yes), ctypes.byref(yes), None)
            ok = ok or a == 0 or b == 0
        wlan.WlanFreeMemory(plist)
        if ok:
            _wlan_handle = h
        else:
            wlan.WlanCloseHandle(h, None)
        return ok
    except Exception:
        return False


def playback_priority(on: bool):
    """Priorità 'sopra la norma' mentre guardi: Windows dà la precedenza a NOVA su processi in background."""
    if not IS_WIN:
        return
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x00008000 if on else 0x00000020)
    except Exception:
        pass


def lower_priority(pid: int, idle: bool = False):
    """Lavori pesanti in background (conversioni): priorità sotto la norma, così il PC e i poster restano fluidi."""
    if not IS_WIN or not pid:
        return
    try:
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x0200 | 0x0400, False, int(pid))     # SET_INFORMATION | QUERY_INFORMATION
        if h:
            k.SetPriorityClass(h, 0x00000040 if idle else 0x00004000)
            k.CloseHandle(h)
    except Exception:
        pass


def sleep_pc():
    """Sospensione (non spegnimento): al risveglio NOVA è dove l'avevi lasciato."""
    if IS_WIN:
        try:
            ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
        except Exception:
            pass
