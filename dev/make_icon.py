"""Callbooker icon - Q in the same style as the family's C icon:
blue gradient rounded square, thick white letter, orange dot, tan radio arcs.
Usage: python make_icon.py out.ico"""
import math, sys
from PIL import Image, ImageDraw

out = sys.argv[1]
N = 1024
TOP, BOT = (17, 45, 88), (22, 98, 182)        # navy -> blue, darker at the top
ORANGE, TAN, WHITE = (255, 152, 0), (201, 160, 98), (255, 255, 255)

def lerp(a, b, t): return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
grad = Image.new("RGB", (N, N)); gd = ImageDraw.Draw(grad)
for y in range(N):
    gd.line([(0, y), (N, y)], fill=lerp(TOP, BOT, y / (N - 1)))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, N - 1, N - 1), radius=180, fill=255)
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)

# the Q: full white ring (left of centre, like the C) ...
cx, cy, R, w = 395, 495, 255, 124
d.ellipse((cx - R, cy - R, cx + R, cy + R), outline=WHITE, width=w)
# ... with a white tail out to the bottom-right
a = math.radians(45)
x0, y0 = cx + (R - w / 2) * math.cos(a), cy + (R - w / 2) * math.sin(a)
x1, y1 = cx + (R + 95) * math.cos(a), cy + (R + 95) * math.sin(a)
tw = 120
d.line([(x0, y0), (x1, y1)], fill=WHITE, width=tw)
for x, y in ((x0, y0), (x1, y1)):
    d.ellipse((x - tw / 2, y - tw / 2, x + tw / 2, y + tw / 2), fill=WHITE)

# orange dot + two tan radio arcs, upper right (same as the C icon)
dx, dy, dr = 745, 455, 84
d.ellipse((dx - dr, dy - dr, dx + dr, dy + dr), fill=ORANGE)
for r, aw in ((150, 30), (215, 30)):
    d.arc((dx - r, dy - r, dx + r, dy + r), start=-38, end=38, fill=TAN, width=aw)

sizes = [256, 128, 64, 48, 32, 24, 16]
frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]
frames[0].save(out, sizes=[(s, s) for s in sizes], append_images=frames[1:])

# preview sheet like the C icon's: dark row of all sizes + light row of small ones
sheet = Image.new("RGBA", (900, 330), (32, 32, 32, 255))
x = 10
for s in (16, 20, 24, 32, 48, 64, 96, 128, 256):
    if s == 256:
        sheet.alpha_composite(img.resize((240, 240), Image.LANCZOS), (x, 18))
    else:
        sheet.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 10)); x += s + 12
ImageDraw.Draw(sheet).rectangle((0, 270, 900, 330), fill=(242, 242, 242, 255))
x = 10
for s in (16, 24, 32, 48):
    sheet.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 284)); x += s + 18
sheet.save(out.replace(".ico", "_sheet.png"))
