@echo off
rem Installiert fehlende Pakete und startet Clipper im Hintergrund (Tray-Icon unten rechts).
cd /d "%~dp0"
echo Clipper wird vorbereitet ...
python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo Installation fehlgeschlagen - siehe Meldung oben.
  pause
  exit /b 1
)
start "" pythonw clipper.py
