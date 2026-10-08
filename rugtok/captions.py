"""TikTok-style word-by-word captions: 1-3 words per chunk, active word highlighted."""
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from .config import COL, font
from .gfx import e_back, place, prog

SIZE = 84
MAX_W = 860
WEIGHT = "Black"


def make_chunks(scenes, max_words=3, max_chars=16):
    words = [w for sc in scenes for sen in sc.sentences for w in sen.words]
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x.show for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sentence = w.show[-1:] in ".!?:,"
        too_long = nxt is not None and len(text) + 1 + len(nxt.show) > max_chars
        gap = nxt is not None and nxt.start - w.end > 0.35
        if len(cur) >= max_words or end_sentence or too_long or gap or nxt is None:
            chunks.append(cur)
            cur = []
    out = []
    for i, ch in enumerate(chunks):
        start = ch[0].start
        nxt_start = chunks[i + 1][0].start if i + 1 < len(chunks) else ch[-1].end + 0.6
        end = min(nxt_start, ch[-1].end + 0.45)
        out.append({"words": ch, "start": start, "end": end})
    return out


@lru_cache(maxsize=512)
def _render(texts: tuple, active: int):
    size = SIZE
    f = font(WEIGHT, size)
    space = f.getlength(" ")
    while size > 40 and sum(f.getlength(t) for t in texts) + space * (len(texts) - 1) > MAX_W:
        size -= 4
        f = font(WEIGHT, size)
        space = f.getlength(" ")
    tw = sum(f.getlength(t) for t in texts) + space * (len(texts) - 1)
    asc, desc = f.getmetrics()
    pad, stroke = 30, 9
    w, h = int(tw + 2 * pad), int(asc + desc + 2 * pad)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ds, d = ImageDraw.Draw(sh), ImageDraw.Draw(img)
    x = pad
    for i, t in enumerate(texts):
        col = COL["yellow"] if i == active else COL["white"]
        ds.text((x, pad + asc + 6), t, font=f, fill=(0, 0, 0, 190), anchor="ls",
                stroke_width=stroke, stroke_fill=(0, 0, 0, 190))
        d.text((x, pad + asc), t, font=f, fill=tuple(col) + (255,), anchor="ls",
               stroke_width=stroke, stroke_fill=(8, 8, 12, 255))
        x += f.getlength(t) + space
    sh = sh.filter(ImageFilter.GaussianBlur(9))
    sh.alpha_composite(img)
    return sh


def draw_captions(cv, chunks, t, y):
    for ch in chunks:
        if ch["start"] <= t < ch["end"]:
            ws = ch["words"]
            active = max([i for i, w in enumerate(ws) if w.start <= t] or [0])
            img = _render(tuple(w.show for w in ws), active)
            k = prog(t, ch["start"], ch["start"] + 0.16)
            scale = 0.82 + 0.18 * e_back(k) if k < 1 else 1.0
            place(cv, img, 540, y, scale=scale)
            return
