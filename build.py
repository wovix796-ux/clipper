"""Baut Clipper.exe und installiert sie mit StartmenÃ¼- und Desktop-VerknÃ¼pfung.

Aufruf: python build.py   (oder "App bauen.bat" doppelklicken)
        python build.py --setup   baut zusÃ¤tzlich Clipper-Setup.exe zum Weitergeben (Inno Setup)
Ziel:   %LOCALAPPDATA%\\Programs\\Clipper\\Clipper.exe
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = Path(os.environ.get("TEMP", HERE)) / "clipper_build"
TARGET = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Clipper"
EXE = TARGET / "Clipper.exe"
APP_VERSION = (1, 3, 1, 0)

# Versionsinfo der exe: Windows zeigt FileDescription z. B. im Taskleisten-MenÃ¼ als Programmnamen
VERSION_INFO = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={APP_VERSION}, prodvers={APP_VERSION}),
  kids=[StringFileInfo([StringTable('040704b0', [
    StringStruct('CompanyName', 'wovix796-ux'),
    StringStruct('FileDescription', 'Clipper'),
    StringStruct('FileVersion', '{".".join(map(str, APP_VERSION[:3]))}'),
    StringStruct('InternalName', 'Clipper'),
    StringStruct('OriginalFilename', 'Clipper.exe'),
    StringStruct('ProductName', 'Clipper'),
    StringStruct('ProductVersion', '{".".join(map(str, APP_VERSION[:3]))}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])]
)
"""


def sh(*cmd):
    print(">", " ".join(map(str, cmd)))
    subprocess.run(list(map(str, cmd)), check=True)


def make_icon(path):
    sys.path.insert(0, str(HERE))
    from logo import make_logo
    make_logo(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def shortcut(lnk):
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
          f"$s.TargetPath = '{EXE}'; $s.WorkingDirectory = '{TARGET}'; "
          f"$s.IconLocation = '{EXE},0'; $s.Description = 'Clipper - letzte 30 s speichern'; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)


def main():
    sh(sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
       "-r", HERE / "requirements.txt", "pyinstaller")
    BUILD.mkdir(exist_ok=True)
    icon = BUILD / "clipper.ico"
    make_icon(icon)
    version = BUILD / "version.txt"
    version.write_text(VERSION_INFO, encoding="utf-8")
    sh(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
       "--name", "Clipper", "--icon", icon, "--version-file", version,
       "--add-data", f"{HERE / 'ui.html'};.",
       "--collect-all", "soundcard", "--hidden-import", "pystray._win32",
       "--distpath", BUILD / "dist", "--workpath", BUILD / "work", "--specpath", BUILD,
       HERE / "clipper.py")

    # laufendes Clipper beenden, sonst sind die Dateien gesperrt
    subprocess.run(["taskkill", "/f", "/im", "Clipper.exe"], capture_output=True)
    # Nur den Inhalt lÃ¶schen: Den Ordner selbst kann ein offenes Fenster als Arbeitsordner sperren.
    TARGET.mkdir(parents=True, exist_ok=True)
    for _ in range(60):   # Windows (und der Virenscanner) geben die Dateien erst kurz danach frei
        try:
            for p in TARGET.iterdir():
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            break
        except PermissionError:
            time.sleep(0.5)
    else:
        sys.exit(f"{TARGET} ist noch gesperrt. Clipper beenden und nochmal versuchen.")
    shutil.copytree(BUILD / "dist" / "Clipper", TARGET, dirs_exist_ok=True)

    shell_dirs = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')"],
        capture_output=True, text=True, check=True).stdout.split("\n")
    desktop, programs = (Path(p.strip()) for p in shell_dirs[:2])
    shortcut(desktop / "Clipper.lnk")
    shortcut(programs / "Clipper.lnk")

    # Autostart auf die exe umstellen, falls er schon an war
    vbs = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/Clipper.vbs"
    if vbs.exists():
        vbs.write_text('Set sh = CreateObject("WScript.Shell")\n'
                       f'sh.Run """{EXE}"" --hidden", 0, False\n', encoding="utf-8")

    print(f"\nFertig: {EXE}\nVerknÃ¼pfungen auf dem Desktop und im StartmenÃ¼ angelegt.")
    if "--setup" in sys.argv:
        build_setup(icon)


def build_setup(icon):
    """Baut Clipper-Setup.exe mit Inno Setup (winget install JRSoftware.InnoSetup)."""
    iscc = next((p for p in [Path(os.environ["LOCALAPPDATA"]) / "Programs/Inno Setup 6/ISCC.exe",
                             Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6/ISCC.exe",
                             Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6/ISCC.exe"]
                 if p.exists()), None)
    if not iscc:
        sys.exit("Inno Setup fehlt: winget install JRSoftware.InnoSetup")
    sh(iscc, "/Q", f"/DAppVersion={'.'.join(map(str, APP_VERSION[:3]))}",
       f"/DSourceDir={BUILD / 'dist' / 'Clipper'}", f"/DIconFile={icon}", f"/DOutDir={BUILD}",
       HERE / "clipper.iss")
    print(f"Setup: {BUILD / 'Clipper-Setup.exe'}")


if __name__ == "__main__":
    main()
