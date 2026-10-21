<p align="center"><img src="assets/logo.png" width="96" alt="Clipper-Logo"></p>

<h1 align="center">Clipper</h1>

<h3 align="center">Du willst unbedingt das Clipping-Tool aus Discord?<br>Hier bekommst du es kostenlos.</h3>

<p align="center">Drück <b>Alt+R</b>, und die letzten 30 Sekunden sind gespeichert, mit Spiel-Ton, deinen Freunden aus dem Call und deinem Mikrofon.<br>
Ohne Nitro, ohne Konto, ohne Cloud.</p>

<p align="center"><a href="../../releases/latest/download/Clipper-Setup.exe"><b>⬇ Kostenlos herunterladen</b></a></p>

<p align="center"><i>English: Want Discord's clipping tool? Get it here for free. Press Alt+R to save the last 30 seconds with game audio, your friends on the call and your mic. No Nitro, no account, no cloud.</i></p>

<p align="center"><sub>Clipper ist ein unabhängiges Projekt und hat nichts mit Discord zu tun. / Not affiliated with Discord.</sub></p>

---

## Was Clipper kann

- **Replay-Puffer:** nimmt dauerhaft im Hintergrund auf. Mit **Alt+R** wird ein Clip mit den letzten 15 s bis 5 min gespeichert. Das Speichern ist sofort fertig, weil nichts neu encodiert wird.
- **Ton von beiden Seiten:** PC-Ton (Spiel, Discord-Freunde, Musik) und dein Mikrofon werden zusammengemischt. Beides lässt sich einzeln abschalten, die Mikrofon-Lautstärke ist einstellbar.
- **Bibliothek:** alle Clips als Vorschaubilder. Fährst du mit der Maus darüber, spult der Clip mit.
- **Editor wie Clipchamp:** Zeitleiste mit Lineal und Filmstreifen. Mit der Schere (`S`) teilst du, mit `Entf` entfernst du Teile, an den Rändern kürzt du. Dazu Zoom und Rückgängig. Gespeichert wird bildgenau als neuer Clip, das Original bleibt.
- **Teilen:** Ein Klick auf „Kopieren“, dann mit Strg+V in Discord, WhatsApp oder den Explorer einfügen. „Für Discord“ verkleinert den Clip vorher auf unter 10 MB.
- **Schnell und sparsam:** nutzt die Grafikkarte zum Encodieren (NVIDIA NVENC, AMD AMF, Intel Quick Sync, sonst CPU).
- **Apple-Look** mit hellem und dunklem Modus. Clipper sitzt im Tray und kann mit Windows starten.
- **Deutsch und Englisch:** Die Sprache richtet sich automatisch nach Windows und lässt sich in den Einstellungen festlegen. *(English: the language follows Windows automatically.)*

## Installation

<p><a href="../../releases/latest/download/Clipper-Setup.exe"><b>⬇ Clipper-Setup.exe herunterladen</b></a> (ca. 25 MB)</p>

1. `Clipper-Setup.exe` herunterladen und doppelklicken.
2. „Installieren“ klicken. Adminrechte brauchst du nicht. Fehlt ffmpeg (wird für die Aufnahme gebraucht), installiert das Setup es gleich mit.
3. Fertig: Clipper liegt im Startmenü und auf Wunsch auf dem Desktop. Deinstallieren geht über Windows-Einstellungen → Apps. Deine Clips bleiben dabei erhalten.

<details><summary>Ohne Installation (portable Zip)</summary>

Unter [Releases](../../releases/latest) die Datei `Clipper-windows.zip` laden, entpacken und `Clipper.exe` starten. ffmpeg musst du dann selbst installieren: `winget install Gyan.FFmpeg`.
</details>

Unten rechts im Tray erscheint das Clipper-Logo. Das Fenster kannst du schließen, die Aufnahme läuft weiter. Mit einem Doppelklick aufs Tray-Icon öffnet es sich wieder.

> Windows SmartScreen warnt eventuell beim Setup, weil es nicht signiert ist. Dann auf „Weitere Informationen“ und „Trotzdem ausführen“ klicken.

## Bedienung

| Was | Wie |
| --- | --- |
| Clip speichern | **Alt+R** (änderbar) oder „Clip aufnehmen“ |
| Clip ansehen und schneiden | Clip anklicken |
| Teilen | `S` oder Schere |
| Teil entfernen | Teil anklicken, `Entf` |
| Abspielen / Pause | Leertaste |
| Bild für Bild | `←` `→` (mit Umschalt: 1 Sekunde) |
| Rückgängig | `Strg+Z` |
| Zoom | `Strg` + Mausrad |

Clips landen in `Videos\Clips`. Den Ordner kannst du in den Einstellungen ändern. Einstellungen und Log liegen unter `%APPDATA%\Clipper`.

## Gut zu wissen

- Das Mikrofon läuft immer mit, auch wenn du in Discord stummgeschaltet bist.
- Bei Spielen im **exklusiven Vollbild** kann das Bild schwarz bleiben. Stell das Spiel dann auf „Randloses Fenster“ um.
- Aufgenommen wird nur der Hauptmonitor und das Ausgabegerät, das beim Start Standard war.
- Läuft ein Spiel als Administrator, kommt Alt+R dort eventuell nicht an. Dann Clipper auch als Administrator starten.

## Selbst bauen

Dafür brauchst du Python 3.10 oder neuer und ffmpeg.

```
pip install -r requirements.txt
python clipper.py          # direkt starten
python build.py            # Clipper.exe bauen und installieren (Desktop + Startmenü)
python build.py --setup    # zusätzlich Clipper-Setup.exe bauen (braucht Inno Setup: winget install JRSoftware.InnoSetup)
python clipper.py --test   # Testbild und Testton, läuft auch ohne Windows
```

**So funktioniert es:** ffmpeg nimmt per `ddagrab` (Desktop Duplication API) auf und schreibt 1-Sekunden-Stücke in einen Ringpuffer. Ein Clip hängt die letzten Stücke ohne neu Encodieren aneinander. Den Ton liefert WASAPI-Loopback, das Mikrofon kommt über das Paket `soundcard` dazu. Beides wird in Python im Takt der Uhr gemischt, damit es synchron zum Bild bleibt. Die Oberfläche ist eine HTML-Seite, ausgeliefert von einem kleinen lokalen Server auf `127.0.0.1` und angezeigt in einem eigenen Fenster (pywebview mit WebView2).

## Lizenz

[MIT](LICENSE). Frei nutzbar, auch zum Verändern und Weitergeben.
