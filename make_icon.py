"""Generate ReelFrame brand icon (.ico) — film frame + purple gradient."""
from PIL import Image, ImageDraw

def make(size):
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)

    # Rounded square with vertical indigo -> violet gradient
    grad = Image.new("RGB", (1, s))
    for y in range(s):
        t = y / max(1, s - 1)
        grad.putpixel((0, y), (
            int(99 + (124 - 99) * t),    # R
            int(102 + (58 - 102) * t),   # G
            int(241 + (237 - 241) * t),  # B
        ))
    grad = grad.resize((s, s))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=255)
    img.paste(grad, (0, 0), mask)

    # Film "frames": three white bars, decreasing width (reel/frames motif)
    pad = int(s * 0.20)
    bar_h = int(s * 0.115)
    gap = int(s * 0.075)
    y = int(s * 0.28)
    widths = [1.00, 0.72, 0.48]
    for wf in widths:
        w = int((s - 2 * pad) * wf)
        d.rounded_rectangle([pad, y, pad + w, y + bar_h], radius=int(bar_h * 0.30), fill=(255, 255, 255, 245))
        y += bar_h + gap
    return img

imgs = [make(n) for n in (16, 24, 32, 48, 64, 128, 256)]
imgs[0].save("web/icon.ico", format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
imgs[-1].save("web/icon.png")
print("wrote web/icon.ico and web/icon.png")
