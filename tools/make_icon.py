"""Draw the app icon: the in-app logo, an amber rounded square with a dark diamond.

Rendered at 1024px and downsampled per size, rather than drawn small, so the
edges stay clean at 16px in the tray as well as at 256px in Explorer.
Run once; the outputs are committed under assets/.
"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "assets")

AMBER = (233, 162, 60)
AMBER_DEEP = (193, 125, 34)
INK = (42, 27, 6)


def draw(size=1024):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Diagonal amber gradient, matching .logo's linear-gradient(135deg, ...).
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(AMBER, AMBER_DEEP)) + (255,)

    mask = Image.new("L", (size, size), 0)
    pad = round(size * 0.04)
    ImageDraw.Draw(mask).rounded_rectangle(
        (pad, pad, size - pad, size - pad), radius=round(size * 0.23), fill=255)
    img.paste(grad, (0, 0), mask)

    c, r = size / 2, size * 0.25
    ImageDraw.Draw(img).polygon(
        [(c, c - r), (c + r, c), (c, c + r), (c - r, c)], fill=INK + (255,))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    big = draw()
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "glitchguard.png"))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(
        os.path.join(OUT, "glitchguard.ico"), sizes=[(s, s) for s in sizes])
    print("wrote", os.path.join(OUT, "glitchguard.ico"), "and glitchguard.png")


if __name__ == "__main__":
    main()
