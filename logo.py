"""Clipper-Logo: Replay-Pfeil um ein Play-Dreieck auf orange-pinkem Verlauf.

Wird für das Tray-Icon (clipper.py) und das App-Icon (build.py) gezeichnet.
Die Koordinaten passen zum SVG in ui.html (viewBox 0 0 1024 1024).
"""
import math

from PIL import Image, ImageDraw

TOP, BOTTOM = (255, 122, 69), (233, 30, 99)
CX = CY = 512
R, STROKE = 250, 74
HEAD, TAIL = -90, 225   # Pfeilspitze oben, zeigt nach links (gegen den Uhrzeigersinn); Lücke oben links


def arrow_head():
    a = math.radians(HEAD)
    px, py = CX + R * math.cos(a), CY + R * math.sin(a)
    tx, ty = math.sin(a), -math.cos(a)    # Tangente gegen den Uhrzeigersinn
    nx, ny = math.cos(a), math.sin(a)     # nach außen
    back = 8
    return [(px + tx * 112, py + ty * 112),
            (px + nx * 92 - tx * back, py + ny * 92 - ty * back),
            (px - nx * 92 - tx * back, py - ny * 92 - ty * back)]


PLAY = [(470, 418), (470, 606), (622, 512)]


def make_logo(size=256):
    s = 1024
    grad = Image.new("RGB", (2, 2))
    grad.putdata([TOP, TOP, BOTTOM, BOTTOM])
    grad = grad.resize((s, s), Image.BILINEAR)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=230, fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.arc((CX - R - STROKE / 2, CY - R - STROKE / 2, CX + R + STROKE / 2, CY + R + STROKE / 2),
          start=HEAD, end=TAIL, fill="white", width=STROKE)
    d.polygon(arrow_head(), fill="white")
    d.polygon(PLAY, fill="white")
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":   # Koordinaten fürs SVG ausgeben
    a1, a2 = math.radians(HEAD), math.radians(TAIL)
    print("arc", CX + R * math.cos(a1), CY + R * math.sin(a1), "->", CX + R * math.cos(a2), CY + R * math.sin(a2))
    print("head", arrow_head())
    make_logo(512).save("logo_preview.png")
