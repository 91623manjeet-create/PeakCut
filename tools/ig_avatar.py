"""Draws the Instagram profile picture (dp) for vicecity_bloopers.

A synthwave sunset: purple-to-pink sky, striped sun, palm silhouettes.
Only Pillow, no downloads. Run: .venv\\Scripts\\python.exe tools\\ig_avatar.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 1080  # square, Instagram then crops it to a circle
img = Image.new("RGB", (S, S))
px = img.load()

# --- sky: dark purple at the top fading to hot pink at the horizon
top, mid, low = (24, 10, 46), (94, 20, 94), (255, 62, 165)
for y in range(S):
    t = y / S
    if t < 0.55:
        f = t / 0.55
        c = tuple(round(top[i] + (mid[i] - top[i]) * f) for i in range(3))
    else:
        f = (t - 0.55) / 0.45
        f = f * f
        c = tuple(round(mid[i] + (low[i] - mid[i]) * f) for i in range(3))
    for x in range(S):
        px[x, y] = c

d = ImageDraw.Draw(img)

# --- the sun: a big circle whose bottom is eaten by stripes
cx, cy, r = S // 2, 430, 300
sun = Image.new("RGB", (2 * r, 2 * r), (0, 0, 0))
sp = sun.load()
for y in range(2 * r):
    f = y / (2 * r)
    c = tuple(round(a + (b - a) * f) for a, b in zip((255, 214, 120), (255, 62, 165)))
    for x in range(2 * r):
        sp[x, y] = c
# cut the classic horizontal gaps, wider apart towards the bottom
for y in range(r, 2 * r):
    band = (y - r) / r
    if int(band * 9) % 2 == 1 and band > 0.28:
        h = round(6 + 26 * band)
        ImageDraw.Draw(sun).rectangle([0, y, 2 * r, y + h], fill=(0, 0, 0))
mask = Image.new("L", (2 * r, 2 * r), 0)
ImageDraw.Draw(mask).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
img.paste(sun, (cx - r, cy - r), mask)

# --- neon ring just outside the sun
ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
rd = ImageDraw.Draw(ring)
rd.ellipse([cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26], outline=(60, 230, 255, 255), width=8)
ring = ring.filter(ImageFilter.GaussianBlur(10))
img.paste(ring, (0, 0), ring)

# --- ground: a darker strip the palms stand on
d.rectangle([0, 880, S, S], fill=(26, 8, 40))
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.rectangle([0, 880, S, 940], fill=(255, 62, 165, 120))
glow = glow.filter(ImageFilter.GaussianBlur(18))
img.paste(glow, (0, 0), glow)
d = ImageDraw.Draw(img)


def palm(x, y, k, flip=False):
    """A palm silhouette: leaning trunk and drooping fronds, drawn as filled shapes."""
    import math
    col = (16, 5, 28)
    lean = -1 if flip else 1

    def curve(p0, p1, p2, n=24):
        return [((1 - f) ** 2 * p0[0] + 2 * (1 - f) * f * p1[0] + f * f * p2[0],
                 (1 - f) ** 2 * p0[1] + 2 * (1 - f) * f * p1[1] + f * f * p2[1])
                for f in (i / n for i in range(n + 1))]

    def tapered(pts, w0, w1):
        """A closed shape along pts, thick at the start and thin at the end."""
        up, down = [], []
        for i, (qx, qy) in enumerate(pts):
            p, n = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
            dx, dy = n[0] - p[0], n[1] - p[1]
            L = math.hypot(dx, dy) or 1
            w = (w0 + (w1 - w0) * i / len(pts))
            up.append((qx - dy / L * w, qy + dx / L * w))
            down.append((qx + dy / L * w, qy - dx / L * w))
        d.polygon(up + down[::-1], fill=col)

    # trunk: one gentle lean with a slight bend
    top = (x + lean * 120, y - round(370 * k))
    mid = (x + lean * 30, y - round(210 * k))
    trunk = curve((x, y), mid, top)
    tapered(trunk, 15, 7)

    # fronds: six arcs falling away from the crown
    for a in (-155, -115, -70, -25, 20, 55):
        rad = math.radians(a + (180 if flip else 0))
        L = 265 + (a % 3) * 18
        ex = top[0] + round(math.cos(rad) * L)
        ey = top[1] + round(abs(math.sin(rad)) * L * 0.35) + 95   # every frond ends drooping
        mx = top[0] + round(math.cos(rad) * L * 0.55)
        my = top[1] - 70                                          # it first rises, then falls
        tapered(curve(top, (mx, my), (ex, ey)), 10, 1)


palm(210, 905, 1.0)
palm(870, 905, 0.9, flip=True)

# --- a few stars up top
import random
random.seed(7)
for _ in range(70):
    x, y = random.randrange(S), random.randrange(360)
    s = random.choice((1, 1, 2))
    d.ellipse([x, y, x + s, y + s], fill=(230, 220, 255))

out = Path("data/brand/ig-avatar.png")
out.parent.mkdir(parents=True, exist_ok=True)
img.save(out)
img.resize((320, 320), Image.LANCZOS).save(out.with_name("ig-avatar-320.png"))
print("wrote", out)
