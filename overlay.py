"""Vorschau-Popup oben rechts, z. B. nach einem Screenshot mitten im Spiel.

Ein eigenes Win32-Fenster (ohne Tk), gezeichnet mit Pillow und per UpdateLayeredWindow
angezeigt. Dadurch gibt es echte Transparenz (runde Ecken, weicher Schatten), und:
- es holt sich nie den Fokus (WS_EX_NOACTIVATE, SW_SHOWNOACTIVATE), das Spiel bleibt vorne,
- ein Klick darauf ruft on_click auf (z. B. Clipper mit dem Screenshot öffnen),
- solange die Maus darüber ist, bleibt es stehen,
- es ist für Bildschirmaufnahmen unsichtbar (WDA_EXCLUDEFROMCAPTURE), landet also nicht im nächsten Clip.
Alles läuft in einem eigenen Thread; show() kann von überall aufgerufen werden.
"""
import ctypes
import math
import queue
import threading
import time
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

_q = queue.Queue()
_thread = None

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

WS_POPUP, SS_NOTIFY = 0x80000000, 0x100   # SS_NOTIFY: Static-Fenster nimmt Mausklicks an
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x8, 0x80
WM_LBUTTONUP = 0x0202
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
SW_SHOWNOACTIVATE, ULW_ALPHA, WDA_EXCLUDEFROMCAPTURE = 4, 2, 0x11
HOLD_SECONDS = 2.8


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                ("alpha", ctypes.c_ubyte), ("format", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
                                       wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]


def show(image_path, title, subtitle, on_click=None, hint=""):
    """Zeigt das Popup. Ein neues ersetzt ein noch sichtbares. on_click läuft in einem eigenen Thread."""
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_run, daemon=True)
        _thread.start()
    _q.put((str(image_path), title, subtitle, on_click, hint))


def _font(size, bold=False):
    for name in (["segoeuisb.ttf", "seguisb.ttf", "segoeuib.ttf"] if bold else ["segoeui.ttf"]):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _card(path, title, subtitle, scale, hint=""):
    """Zeichnet das Popup als RGBA-Bild: Schatten, dunkle Karte, Vorschau, Text."""
    s = lambda v: max(1, round(v * scale))
    shadow, w, pad, r = s(18), s(340), s(10), s(14)
    tw = w - 2 * pad
    with Image.open(path) as src:
        th = min(round(tw * src.height / src.width), round(tw * 0.75))
        thumb = ImageOps.fit(src.convert("RGB"), (tw, th), Image.LANCZOS)
    text_h = s(52)
    h = pad + th + text_h
    W, H = w + 2 * shadow, h + 2 * shadow
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    sh = Image.new("L", (W, H), 0)   # weicher Schatten unter der Karte
    ImageDraw.Draw(sh).rounded_rectangle((shadow, shadow + s(4), shadow + w, shadow + h + s(4)), r, fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(s(10)))
    img.paste((0, 0, 0, 255), (0, 0), sh)

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((shadow, shadow, shadow + w - 1, shadow + h - 1), r,
                        fill=(30, 30, 32, 245), outline=(255, 255, 255, 28), width=1)
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), s(8), fill=255)
    img.paste(thumb, (shadow + pad, shadow + pad), mask)

    # grüner Haken + Titel + Dateiname
    cy = shadow + pad + th + text_h // 2
    cx = shadow + pad + s(10)
    d.ellipse((cx - s(10), cy - s(10), cx + s(10), cy + s(10)), fill=(48, 209, 88, 255))
    d.line([(cx - s(4.5), cy + s(0.5)), (cx - s(1), cy + s(4)), (cx + s(5), cy - s(3.5))],
           fill=(255, 255, 255, 255), width=s(2.2), joint="curve")
    tx = cx + s(18)
    d.text((tx, cy - s(1)), title, font=_font(s(14), True), fill=(245, 245, 247, 255), anchor="ls")
    right = shadow + w - pad
    if hint:
        fh = _font(s(12), True)
        d.text((right, cy), hint, font=fh, fill=(10, 132, 255, 255), anchor="rm")
        right -= d.textlength(hint, font=fh) + s(10)
    sub = subtitle
    f2 = _font(s(11.5))
    while d.textlength(sub, font=f2) > right - tx and len(sub) > 4:
        sub = sub[:-2]
        if not sub.endswith("…"):
            sub = sub.rstrip() + "…"
    d.text((tx, cy + s(3)), sub, font=f2, fill=(152, 152, 157, 255), anchor="lt")
    return img, shadow


def _premultiplied_bgra(img):
    import numpy as np
    a = np.asarray(img, dtype=np.uint16)
    out = np.empty(a.shape, dtype=np.uint8)
    alpha = a[..., 3]
    out[..., 0] = a[..., 2] * alpha // 255
    out[..., 1] = a[..., 1] * alpha // 255
    out[..., 2] = a[..., 0] * alpha // 255
    out[..., 3] = alpha
    return out.tobytes()


class _Popup:
    def __init__(self, img):
        self.w, self.h = img.size
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE,
            "STATIC", "Clipper", WS_POPUP | SS_NOTIFY, 0, 0, self.w, self.h, None, None, None, None)
        self.x = self.y = 0
        user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)   # nicht im Clip
        self.screen = user32.GetDC(None)
        self.mem = gdi32.CreateCompatibleDC(self.screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), self.w, -self.h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        self.bmp = gdi32.CreateDIBSection(self.mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        data = _premultiplied_bgra(img)
        ctypes.memmove(bits, data, len(data))
        self.old = gdi32.SelectObject(self.mem, self.bmp)
        self.shown = False

    def update(self, x, y, alpha):
        self.x, self.y = int(x), int(y)
        blend = BLENDFUNCTION(0, 0, max(0, min(255, int(alpha))), 1)
        user32.UpdateLayeredWindow(self.hwnd, self.screen, ctypes.byref(wintypes.POINT(int(x), int(y))),
                                   ctypes.byref(wintypes.SIZE(self.w, self.h)), self.mem,
                                   ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
        if not self.shown:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.shown = True

    def close(self):
        gdi32.SelectObject(self.mem, self.old)
        gdi32.DeleteObject(self.bmp)
        gdi32.DeleteDC(self.mem)
        user32.ReleaseDC(None, self.screen)
        user32.DestroyWindow(self.hwnd)


def _pump(hwnd=None):
    """Verarbeitet Fenster-Nachrichten. True, wenn das Popup angeklickt wurde."""
    msg, clicked = wintypes.MSG(), False
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):   # PM_REMOVE
        if hwnd and msg.hWnd == hwnd and msg.message == WM_LBUTTONUP:
            clicked = True
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    return clicked


def _hovered(popup, shadow):
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return (popup.x + shadow <= pt.x < popup.x + popup.w - shadow
            and popup.y + shadow <= pt.y < popup.y + popup.h - shadow)


def _ease_out(t):   # wie cubic-bezier(0.23, 1, 0.32, 1): schnell rein, weich aus
    return 1 - (1 - t) ** 4


def _run():
    while True:
        item = _q.get()
        while not _q.empty():   # mehrere schnell hintereinander: nur das neueste zeigen
            item = _q.get()
        try:
            _animate(*item)
        except Exception:
            import logging
            logging.getLogger("clipper").exception("Vorschau-Popup fehlgeschlagen")


def _animate(path, title, subtitle, on_click=None, hint=""):
    scale = user32.GetDpiForSystem() / 96 if hasattr(user32, "GetDpiForSystem") else 1.0
    img, shadow = _card(path, title, subtitle, scale, hint if on_click else "")
    popup = _Popup(img)
    sw = user32.GetSystemMetrics(0)
    margin = round(16 * scale)
    x_end = sw - popup.w - margin + shadow
    y = margin - shadow
    slide = round(28 * scale)

    def run_phase(duration, frame, until=None):
        """Spielt eine Phase ab. Gibt "click", "new" oder None (normal zu Ende) zurück."""
        start = time.perf_counter()
        while True:
            t = min(1.0, (time.perf_counter() - start) / duration)
            x, alpha = frame(t)
            popup.update(x, y, alpha)
            if _pump(popup.hwnd) and on_click:
                return "click"
            if not _q.empty():
                return "new"
            if t >= 1.0 and (until is None or until()):
                return None
            time.sleep(1 / 120)

    try:
        result = (run_phase(0.26, lambda t: (x_end + slide * (1 - _ease_out(t)), 255 * _ease_out(t)))   # rein
                  or run_phase(HOLD_SECONDS, lambda t: (x_end, 255),
                               until=lambda: not _hovered(popup, shadow)))                            # stehen, solange Maus drauf
        if result == "click":
            threading.Thread(target=on_click, daemon=True).start()
        if result != "new":   # raus, schneller als rein
            run_phase(0.2 if result is None else 0.12, lambda t: (x_end + slide * 0.4 * t * t, 255 * (1 - t)))
    finally:
        popup.close()
        _pump()


if __name__ == "__main__":   # Test: python overlay.py bild.png
    import sys
    show(sys.argv[1], "Screenshot saved", "Screenshot 2026-10-22 12-00-00.png",
         on_click=lambda: print("angeklickt"), hint="Open ›")
    time.sleep(6)
