<p align="center"><img src="assets/logo.png" width="96" alt="Clipper logo"></p>

<h1 align="center">Clipper</h1>

<h3 align="center">Want Discord's clipping tool that badly?<br>Get it here for free.</h3>

<p align="center">Press <b>Alt+R</b> and the last 30 seconds are saved, with game audio, your friends on the call and your mic.<br>
No Nitro, no account, no cloud.</p>

<p align="center"><a href="../../releases/latest/download/Clipper-Setup.exe"><b>⬇ Download for free</b></a></p>

<p align="center"><sub>Clipper is an independent project and is not affiliated with Discord.</sub></p>

---

## What Clipper does

- **Replay buffer:** Clipper records in the background all the time. Press **Alt+R** to save the last 15 seconds to 5 minutes as a clip. Saving is instant because nothing gets re-encoded.
- **Screenshots too:** press **Alt+F1** to save a full-resolution screenshot. A small preview pops up in the top right, even in games, without taking focus away from the game and without showing up in your clips. Click the preview to open the screenshot in Clipper. Screenshots appear next to your clips, and "Copy" puts the image on the clipboard so you can paste it anywhere.
- **Both sides of the call:** desktop audio (game, friends on Discord, music) and your microphone are mixed together. You can turn each one off and adjust the mic volume.
- **Library:** all your clips as thumbnails. Hover over one and it scrubs through the clip.
- **Editor like Clipchamp:** a timeline with ruler and filmstrip. Split with the scissors (`S`), remove parts with `Del`, drag the edges to trim, zoom, undo. The result is saved frame-accurately as a new clip, and the original stays.
- **Sharing:** click "Copy", then paste with Ctrl+V into Discord, WhatsApp or Explorer. "For Discord" shrinks the clip to under 10 MB first.
- **Fast and light:** uses your graphics card for encoding (NVIDIA NVENC, AMD AMF, Intel Quick Sync, otherwise the CPU).
- **Clean look** with light and dark mode. Clipper lives in the tray and can start with Windows.

## Installation

1. Download [`Clipper-Setup.exe`](../../releases/latest/download/Clipper-Setup.exe) and double-click it.
2. Click "Install". No admin rights needed. If ffmpeg (needed for recording) is missing, the setup installs it for you.
3. Done. Clipper is in your Start menu and, if you want, on your desktop. Uninstall it via Windows Settings → Apps. Your clips are kept.

<details><summary>Without installing (portable zip)</summary>

Download `Clipper-windows.zip` from [Releases](../../releases/latest), unzip it and run `Clipper.exe`. You need to install ffmpeg yourself: `winget install Gyan.FFmpeg`.
</details>

The Clipper logo appears in the tray at the bottom right. You can close the window and recording keeps running. Double-click the tray icon to open it again.

> Windows SmartScreen may warn you when running the setup because it isn't signed. Click "More info" and then "Run anyway".

## How to use it

| What | How |
| --- | --- |
| Save a clip | **Alt+R** (changeable) or "Record clip" |
| Take a screenshot | **Alt+F1** (changeable) or tray menu → "Take screenshot" |
| Watch and edit a clip | Click the clip |
| Split | `S` or the scissors |
| Remove a part | Click the part, then `Del` |
| Play / pause | Space |
| Frame by frame | `←` `→` (with Shift: 1 second) |
| Undo | `Ctrl+Z` |
| Zoom | `Ctrl` + scroll wheel |

Clips and screenshots are saved to `Videos\Clips`. You can change the folder in the settings. Settings and the log are in `%APPDATA%\Clipper`.

## Good to know

- The microphone is always recorded, even when you're muted in Discord.
- Games in **exclusive fullscreen** may record as a black screen, and the screenshot preview can't appear on top of them. Switch the game to "Borderless window".
- Clipper records only the main monitor and the audio device that was the default when it started.
- If a game runs as administrator, Alt+R may not reach it. Run Clipper as administrator too.

## Building it yourself

You need Python 3.10 or newer and ffmpeg.

```
pip install -r requirements.txt
python clipper.py          # run directly
python build.py            # build Clipper.exe and install it (desktop + Start menu)
python build.py --setup    # also build Clipper-Setup.exe (needs Inno Setup: winget install JRSoftware.InnoSetup)
python clipper.py --test   # test picture and test tone, also runs without Windows
```

**How it works:** ffmpeg captures the screen via `ddagrab` (Desktop Duplication API) and writes 1-second chunks into a ring buffer. A clip joins the latest chunks without re-encoding. Desktop audio comes from WASAPI loopback, the microphone is added via the `soundcard` package. Python mixes both in step with the clock so they stay in sync with the picture. The interface is an HTML page served by a small local server on `127.0.0.1` and shown in its own window (pywebview with WebView2).

## License

[MIT](LICENSE). Free to use, change and share.
