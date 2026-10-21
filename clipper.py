"""Clipper — Replay-Buffer wie die Discord-/Nitro-Clips, mit eigener Clip-Bibliothek.

Alt+R speichert die letzten N Sekunden (Bild + PC-Ton). Das App-Fenster zeigt alle
Clips, spielt sie ab und schneidet sie.

Aufbau:
  Recorder  ffmpeg nimmt dauerhaft auf (ddagrab) und schreibt 1-s-Stücke in einen
            Ringpuffer. Der PC-Ton kommt per WASAPI-Loopback (soundcard) über stdin
            in dasselbe ffmpeg, damit Bild und Ton in denselben Stücken landen.
  Server    kleiner HTTP-Server auf 127.0.0.1 für die Oberfläche (ui.html)
  Fenster   Edge im App-Modus; das Tray-Icon hält Clipper im Hintergrund am Laufen

Start:  pythonw clipper.py          (normal, über "Clipper starten.bat")
        python clipper.py --test    (ohne Bildschirm: Testbild + Testton, auch unter Linux)
Log:    %APPDATA%\\Clipper\\clipper.log
"""

import argparse
import datetime
import json
import logging
import math
import os
import queue
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

PORT = 47821
FROZEN = getattr(sys, "frozen", False)   # als Clipper.exe gebaut (PyInstaller)
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
IS_WIN = sys.platform == "win32"
DATA_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "Clipper"
THUMB_DIR = DATA_DIR / "thumbs"
SETTINGS_FILE = DATA_DIR / "settings.json"
BUFFER_ROOT = Path(tempfile.gettempdir()) / "clipper_buffer"
SHARE_DIR = DATA_DIR / "teilen"
SHARE_LIMIT = 9_800_000   # Discord ohne Nitro: 10 MB
STRIP_FRAMES = 20
SEGMENT_SECONDS = 1
SAMPLE_RATE = 48000
NO_WINDOW = 0x08000000 if IS_WIN else 0   # ffmpeg-Aufrufe ohne schwarzes Konsolenfenster
QUALITY = {"hoch": "20M", "mittel": "12M", "niedrig": "6M"}
ENCODERS = ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"]
DEFAULTS = {
    "clip_seconds": 30,
    "fps": 60,
    "quality": "hoch",
    "audio": True,
    "mic": True,          # eigene Stimme (Standard-Mikrofon) dazumischen
    "mic_volume": 100,    # Prozent
    "hotkey": "alt+r",
    "clip_dir": str(Path.home() / "Videos" / "Clips"),
    "autostart": False,
    "sound": True,
    "theme": "auto",      # Erscheinungsbild: auto (wie Windows), light, dark
}
TEST = False
LANG = "en"   # Clipper ist nur noch auf Englisch. Die deutschen Texte bleiben im Code als Ausgangstext.


def L(de, en):
    """Text in der eingestellten Sprache."""
    return de if LANG == "de" else en

DATA_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(exist_ok=True)
log = logging.getLogger("clipper")
log.setLevel(logging.INFO)
_fh = logging.FileHandler(DATA_DIR / "clipper.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
if sys.stderr:   # unter pythonw gibt es kein stderr
    log.addHandler(logging.StreamHandler())


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW)


def find_tool(name):
    exe = shutil.which(name)
    if exe:
        return exe
    if IS_WIN:   # Autostart sieht den neuen PATH von winget manchmal noch nicht
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        for c in [local / "Microsoft/WinGet/Links" / f"{name}.exe",
                  *local.glob(f"Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/{name}.exe")]:
            if c.exists():
                return str(c)
    return None


def kill_orphans():
    """Beendet ffmpeg-Prozesse eines früheren Clipper-Laufs (Absturz, Fenster per X geschlossen).

    Die laufen sonst unsichtbar weiter, belegen die Grafikkarte und sperren den Puffer.
    Erkennbar sind sie am Pufferpfad in ihrer Befehlszeile.
    """
    if not IS_WIN:
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='ffmpeg.exe'\" | "
          "Where-Object { $_.CommandLine -like '*clipper_buffer*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
    r = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if r.stdout.strip():
        log.info("Alte ffmpeg-Prozesse beendet: %s", r.stdout.split())
        time.sleep(0.5)


def message_box(text):
    log.error(text)
    if IS_WIN:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Clipper", 0x10)


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text("utf-8")))
    except (OSError, ValueError):
        pass
    return s


def unique_path(path):
    if not path.exists():
        return path
    for i in range(2, 1000):
        p = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not p.exists():
            return p
    raise RuntimeError(L("Kein freier Dateiname", "No free file name"))


def retry(fn, tries=10):
    """Windows sperrt Dateien, solange sie noch jemand liest (z. B. der Player)."""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.3)


# --- Encoder -----------------------------------------------------------------

def pick_encoder(ffmpeg):
    for enc in ENCODERS:
        r = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                 "-i", "color=black:s=256x256:d=0.1", "-c:v", enc, "-f", "null", "-"])
        if r.returncode == 0:
            return enc
    return "libx264"


def encoder_args(enc, fps, bitrate, keyframes):
    args = ["-c:v", enc, "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", bitrate,
            "-pix_fmt", "yuv420p"]
    if keyframes:
        # Keyframe an jeder Stückgrenze, sonst lassen sich die Stücke nicht aneinanderhängen
        args += ["-g", str(fps * SEGMENT_SECONDS),
                 "-force_key_frames", f"expr:gte(t,n_forced*{SEGMENT_SECONDS})"]
    if enc == "libx264":
        args += ["-preset", "ultrafast" if keyframes else "veryfast"]
    elif enc == "h264_nvenc":
        args += ["-preset", "p1" if keyframes else "p5"]
    return args


# --- Ton ---------------------------------------------------------------------

class AudioPump:
    """Liefert PC-Ton und Mikrofon gemischt im Takt der Uhr an ffmpeg.

    WASAPI-Loopback liefert bei Stille gar keine Daten. ffmpeg zählt die Zeit aber
    über die Anzahl der Samples — ohne Auffüllen würde der Ton nach jeder Pause
    zu früh kommen. Deshalb schreibt der Schreiber immer genau so viele Samples,
    wie seit dem Start vergangen sind (50 ms hinter der Uhr). Fehlt einer Quelle
    etwas, kommt Stille; staut sich bei einer mehr als 200 ms, fällt das Älteste weg.
    """

    FRAME = 8   # Stereo, float32

    def __init__(self, sink, pc=True, mic=False, mic_gain=1.0):
        self.sink = sink
        self.sources = {}   # Name -> Queue mit float32-Stereo-Arrays
        if pc:
            self.sources["pc"] = queue.Queue()
        if mic:
            self.sources["mic"] = queue.Queue()
        self.mic_gain = mic_gain
        self.running = True
        self.errors = {}
        self.devices = {}

    @property
    def error(self):
        return " · ".join(self.errors.values())

    def start(self):
        for name in self.sources:
            threading.Thread(target=self._read, args=(name,), daemon=True).start()
        threading.Thread(target=self._write, daemon=True).start()

    def stop(self):
        self.running = False

    def _read(self, name):
        q = self.sources[name]
        try:
            if TEST:
                return self._read_test_tone(q, 440 if name == "pc" else 660)
            # Reihenfolge wichtig: soundcard initialisiert COM beim Import selbst und
            # bricht ab, wenn COM im Thread schon läuft (S_FALSE). Für spätere
            # Neustarts des Threads (Modul schon geladen) danach selbst initialisieren.
            import soundcard as sc
            import ctypes
            import numpy as np
            ctypes.windll.ole32.CoInitializeEx(None, 0)   # COM ist pro Thread
            if name == "pc":
                spk = sc.default_speaker()
                dev, channels, gain = sc.get_microphone(spk.id, include_loopback=True), 2, 1.0
                self.devices[name] = spk.name
            else:
                dev, channels, gain = sc.default_microphone(), 1, self.mic_gain
                self.devices[name] = dev.name
            log.info("Ton (%s) von: %s", name, self.devices[name])
            with dev.recorder(samplerate=SAMPLE_RATE, channels=channels) as rec:
                while self.running:
                    data = rec.record(numframes=None)
                    if len(data):
                        data = data.astype(np.float32)
                        if channels == 1:
                            data = np.repeat(data.reshape(-1, 1), 2, axis=1)   # Mono -> Stereo
                        if gain != 1.0:
                            data *= gain
                        q.put(data)
                    else:
                        time.sleep(0.005)
        except Exception as e:   # Ton kaputt -> Bild läuft trotzdem weiter (Stille)
            self.errors[name] = (L("Mikrofon: ", "Microphone: ") if name == "mic" else "") + str(e)
            log.exception("Ton-Aufnahme (%s) fehlgeschlagen", name)

    def _read_test_tone(self, q, freq):
        import numpy as np
        n, t = SAMPLE_RATE // 100, 0
        while self.running:
            v = 0.1 * np.sin(2 * np.pi * freq * (t + np.arange(n)) / SAMPLE_RATE, dtype=np.float32)
            t += n
            q.put(np.repeat(v.reshape(-1, 1), 2, axis=1))
            time.sleep(0.01)

    def _write(self):
        import numpy as np
        bufs = {name: np.zeros((0, 2), np.float32) for name in self.sources}
        start, written = time.perf_counter(), 0
        lag, cap = SAMPLE_RATE // 20, SAMPLE_RATE // 5   # 50 ms hinter der Uhr, max. 200 ms Stau
        try:
            while self.running:
                time.sleep(0.02)
                n = int((time.perf_counter() - start) * SAMPLE_RATE) - lag - written
                if n <= 0:
                    continue
                out = np.zeros((n, 2), np.float32)
                for name, q in self.sources.items():
                    parts = [bufs[name]]
                    while not q.empty():
                        parts.append(q.get_nowait())
                    buf = np.concatenate(parts)
                    take = buf[:n]
                    out[:len(take)] += take
                    buf = buf[n:]
                    bufs[name] = buf[-cap:] if len(buf) > cap else buf
                np.clip(out, -1.0, 1.0, out=out)
                self.sink.write(out.astype("<f4").tobytes())
                self.sink.flush()
                written += n
        except (OSError, ValueError):
            pass   # ffmpeg wurde beendet


# --- Aufnahme ----------------------------------------------------------------

class Recorder:
    def __init__(self, ffmpeg):
        self.ffmpeg = ffmpeg
        self.encoder = pick_encoder(ffmpeg)
        self.proc = None
        self.audio = None
        self.buffer = BUFFER_ROOT
        self.settings = None
        self.error = ""
        self.lock = threading.Lock()
        self.wanted = False
        log.info("Encoder: %s", self.encoder)
        threading.Thread(target=self._watchdog, daemon=True).start()

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, s):
        with self.lock:
            self._stop()
            self.settings, self.wanted, self.error = dict(s), True, ""
            # Jeder Start bekommt einen eigenen Ordner: Reste, die Windows noch sperrt,
            # stören so nicht mehr
            shutil.rmtree(BUFFER_ROOT, ignore_errors=True)
            self.buffer = BUFFER_ROOT / f"{os.getpid()}-{int(time.time() * 1000)}"
            self.buffer.mkdir(parents=True, exist_ok=True)
            fps = int(s["fps"])
            if TEST:
                video = ["-re", "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r={fps}"]
                vf = []
            else:
                # ddagrab = Desktop Duplication API von Windows, sparsam bei der CPU
                video = ["-thread_queue_size", "512", "-f", "lavfi",
                         "-i", f"ddagrab=framerate={fps}:draw_mouse=1"]
                vf = ["-vf", "hwdownload,format=bgra"]
            sound = s["audio"] or s["mic"]
            if sound:
                audio_in = ["-thread_queue_size", "1024", "-f", "f32le", "-ar", str(SAMPLE_RATE),
                            "-ac", "2", "-i", "pipe:0"]
                audio_out = ["-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
            else:
                audio_in, audio_out = [], ["-an"]
            wrap = int(s["clip_seconds"]) // SEGMENT_SECONDS + 5
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", *video, *audio_in, *vf,
                   *encoder_args(self.encoder, fps, QUALITY.get(s["quality"], "12M"), True),
                   *audio_out,
                   "-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
                   "-segment_wrap", str(wrap), "-reset_timestamps", "1",
                   str(self.buffer / "seg%03d.ts")]
            log.info("Aufnahme startet: %s", " ".join(cmd))
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE if sound else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
            threading.Thread(target=self._read_stderr, args=(self.proc,), daemon=True).start()
            if sound:
                self.audio = AudioPump(self.proc.stdin, pc=s["audio"], mic=s["mic"],
                                       mic_gain=int(s["mic_volume"]) / 100)
                self.audio.start()

    def stop(self):
        with self.lock:
            self.wanted = False
            self._stop()

    def _stop(self):
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _read_stderr(self, proc):
        for line in iter(proc.stderr.readline, b""):
            text = line.decode("utf-8", "replace").strip()
            if text:
                log.warning("ffmpeg: %s", text)
                self.error = text

    def _watchdog(self):
        """Startet ffmpeg neu, falls es abstürzt (z. B. Auflösungswechsel im Spiel)."""
        while True:
            time.sleep(3)
            if self.wanted and self.proc and self.proc.poll() is not None:
                log.warning("ffmpeg beendet (Code %s), starte neu", self.proc.returncode)
                try:
                    self.start(self.settings)
                except Exception:
                    log.exception("Neustart fehlgeschlagen")

    def save_clip(self, clip_dir, seconds):
        segs = sorted(self.buffer.glob("seg*.ts"), key=lambda p: p.stat().st_mtime)
        # Das jüngste Stück wird gerade noch geschrieben — weglassen, sonst kaputtes Ende
        segs = segs[:-1][-(seconds // SEGMENT_SECONDS):]
        if not segs:
            raise RuntimeError(L("Noch nichts aufgenommen — gleich nochmal probieren.",
                                  "Nothing recorded yet — try again in a moment."))
        clip_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        out = unique_path(clip_dir / f"Clip {stamp}.mp4")
        # Erst kopieren, damit der Ringpuffer sie währenddessen nicht überschreibt
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            for i, seg in enumerate(segs):
                dst = Path(tmp) / f"{i:03d}.ts"
                shutil.copyfile(seg, dst)
                lines.append(f"file '{dst.as_posix()}'")
            listfile = Path(tmp) / "list.txt"
            listfile.write_text("\n".join(lines), encoding="utf-8")
            r = run([self.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "concat",
                     "-safe", "0", "-i", str(listfile), "-c", "copy",
                     "-movflags", "+faststart", str(out)])
        if r.returncode != 0:
            raise RuntimeError(L("Clip fehlgeschlagen: ", "Clip failed: ") + r.stderr.strip()[-300:])
        log.info("Clip gespeichert: %s (%d s)", out, len(segs))
        return out


# --- Clip-Bibliothek ---------------------------------------------------------

class Library:
    def __init__(self, app):
        self.app = app
        self.durations = {}

    @property
    def dir(self):
        return Path(self.app.settings["clip_dir"])

    def path(self, name):
        p = self.dir / Path(name).name   # nur Dateinamen, keine Pfade von außen
        if p.suffix.lower() != ".mp4" or not p.is_file():
            raise FileNotFoundError(name)
        return p

    def duration(self, p):
        key = (p.name, p.stat().st_mtime)
        if key not in self.durations:
            r = run([self.app.ffprobe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(p)])
            try:
                self.durations[key] = float(r.stdout.strip())
            except ValueError:
                self.durations[key] = 0.0
        return self.durations[key]

    def list(self):
        if not self.dir.is_dir():
            return []
        files = sorted(self.dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime,
                 "duration": self.duration(p)} for p in files]

    def signature(self):
        """Ändert sich, sobald ein Clip dazukommt oder wegfällt — die Oberfläche lädt dann neu."""
        if not self.dir.is_dir():
            return "0"
        files = list(self.dir.glob("*.mp4"))
        return f"{len(files)}-{max((p.stat().st_mtime for p in files), default=0)}"

    def thumbnail(self, name):
        p = self.path(name)
        thumb = THUMB_DIR / f"{p.stem}_{int(p.stat().st_mtime)}.jpg"
        if not thumb.exists():
            at = min(1.0, self.duration(p) / 2)
            run([self.app.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(at),
                 "-i", str(p), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(thumb)])
        return thumb

    def strip(self, name):
        """Filmstreifen: STRIP_FRAMES Bilder nebeneinander in einem JPG (Hover-Vorschau, Schnittleiste)."""
        p = self.path(name)
        out = THUMB_DIR / f"{p.stem}_{int(p.stat().st_mtime)}_strip.jpg"
        if not out.exists():
            d = max(self.duration(p), 0.1)
            # nur Keyframes decodieren: ~0,4 s statt ~3 s pro Clip
            run([self.app.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-skip_frame", "nokey",
                 "-i", str(p), "-an", "-vf", f"fps={STRIP_FRAMES + 0.5}/{d:.3f},scale=240:-2,tile={STRIP_FRAMES}x1",
                 "-frames:v", "1", "-q:v", "5", str(out)])
        return out

    def copy(self, name, small):
        """Legt den Clip als Datei in die Zwischenablage (Strg+V in Discord, WhatsApp, Explorer)."""
        p = self.path(name)
        if small and p.stat().st_size > SHARE_LIMIT:
            p = self.shrink(p)
        lit = str(p).replace("'", "''")
        r = run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -LiteralPath '{lit}'"])
        if r.returncode != 0:
            raise RuntimeError(L("Zwischenablage: ", "Clipboard: ") + r.stderr.strip()[-200:])
        return p

    def shrink(self, src):
        """Encodiert eine Kopie, die unter das Discord-Limit passt. Liegt in %APPDATA%\\Clipper\\teilen."""
        SHARE_DIR.mkdir(exist_ok=True)
        for old in sorted(SHARE_DIR.glob("*.mp4"), key=lambda f: f.stat().st_mtime)[:-4]:
            old.unlink(missing_ok=True)   # nur die letzten paar behalten
        out = SHARE_DIR / f"{src.stem} (klein).mp4"
        d = max(self.duration(src), 1)
        audio = 96
        for factor in (0.92, 0.75):   # zweiter Versuch, falls die Datei doch zu groß wird
            video = int(SHARE_LIMIT * 8 / 1000 / d * factor) - audio
            if video < 200:
                raise ValueError(L("Clip ist zu lang für 10 MB. Erst kürzen.", "Clip is too long for 10 MB. Trim it first."))
            height = 1080 if video >= 4000 else 720 if video >= 1500 else 480
            fps = 60 if video >= 4000 else 30
            r = run([self.app.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                     "-vf", f"scale=-2:'min({height},ih)'", "-r", str(fps),
                     *encoder_args(self.app.recorder.encoder, fps, f"{video}k", False),
                     "-c:a", "aac", "-b:a", f"{audio}k", "-movflags", "+faststart", str(out)])
            if r.returncode != 0:
                raise RuntimeError(L("Verkleinern fehlgeschlagen: ", "Shrinking failed: ") + r.stderr.strip()[-300:])
            if out.stat().st_size <= SHARE_LIMIT:
                return out
        raise RuntimeError(L("Clip ließ sich nicht unter 10 MB bringen.", "Could not get the clip under 10 MB."))

    def has_audio(self, p):
        r = run([self.app.ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=index", "-of", "csv=p=0", str(p)])
        return bool(r.stdout.strip())

    def trim(self, name, segments, replace=False):
        """Schneidet die Teile [(start, ende), …] aus dem Clip und hängt sie aneinander."""
        src = self.path(name)
        segs = [(max(0.0, float(a)), float(b)) for a, b in segments if float(b) - float(a) >= 0.05]
        if not segs or sum(b - a for a, b in segs) < 0.3:
            raise ValueError(L("Auswahl ist zu kurz.", "Selection is too short."))
        s = self.app.settings
        audio = self.has_audio(src)
        # trim/atrim + concat: bildgenau, auch für mehrere Teile
        parts, labels = [], ""
        for i, (a, b) in enumerate(segs):
            parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
            labels += f"[v{i}]"
            if audio:
                parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
                labels += f"[a{i}]"
        parts.append(f"{labels}concat=n={len(segs)}:v=1:a={int(audio)}[v]" + ("[a]" if audio else ""))
        tmp = src.with_name(f".{src.stem}.schnitt.mp4")
        r = run([self.app.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                 "-filter_complex", ";".join(parts), "-map", "[v]", *(["-map", "[a]"] if audio else []),
                 *encoder_args(self.app.recorder.encoder, int(s["fps"]),
                               QUALITY.get(s["quality"], "12M"), False),
                 "-g", str(int(s["fps"])),   # Keyframe pro Sekunde: schneller Filmstreifen, flüssiges Spulen
                 *(["-c:a", "aac", "-b:a", "192k"] if audio else []),
                 "-movflags", "+faststart", str(tmp)])
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(L("Schneiden fehlgeschlagen: ", "Cutting failed: ") + r.stderr.strip()[-300:])
        if replace:
            retry(lambda: os.replace(tmp, src))
            return src
        out = unique_path(src.with_name(f"{src.stem} (geschnitten).mp4"))
        os.replace(tmp, out)
        return out

    def rename(self, name, new):
        src = self.path(name)
        new = re.sub(r'[<>:"/\\|?*]', "", new).strip().removesuffix(".mp4").strip()
        if not new:
            raise ValueError(L("Name ist leer.", "Name is empty."))
        dst = src.with_name(new + ".mp4")
        if dst.exists() and dst != src:
            raise ValueError(L("Es gibt schon einen Clip mit diesem Namen.", "A clip with this name already exists."))
        retry(lambda: os.replace(src, dst))
        return dst

    def delete(self, name):
        p = self.path(name)
        try:
            from send2trash import send2trash   # in den Papierkorb statt endgültig weg
            retry(lambda: send2trash(str(p)))
        except ImportError:
            retry(p.unlink)

    def reveal(self, name=None):
        if not IS_WIN:
            return
        if name:
            subprocess.Popen(["explorer", f"/select,{self.path(name)}"])
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            os.startfile(self.dir)


def chime(ok=True):
    """Leiser, weicher Zwei-Ton (aufsteigend = gespeichert, absteigend = Fehler) als WAV."""
    path = DATA_DIR / ("chime_ok.wav" if ok else "chime_err.wav")
    if path.exists():
        return path
    import wave
    rate, length = 44100, 0.5
    notes = [(1046.5, 0.0), (1568.0, 0.075)] if ok else [(659.3, 0.0), (493.9, 0.09)]
    frames = bytearray()
    for i in range(int(rate * length)):
        t, v = i / rate, 0.0
        for freq, start in notes:
            dt = t - start
            if dt >= 0:
                env = min(1.0, dt / 0.004) * math.exp(-dt / 0.085)   # 4 ms Anschlag, schnelles Ausklingen
                v += env * (math.sin(2 * math.pi * freq * dt) + 0.12 * math.sin(4 * math.pi * freq * dt))
        frames += struct.pack("<h", int(max(-1, min(1, v * 0.11)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return path


# --- App -----------------------------------------------------------------------

class App:
    def __init__(self, ffmpeg, ffprobe):
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe
        self.settings = load_settings()
        self.recorder = Recorder(ffmpeg)
        self.library = Library(self)
        self.hotkey_handle = None
        self.hotkey_error = ""
        self.last_clip = None
        self.clip_lock = threading.Lock()
        self.tray = None

    def start(self):
        self.recorder.start(self.settings)
        self.bind_hotkey()
        if self.settings["autostart"] and not TEST:   # Eintrag erneuern (neu installiert, anderer Ordner)
            set_autostart(True)

    def bind_hotkey(self):
        if TEST:
            return
        try:
            import keyboard
            if self.hotkey_handle is not None:
                keyboard.remove_hotkey(self.hotkey_handle)
            self.hotkey_handle = keyboard.add_hotkey(
                self.settings["hotkey"], lambda: threading.Thread(target=self.clip_now, daemon=True).start())
            self.hotkey_error = ""
        except Exception as e:
            self.hotkey_error = str(e)
            log.exception("Hotkey konnte nicht gesetzt werden")

    def clip_now(self):
        if not self.clip_lock.acquire(blocking=False):   # Doppeldruck ignorieren
            return None
        try:
            out = self.recorder.save_clip(self.library.dir, int(self.settings["clip_seconds"]))
            self.last_clip = {"name": out.name, "time": time.time()}
            self.notify(L("Clip gespeichert", "Clip saved"), out.name, True)
            return out
        except Exception as e:
            log.exception("Clip fehlgeschlagen")
            self.notify(L("Clip fehlgeschlagen", "Clip failed"), str(e), False)
            raise
        finally:
            self.clip_lock.release()

    def notify(self, title, text, ok):
        if IS_WIN and self.settings.get("sound", True):
            try:
                import winsound
                winsound.PlaySound(str(chime(ok)), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception:
                log.exception("Ton konnte nicht abgespielt werden")
        if self.tray:
            try:   # Windows-Benachrichtigung ohne eigenen Systemton (NIIF_NOSOUND)
                from pystray._util import win32
                self.tray._message(win32.NIM_MODIFY, win32.NIF_INFO, szInfo=text,
                                   szInfoTitle=title, dwInfoFlags=0x10)
            except Exception:
                try:
                    self.tray.notify(text, title)
                except Exception:
                    pass

    def update_settings(self, new):
        old = dict(self.settings)
        s = dict(self.settings)
        s["clip_seconds"] = max(5, min(300, int(new.get("clip_seconds", s["clip_seconds"]))))
        s["fps"] = 30 if int(new.get("fps", s["fps"])) <= 30 else 60
        s["quality"] = new.get("quality", s["quality"]) if new.get("quality") in QUALITY else s["quality"]
        s["audio"] = bool(new.get("audio", s["audio"]))
        s["mic"] = bool(new.get("mic", s["mic"]))
        s["mic_volume"] = max(25, min(300, int(new.get("mic_volume", s["mic_volume"]))))
        s["hotkey"] = (new.get("hotkey") or s["hotkey"]).strip().lower()
        s["clip_dir"] = (new.get("clip_dir") or s["clip_dir"]).strip()
        s["autostart"] = bool(new.get("autostart", s["autostart"]))
        s["sound"] = bool(new.get("sound", s["sound"]))
        s["theme"] = new["theme"] if new.get("theme") in ("auto", "light", "dark") else s["theme"]
        self.settings = s
        SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), "utf-8")
        if any(s[k] != old[k] for k in ("clip_seconds", "fps", "quality", "audio", "mic", "mic_volume")):
            self.recorder.start(s)
        if s["hotkey"] != old["hotkey"]:
            self.bind_hotkey()
        if s["autostart"] != old["autostart"]:
            set_autostart(s["autostart"])
        if s["theme"] != old["theme"]:
            style_titlebar(s["theme"])
        return s

    def status(self):
        rec = self.recorder
        audio_error = rec.audio.error if rec.audio else ""
        return {
            "recording": rec.running,
            "encoder": rec.encoder,
            "error": "" if rec.running else rec.error,
            "audio_error": audio_error,
            "lang": LANG,
            "audio_devices": rec.audio.devices if rec.audio else {},
            "hotkey_error": self.hotkey_error,
            "settings": self.settings,
            "library": self.library.signature(),
            "last_clip": self.last_clip,
        }

    def quit(self):
        log.info("Clipper beendet")
        self.recorder.stop()
        shutil.rmtree(BUFFER_ROOT, ignore_errors=True)
        if self.tray:
            self.tray.stop()
        os._exit(0)


def set_autostart(on):
    if not IS_WIN:
        return
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Clipper.vbs"
    if not on:
        startup.unlink(missing_ok=True)
        return
    if FROZEN:   # Clipper.exe startet sich selbst
        cmd = f'""{sys.executable}"" --hidden'
    else:
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = pyw if pyw.exists() else Path(sys.executable)
        cmd = f'""{exe}"" ""{Path(__file__).resolve()}"" --hidden'
    startup.write_text('Set sh = CreateObject("WScript.Shell")\n'   # \n wird unter Windows zu \r\n
                       f'sh.Run "{cmd}", 0, False\n', encoding="utf-8")


WINDOW = None   # eigenes Fenster (pywebview/WebView2), sonst Edge im App-Modus
WINDOW_HWND = 0


def windows_dark():
    """True, wenn Windows für Apps den dunklen Modus nutzt."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def style_titlebar(theme):
    """Titelleiste des Fensters hell oder dunkel, passend zum Erscheinungsbild der App."""
    if WINDOW is None or not IS_WIN:
        return
    try:
        import ctypes
        dark = theme == "dark" or (theme == "auto" and windows_dark())
        hwnd = WINDOW_HWND or WINDOW.native.Handle.ToInt64()
        ctypes.windll.dwmapi.DwmSetWindowAttribute(   # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.c_void_p(hwnd), 20, ctypes.byref(ctypes.c_int(int(dark))), 4)
    except Exception:
        log.exception("Titelleiste konnte nicht angepasst werden")


def run_window(app, hidden):
    """Zeigt die Oberfläche im eigenen Fenster. In der Taskleiste steht dann „Clipper“ statt Edge."""
    global WINDOW
    try:
        import webview
    except ImportError:
        log.warning("pywebview fehlt, nutze Edge")
        if not hidden:
            open_window()
        return run_tray(app)
    threading.Thread(target=run_tray, args=(app,), daemon=True).start()
    theme = app.settings.get("theme", "auto")
    dark = theme == "dark" or (theme == "auto" and windows_dark())
    WINDOW = webview.create_window("Clipper", f"http://127.0.0.1:{PORT}/", width=1280, height=820,
                                   min_size=(820, 560), hidden=hidden,
                                   background_color="#000000" if dark else "#f5f5f7")

    def on_closing():   # X schließt nur das Fenster, die Aufnahme läuft im Tray weiter
        WINDOW.hide()
        return False

    WINDOW.events.closing += on_closing
    def on_shown():
        global WINDOW_HWND
        try:
            WINDOW_HWND = WINDOW.native.Handle.ToInt64()
        except Exception:
            pass
        style_titlebar(app.settings.get("theme", "auto"))

    WINDOW.events.shown += on_shown
    webview.start(private_mode=False, storage_path=str(DATA_DIR / "webview"))
    app.quit()


def open_window():
    if WINDOW is not None:
        WINDOW.show()
        WINDOW.restore()
        return
    url = f"http://127.0.0.1:{PORT}/"
    if IS_WIN:   # Notlösung: Edge im App-Modus = eigenes Fenster ohne Adressleiste
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            edge = Path(base or "") / "Microsoft/Edge/Application/msedge.exe"
            if base and edge.exists():
                subprocess.Popen([str(edge), f"--app={url}", "--window-size=1280,820",
                                  f"--user-data-dir={DATA_DIR / 'fenster'}"],
                                 cwd=DATA_DIR)   # sonst sperrt Edge den Programmordner beim Neu-Bauen
                return
    webbrowser.open(url)


# --- HTTP --------------------------------------------------------------------

APP = None


class Server(ThreadingHTTPServer):
    """Belegt den Port exklusiv. Mit SO_REUSEADDR (Python-Standard) dürfte unter Windows ein
    zweites Clipper denselben Port öffnen und liefe dann doppelt."""
    allow_reuse_address = False

    def server_bind(self):
        if IS_WIN:
            import socket
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, ctype):
        size = path.stat().st_size
        start, end = 0, size - 1
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m[1] or m[2]):   # Range-Anfragen braucht der Player zum Spulen
            if m[1]:
                start, end = int(m[1]), int(m[2]) if m[2] else size - 1
            else:
                start = max(0, size - int(m[2]))
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except (ConnectionError, OSError):
            pass

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.split("/", 2)
        try:
            if url.path == "/":
                return self.send_file(HERE / "ui.html", "text/html; charset=utf-8")
            if url.path in ("/icon.png", "/favicon.ico"):   # Logo für Fenstertitel und Taskleiste
                icon = DATA_DIR / "icon.png"
                if not icon.exists():
                    from logo import make_logo
                    make_logo(256).save(icon)
                return self.send_file(icon, "image/png")
            if url.path == "/api/status":
                return self.send_json(APP.status())
            if url.path == "/api/clips":
                return self.send_json(APP.library.list())
            if parts[1] == "media":
                return self.send_file(APP.library.path(unquote(parts[2])), "video/mp4")
            if parts[1] == "thumb":
                return self.send_file(APP.library.thumbnail(unquote(parts[2])), "image/jpeg")
            if parts[1] == "strip":
                return self.send_file(APP.library.strip(unquote(parts[2])), "image/jpeg")
            self.send_json({"error": L("nicht gefunden", "not found")}, 404)
        except FileNotFoundError:
            self.send_json({"error": L("nicht gefunden", "not found")}, 404)

    def do_POST(self):
        # Eigener Header: fremde Webseiten können ihn nicht setzen (CORS), also nichts löschen
        if self.headers.get("X-Clipper") != "1":
            return self.send_json({"error": L("verboten", "forbidden")}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            route = urlparse(self.path).path
            lib = APP.library
            if route == "/api/clip":
                out = APP.clip_now()
                return self.send_json({"name": out.name if out else None})
            if route == "/api/trim":
                segs = body.get("segments") or [(body["start"], body["end"])]
                out = lib.trim(body["name"], segs, body.get("replace", False))
                return self.send_json({"name": out.name})
            if route == "/api/rename":
                return self.send_json({"name": lib.rename(body["name"], body["new"]).name})
            if route == "/api/delete":
                lib.delete(body["name"])
                return self.send_json({"ok": True})
            if route == "/api/show":   # zweiter Start von Clipper.exe
                open_window()
                return self.send_json({"ok": True})
            if route == "/api/copy":
                out = lib.copy(body["name"], bool(body.get("small")))
                return self.send_json({"file": out.name, "size": out.stat().st_size})
            if route == "/api/reveal":
                lib.reveal(body.get("name"))
                return self.send_json({"ok": True})
            if route == "/api/settings":
                return self.send_json(APP.update_settings(body))
            if route == "/api/quit":
                self.send_json({"ok": True})
                threading.Timer(0.3, APP.quit).start()
                return
            self.send_json({"error": L("nicht gefunden", "not found")}, 404)
        except FileNotFoundError:
            self.send_json({"error": L("Clip nicht gefunden.", "Clip not found.")}, 404)
        except Exception as e:
            log.exception("Fehler bei %s", self.path)
            self.send_json({"error": str(e)}, 400)


# --- Start ---------------------------------------------------------------------

def run_tray(app):
    try:
        import pystray
        from logo import make_logo
    except ImportError:
        log.warning("pystray fehlt, kein Tray-Icon")
        while True:
            time.sleep(3600)
    img = make_logo(64)
    menu = pystray.Menu(
        # Texte als Funktion: pystray fragt sie bei jedem Öffnen neu ab (Sprachwechsel)
        pystray.MenuItem(lambda item: L("Clipper öffnen", "Open Clipper"), lambda: open_window(), default=True),
        pystray.MenuItem(lambda item: L("Clip aufnehmen", "Record clip"),
                         lambda: threading.Thread(target=app.clip_now, daemon=True).start()),
        pystray.MenuItem(lambda item: L("Beenden", "Quit"), lambda: app.quit()),
    )
    app.tray = pystray.Icon("Clipper", img, L("Clipper — nimmt auf", "Clipper — recording"), menu)
    app.tray.run()


def main():
    global TEST, APP
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="Testbild + Testton statt Bildschirm")
    ap.add_argument("--hidden", action="store_true", help="ohne Fenster starten (Autostart)")
    args = ap.parse_args()
    TEST = args.test
    if not TEST and not IS_WIN:
        sys.exit("Bildschirmaufnahme gibt es nur unter Windows. Zum Testen: --test")

    ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
    if not ffmpeg or not ffprobe:
        message_box(L("ffmpeg nicht gefunden.\n\nInstallieren mit:  winget install Gyan.FFmpeg\n"
                      "Danach Clipper neu starten.",
                      "ffmpeg not found.\n\nInstall it with:  winget install Gyan.FFmpeg\n"
                      "Then start Clipper again."))
        sys.exit(1)

    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError:   # läuft schon -> das laufende Clipper soll sein Fenster zeigen
        try:
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/show", data=b"{}", method="POST",
                headers={"X-Clipper": "1", "Content-Type": "application/json"}), timeout=3)
        except OSError:
            open_window()
        return

    log.info("Clipper startet (Test=%s)", TEST)
    kill_orphans()
    APP = App(ffmpeg, ffprobe)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    APP.start()
    if TEST:
        print(f"Testmodus läuft auf http://127.0.0.1:{PORT}/ — Strg+C beendet.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            APP.quit()
    else:
        run_window(APP, args.hidden)


if __name__ == "__main__":
    main()
