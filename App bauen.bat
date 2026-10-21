@echo off
rem Baut Clipper.exe neu und installiert sie (Desktop + Startmenue). Nach Code-Aenderungen erneut ausfuehren.
cd /d "%~dp0"
python build.py
pause
