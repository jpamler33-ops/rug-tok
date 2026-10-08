"""Drawing primitives: easing, cached text sprites, panels, compositing, background."""
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import COL, H, W, font

# ------------------------------------------------------------------ easing --


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def prog(t, a, b):
    if b <= a:
        return 1.0 if t >= a else 0.0
    return clamp((t - a) / (b - a))


def e_out(x):
    return 1 - (1 - x) ** 3


def e_in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def e_back(x, s=1.9):
    c3 = s + 1
    return 1 + c3 * (x - 1) ** 3 + s * (x - 1) ** 2


def e_expo(x):
    return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def mix(a, b, x):
    return a + (b - a) * x


def mix_col(c1, c2, x):
    return tuple(int(round(mix(a, b, x))) for a, b in zip(c1, c2))

# ------------------------------------------------------------- compositing --


def comp(canvas: Image.Image, img: Image.Image, x0, y0):
    """alpha_composite with clipping (PIL refuses negative / out-of-bounds offsets)."""
    x0, y0 = int(round(x0)), int(round(y0))
    cw, ch = canvas.size
    w, h = img.size
    sx, sy = max(0, -x0), max(0, -y0)
    ex, ey = min(w, cw - x0), min(h, ch - y0)
    if ex <= sx or ey <= sy:
        return
    if (sx, sy, ex, ey) != (0, 0, w, h):
        img = img.crop((sx, sy, ex, ey))
    canvas.alpha_composite(img, (x0 + sx, y0 + sy))


def with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return img
    img = img.copy()
    a = img.getchannel("A").point(lambda v: int(v * alpha))
    img.putalpha(a)
    return img


def place(canvas, img, x, y, anchor="mm", scale=1.0, alpha=1.0, rot=0.0):
    if alpha <= 0.003 or scale <= 0.01:
        return
    if rot:
        img = img.rotate(rot, resample=Image.BICUBIC, expand=True)
    if abs(scale - 1) > 0.002:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.BICUBIC)
    img = with_alpha(img, alpha)
    w, h = img.size
    ax = {"l": 0, "m": w / 2, "r": w}[anchor[0]]
    ay = {"t": 0, "m": h / 2, "b": h}[anchor[1]]
    comp(canvas, img, x - ax, y - ay)

# ------------------------------------------------------------------- text --


def _advances(text, f, fixed_digits):
    if not fixed_digits:
        return None
    dw = max(f.getlength(c) for c in "0123456789")
    return [dw if c.isdigit() else f.getlength(c) for c in text]


@lru_cache(maxsize=4096)
def text_sprite(text, weight, size, color, glow=0, glow_color=None, glow_strength=1.0,
                stroke=0, stroke_color=(0, 0, 0), fixed_digits=False, shadow=0):
    """Tight RGBA sprite of one line of text. Sprite is padded; the text box is centered."""
    f = font(weight, size)
    asc, desc = f.getmetrics()
    adv = _advances(text, f, fixed_digits)
    tw = sum(adv) if adv else f.getlength(text)
    pad = int(glow * 2.5 + stroke + shadow * 2 + 6)
    w, h = int(tw + 2 * pad), int(asc + desc * 0.55 + 2 * pad)
    color = tuple(color) + ((255,) if len(color) == 3 else ())

    def draw_text(img, fill, sw=0, sf=None):
        d = ImageDraw.Draw(img)
        if adv:
            x = pad
            for c, a in zip(text, adv):
                cx = x + (a - f.getlength(c)) / 2
                d.text((cx, pad + asc), c, font=f, fill=fill, anchor="ls",
                       stroke_width=sw, stroke_fill=sf)
                x += a
        else:
            d.text((pad, pad + asc), text, font=f, fill=fill, anchor="ls",
                   stroke_width=sw, stroke_fill=sf)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw_text(sh, (0, 0, 0, 200), stroke, (0, 0, 0, 200))
        sh = sh.filter(ImageFilter.GaussianBlur(shadow))
        out.alpha_composite(sh, (0, int(shadow * 0.6)))
    if glow:
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gc = tuple(glow_color or color[:3]) + (255,)
        draw_text(g, gc)
        g = g.filter(ImageFilter.GaussianBlur(glow))
        if glow_strength != 1.0:
            g = with_alpha(g, min(1.0, glow_strength))
        out.alpha_composite(g)
        if glow_strength > 1.0:
            out.alpha_composite(with_alpha(g, glow_strength - 1.0))
    t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sc = tuple(stroke_color) + (255,) if stroke else None
    draw_text(t, color, stroke, sc)
    out.alpha_composite(t)
    return out


def text_width(text, weight, size, fixed_digits=False):
    f = font(weight, size)
    adv = _advances(text, f, fixed_digits)
    return sum(adv) if adv else f.getlength(text)


def fit_size(text, weight, size, max_w, fixed_digits=False):
    while size > 12 and text_width(text, weight, size, fixed_digits) > max_w:
        size -= 2
    return size

# ----------------------------------------------------------------- shapes --


@lru_cache(maxsize=256)
def panel(w, h, r, fill=COL["card"], outline=COL["stroke"], width=2, shadow=28,
          fill_alpha=235, top_fill=None):
    """Anti-aliased rounded panel with soft drop shadow (drawn 2x, downsampled)."""
    pad = shadow * 2
    big = Image.new("RGBA", ((w + 2 * pad) * 2, (h + 2 * pad) * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    box = [pad * 2, pad * 2, (pad + w) * 2, (pad + h) * 2]
    d.rounded_rectangle(box, r * 2, fill=tuple(fill) + (fill_alpha,),
                        outline=tuple(outline) + (255,) if width else None, width=width * 2)
    img = big.resize((w + 2 * pad, h + 2 * pad), Image.LANCZOS)
    if top_fill:  # subtle top highlight gradient
        grad = np.linspace(1, 0, h).astype(np.float32)[:, None] * top_fill
        hl = np.zeros((h + 2 * pad, w + 2 * pad, 4), np.uint8)
        hl[pad:pad + h, pad:pad + w, :3] = 255
        hl[pad:pad + h, pad:pad + w, 3] = (grad * 255).astype(np.uint8)
        hl_img = Image.fromarray(hl, "RGBA")
        mask = img.getchannel("A")
        hl_img.putalpha(Image.fromarray(np.minimum(np.array(hl_img.getchannel("A")),
                                                    np.array(mask))))
        img.alpha_composite(hl_img)
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + shadow // 3, pad + w, pad + h + shadow // 3],
                                             r, fill=(0, 0, 0, 170))
        sh = sh.filter(ImageFilter.GaussianBlur(shadow / 2))
        sh.alpha_composite(img)
        img = sh
    return img


@lru_cache(maxsize=64)
def pill(text, weight, size, fg, bg, pad_x=26, pad_y=14, outline=None, bg_alpha=255, dot=None):
    f = font(weight, size)
    asc, desc = f.getmetrics()
    tw = f.getlength(text)
    dot_w = int(size * 0.55) + 14 if dot else 0
    w, h = int(tw + 2 * pad_x + dot_w), int(size + 2 * pad_y)
    big = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.rounded_rectangle([0, 0, w * 2 - 1, h * 2 - 1], h, fill=tuple(bg) + (bg_alpha,),
                        outline=tuple(outline) + (255,) if outline else None,
                        width=4 if outline else 0)
    if dot:
        r = size * 0.55
        cx, cy = pad_x * 2 + r, h
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(dot) + (255,))
    img = big.resize((w, h), Image.LANCZOS)
    ImageDraw.Draw(img).text((pad_x + dot_w, h / 2), text, font=f, fill=tuple(fg) + (255,),
                             anchor="lm")
    return img


@lru_cache(maxsize=32)
def circle_icon(d, kind, color):
    """Anti-aliased icon in a circle. kind: 'x' | 'warn' | 'check'."""
    s = d * 3
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    c = tuple(color) + (255,)
    if kind == "warn":
        m = s * 0.08
        dr.polygon([(s / 2, m), (s - m, s - m * 1.6), (m, s - m * 1.6)], fill=c)
        lw = int(s * 0.09)
        dr.line([(s / 2, s * 0.36), (s / 2, s * 0.64)], fill=(10, 10, 14, 255), width=lw)
        dr.ellipse([s / 2 - lw * 0.6, s * 0.72, s / 2 + lw * 0.6, s * 0.72 + lw * 1.2],
                   fill=(10, 10, 14, 255))
    else:
        dr.ellipse([2, 2, s - 2, s - 2], fill=tuple(int(v * 0.22) for v in color) + (255,),
                   outline=c, width=int(s * 0.05))
        lw = int(s * 0.1)
        k = s * 0.32
        dr.line([(k, k), (s - k, s - k)], fill=c, width=lw)
        dr.line([(s - k, k), (k, s - k)], fill=c, width=lw)
    return img.resize((d, d), Image.LANCZOS)

# ------------------------------------------------------------- background --


def make_background(seed=1) -> Image.Image:
    """Dark gradient + radial glow + faint trading-terminal grid + vignette."""
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    c0, c1 = np.array(COL["bg0"], np.float32), np.array(COL["bg1"], np.float32)
    t = np.clip(y * 1.1, 0, 1)
    img = c0 + (c1 - c0) * t[..., None] * np.ones_like(x)[..., None]
    # soft colored glow behind the main stage
    d = np.sqrt(((x - 0.5) * 1.0) ** 2 + ((y - 0.38) * 0.62) ** 2)
    img += np.array([40, 18, 60], np.float32) * np.clip(1 - d * 2.2, 0, 1)[..., None] ** 2
    # grid
    grid = np.zeros((H, W), np.float32)
    grid[::90, :] = 1
    grid[:, ::90] = 1
    img += grid[..., None] * 7
    # vignette
    v = np.sqrt((x - 0.5) ** 2 * 1.6 + (y - 0.5) ** 2 * 0.9)
    img *= np.clip(1.15 - v * 1.25, 0.25, 1)[..., None]
    img = np.clip(img, 0, 255).astype(np.uint8)
    return Image.fromarray(img, "RGB").convert("RGBA")


def make_grain(n=6, strength=7, seed=3):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        a = rng.integers(0, strength, (H // 2, W // 2), dtype=np.uint8)
        g = np.zeros((H // 2, W // 2, 4), np.uint8)
        g[..., :3] = 255
        g[..., 3] = a
        out.append(Image.fromarray(g, "RGBA").resize((W, H), Image.NEAREST))
    return out
