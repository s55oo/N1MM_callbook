import sys
from PIL import Image, ImageDraw, ImageFilter
out = sys.argv[1]
N = 1024
def lerp(a, b, t): return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))
# background: rounded square, vertical navy -> blue gradient
grad = Image.new("RGB", (N, N))
gd = ImageDraw.Draw(grad)
top, bot = (30, 86, 196), (12, 28, 66)
for y in range(N):
    gd.line([(0, y), (N, y)], fill=lerp(top, bot, y / (N-1)))
mask = Image.new("L", (N, N), 0)
ImageDraw.Draw(mask).rounded_rectangle((24, 24, N-24, N-24), radius=200, fill=255)
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
img.paste(grad, (0, 0), mask)
# soft top highlight
hl = Image.new("L", (N, N), 0)
ImageDraw.Draw(hl).ellipse((-200, -620, N+200, 420), fill=46)
hl = hl.filter(ImageFilter.GaussianBlur(60)); hl = Image.composite(hl, Image.new("L", (N, N), 0), mask)
img = Image.alpha_composite(img, Image.merge("RGBA", (Image.new("L",(N,N),255),)*3 + (hl,)))
# the Q: thick ring + diagonal tail
cx, cy, R, w = 500, 486, 300, 112
shadow = Image.new("L", (N, N), 0)
sd = ImageDraw.Draw(shadow)
def q(d, fill_ring, fill_tail, dx=0, dy=0):
    d.ellipse((cx-R+dx, cy-R+dy, cx+R+dx, cy+R+dy), outline=fill_ring, width=w)
    # tail: thick rounded line from inside the ring out to bottom-right
    x0, y0, x1, y1 = cx+70+dx, cy+90+dy, cx+300+dx, cy+320+dy
    d.line([(x0, y0), (x1, y1)], fill=fill_tail, width=118)
    r = 59
    d.ellipse((x1-r, y1-r, x1+r, y1+r), fill=fill_tail)
    d.ellipse((x0-r, y0-r, x0+r, y0+r), fill=fill_tail)
q(sd, 120, 120, 10, 16)
shadow = shadow.filter(ImageFilter.GaussianBlur(18))
img = Image.alpha_composite(img, Image.merge("RGBA", (Image.new("L",(N,N),0),)*3 + (shadow,)))
layer = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ld = ImageDraw.Draw(layer)
q(ld, (255, 255, 255, 255), (124, 252, 0, 255))
# keep the ring white where the tail crosses it: redraw ring segment over tail start? no - tail on top reads as Q
img = Image.alpha_composite(img, layer)
sizes = [256, 128, 64, 48, 32, 24, 16]
frames = [img.resize((s, s), Image.LANCZOS) for s in sizes]
frames[0].save(out, sizes=[(s, s) for s in sizes], append_images=frames[1:])
img.resize((512, 512), Image.LANCZOS).save(out.replace(".ico", "_preview.png"))
# small-size strip for checking legibility
strip = Image.new("RGBA", (16+24+32+48+64+5*12+12, 76), (240, 240, 240, 255))
x = 12
for s in (16, 24, 32, 48, 64):
    strip.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 76 - s - 6)); x += s + 12
strip.resize((strip.width*3, strip.height*3), Image.NEAREST).save(out.replace(".ico", "_small.png"))
