"""Builds every logo file of AIS AssetTrack from the official AIS logo (brand/ais_logo_source.png).
Run from the project folder:  python brand/build_logos.py
To use a better / higher-resolution logo later: replace brand/ais_logo_source.png and run this again.
Outputs: web icons, favicon, dark-header logo, AIS + AssetTrack logo, A4 print logo, HHT app icon / adaptive icon /
splash, thermal-printer logo (PNG + 1-bit raster for ESC/POS). Developed by DT
"""
import base64, io, os
import numpy as np
from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "brand", "ais_logo_source.png")
STATIC = os.path.join(ROOT, "server", "app", "static")
HHT = os.path.join(ROOT, "hht", "assets")
LIB = os.path.join(ROOT, "hht", "src", "lib")


def clean_source() -> Image.Image:
    """White background (removes a 'transparent' checkerboard), trimmed to the artwork."""
    im = Image.open(SRC).convert("RGB")
    a = np.asarray(im).astype(int)
    mx, mn = a.max(2), a.min(2)
    grey = (mx - mn < 40) & (mn > 150)
    a[grey] = 255
    im = Image.fromarray(a.astype("uint8"))
    bb = ImageOps.invert(im.convert("L")).point(lambda v: 255 if v > 60 else 0).getbbox()
    return im.crop(bb)


def to_alpha(im: Image.Image) -> Image.Image:
    """White -> transparent, keeping anti-aliased edges (colour-to-alpha)."""
    a = np.asarray(im.convert("RGB")).astype(float)
    alpha = ((255 - a) / 255).max(2)
    alpha = np.clip(alpha * 1.15, 0, 1)                    # slightly firmer edges
    safe = np.where(alpha > 0, alpha, 1)[..., None]
    rgb = np.clip((a - 255 * (1 - alpha[..., None])) / safe, 0, 255)
    out = np.dstack([rgb, alpha * 255]).astype("uint8")
    return Image.fromarray(out, "RGBA")


def on_dark(im: Image.Image) -> Image.Image:
    """Version for dark backgrounds: red diamond stays red, blue 'AIS' and black text turn white."""
    a = np.asarray(im).copy()
    r, g, b = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    red = (r > g + 60) & (r > b + 60)
    a[~red, 0:3] = 255
    a[red, 0:3] = [230, 40, 50]
    return Image.fromarray(a, "RGBA")


def fit(im, w, h, bg=(0, 0, 0, 0), scale=1.0):
    """Logo centred on a w x h canvas, using `scale` of the canvas."""
    c = Image.new("RGBA", (w, h), bg)
    t = im.copy()
    f = min(w * scale / t.width, h * scale / t.height)
    t = t.resize((max(1, round(t.width * f)), max(1, round(t.height * f))), Image.LANCZOS)
    c.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    return c


def text_split(im: Image.Image) -> int:
    """Row where the 'Asahi India Glass Ltd.' line starts (largest blank band in the lower half)."""
    g = np.asarray(im.convert("L")) < 200
    rows = g.any(1)
    best, start = (0, im.height), None
    for y in range(im.height // 2, im.height):
        if not rows[y] and start is None:
            start = y
        if rows[y] and start is not None:
            if y - start > best[0]:
                best = (y - start, y)
            start = None
    return best[1]


def main():
    src = clean_source()
    logo = to_alpha(src)                                     # transparent official logo
    dark = on_dark(logo)
    mark = logo.crop((0, 0, logo.width, text_split(src) - 2))  # diamond + AIS only (for tiny icons)
    mark = mark.crop(mark.getbbox())
    wm = Image.open(os.path.join(STATIC, "wordmark.png")).convert("RGBA")
    wm_dark = Image.open(os.path.join(STATIC, "wordmark-on-dark.png")).convert("RGBA")

    # ---- web
    fit(logo, 192, 192, scale=0.94).save(os.path.join(STATIC, "icon-192.png"))
    fit(dark, 192, 192, scale=0.94).save(os.path.join(STATIC, "icon-on-dark.png"))
    fit(mark, 64, 64, scale=0.98).save(os.path.join(STATIC, "favicon.png"))
    # A4 prints: white background, high resolution
    up = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
    pad = Image.new("RGB", (up.width + 28, up.height + 28), "white"); pad.paste(up, (14, 14))
    pad.save(os.path.join(STATIC, "print-logo.png"))

    # ---- AIS logo above the AssetTrack wordmark (web login / HHT / thermal print)
    def combo(lg, w_mark, W=396, H=244):
        c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        top = lg.copy(); f = 112 / top.height; top = top.resize((round(top.width * f), 112), Image.LANCZOS)
        c.alpha_composite(top, ((W - top.width) // 2, 0))
        wmk = w_mark.copy(); f = W / wmk.width; wmk = wmk.resize((W, round(wmk.height * f)), Image.LANCZOS)
        c.alpha_composite(wmk, (0, H - wmk.height))
        return c
    both = combo(logo, wm)
    both.save(os.path.join(STATIC, "logo.png"))
    both.save(os.path.join(HHT, "logo.png"))

    # ---- HHT app
    fit(logo, 1024, 1024, scale=0.9).save(os.path.join(HHT, "icon.png"))
    fit(dark, 1024, 1024, scale=0.9).save(os.path.join(HHT, "icon_on_dark.png"))
    ad = fit(logo, 1024, 1024, bg=(255, 255, 255, 255), scale=0.62)      # Android adaptive icon: keep inside the safe zone
    ad.convert("RGB").save(os.path.join(HHT, "adaptive-icon.png"))
    sp = Image.new("RGBA", (1284, 2778), (255, 255, 255, 255))
    big = combo(logo, wm, 792, 488)
    sp.alpha_composite(big, ((1284 - big.width) // 2, (2778 - big.height) // 2))
    sp.convert("RGB").save(os.path.join(HHT, "splash.png"))

    # ---- thermal printer (ESC/POS): 384 x 236, 1-bit
    th = Image.new("RGBA", (384, 236), (255, 255, 255, 255))
    th.alpha_composite(combo(logo, wm, 384, 236))
    g = th.convert("L")
    bw = g.point(lambda v: 0 if v < 170 else 255, "1")
    bw.convert("L").save(os.path.join(HHT, "print_logo.png"))
    bits = np.asarray(bw.convert("L")) < 128                          # True = black dot
    packed = np.packbits(bits, axis=1)                                  # MSB first, 48 bytes per row
    b64 = base64.b64encode(packed.tobytes()).decode()
    with open(os.path.join(LIB, "printLogoRaster.js"), "w") as f:
        f.write("// AIS logo as 1-bit raster for ESC/POS (GS v 0): 384x236 px, 48 bytes per row. "
                "Generated by brand/build_logos.py from the official AIS logo. Developed by DT\n")
        f.write(f"export const LOGO_RASTER = {{ width: 384, height: 236, widthBytes: 48, data: '{b64}' }};\n")
    buf = io.BytesIO(); bw.convert("L").save(buf, "PNG")
    with open(os.path.join(LIB, "printLogo.js"), "w") as f:
        f.write("// AIS logo for ESC/POS printers (384px wide, 1-bit). Generated by brand/build_logos.py. Developed by DT\n")
        f.write(f"export const PRINT_LOGO_B64 = '{base64.b64encode(buf.getvalue()).decode()}';\n")
    print("logos built from", SRC)


if __name__ == "__main__":
    main()
