"""The five scenes of 'Rug des Tages'. Each scene draws itself for a local time `lt`
and declares its sound/visual events (pinned to narration markers)."""
import hashlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import COL, W
from .gfx import (circle_icon, clamp, e_back, e_in_out, e_out, fit_size, mix, mix_col, panel,
                  pill, place, prog, text_sprite)
from .data import short_ca
from .text_de import fmt_dec, fmt_int, fmt_usd

CX = W // 2

# ---------------------------------------------------------------- helpers --


def enter(lt, t0, dur=0.42):
    """-> (motion 0..~1.1 with overshoot, alpha 0..1)"""
    x = prog(lt, t0, t0 + dur)
    return (e_back(x) if x < 1 else 1.0), clamp(x * 2.5)


def price_series(d):
    """Real price_series if given (required for non-demo videos); otherwise a synthetic
    path consistent with the key numbers (demo only)."""
    if d.get("price_series"):
        a = np.asarray(d["price_series"], dtype=float)
        ms, ps = a[:, 0] - a[0, 0], a[:, 1] / a[0, 1]
        return ms, ps, int(np.argmax(ps))
    rng = np.random.default_rng(d.get("seed", 1))
    peak_m = float(d["minutes_to_peak"])
    G = 1 + d["peak_gain_pct"] / 100
    dead_m = peak_m + d["minutes_peak_to_dead"]
    final = G * (1 - d["drawdown_pct"] / 100)
    n = 170
    m1 = np.linspace(0, peak_m, n)
    u = m1 / peak_m
    base = np.exp(np.log(G) * u ** 1.75)
    walk = np.cumsum(rng.normal(0, 0.05, n))
    walk -= np.linspace(0, walk[-1], n)
    walk = np.convolve(walk, np.ones(4) / 4, mode="same")
    p1 = base * np.exp(walk * (0.35 + 0.65 * u))
    p1 = np.minimum(p1, G * 0.97)
    p1[0], p1[-1] = 1.0, G
    m2 = np.array([peak_m + 0.05, peak_m + 0.11])
    p2 = np.array([G * 0.32, G * 0.055])
    m3 = np.linspace(peak_m + 0.11, dead_m, 34)[1:]
    v = np.linspace(0, 1, len(m3))
    p3 = G * 0.055 * (final / (G * 0.055)) ** (v ** 0.7)
    p3 *= 1 + rng.normal(0, 0.12, len(m3)) * (1 - v)
    p3[-1] = final
    m4 = np.linspace(dead_m, dead_m + 0.7, 6)[1:]
    p4 = np.full(len(m4), final)
    ms = np.concatenate([m1, m2, m3, m4])
    ps = np.concatenate([p1, p2, p3, p4])
    return ms, ps, n - 1


_GRAD = {}


def _grad(w, h, top_alpha):
    k = (w, h, top_alpha)
    if k not in _GRAD:
        a = (np.linspace(1, 0, h, dtype=np.float32) ** 1.4 * top_alpha).astype(np.uint8)
        _GRAD[k] = Image.fromarray(np.repeat(a[:, None], w, axis=1), "L")
    return _GRAD[k]


def draw_series(bw, bh, ms, ps, reveal_m, peak_idx, lw=7, glow=12, ss=2, pmax=None,
                fill_alpha=95, pad=10):
    """Render the revealed part of a price line into a (bw, bh) RGBA image.
    Returns (image, head_xy or None, head_after_peak)."""
    mmax = ms[-1]
    pmax = pmax or ps.max() * 1.1
    k = int(np.searchsorted(ms, reveal_m, side="right"))
    mm, pp = list(ms[:k]), list(ps[:k])
    if 0 < k < len(ms) and reveal_m > ms[k - 1]:
        f = (reveal_m - ms[k - 1]) / (ms[k] - ms[k - 1])
        mm.append(reveal_m)
        pp.append(ps[k - 1] + (ps[k] - ps[k - 1]) * f)
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    if len(mm) < 2:
        return img, None, False

    def xy(m, p, s=1):
        return (pad + m / mmax * (bw - 2 * pad)) * s, (bh - pad - p / pmax * (bh - 2 * pad)) * s

    n_rise = min(len(mm), peak_idx + 1)
    rise = [xy(m, p, ss) for m, p in zip(mm[:n_rise], pp[:n_rise])]
    fall = [xy(m, p, ss) for m, p in zip(mm[n_rise - 1:], pp[n_rise - 1:])] if len(mm) > n_rise else []

    # gradient fills under the line
    for pts, col in ((rise, COL["green"]), (fall, COL["red"])):
        if len(pts) < 2:
            continue
        mask = Image.new("L", (bw, bh), 0)
        poly = [(x / ss, y / ss) for x, y in pts]
        poly += [(poly[-1][0], bh - pad), (poly[0][0], bh - pad)]
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        alpha = Image.fromarray(np.minimum(np.array(mask), np.array(_grad(bw, bh, fill_alpha))))
        layer = Image.new("RGBA", (bw, bh), tuple(col) + (0,))
        layer.putalpha(alpha)
        img.alpha_composite(layer)

    big = Image.new("RGBA", (bw * ss, bh * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    if len(rise) >= 2:
        d.line(rise, fill=tuple(COL["green"]) + (255,), width=lw * ss, joint="curve")
    if len(fall) >= 2:
        d.line(fall, fill=tuple(COL["red"]) + (255,), width=lw * ss, joint="curve")
    lines = big.resize((bw, bh), Image.LANCZOS)
    if glow:
        img.alpha_composite(lines.filter(ImageFilter.GaussianBlur(glow)))
    img.alpha_composite(lines)
    hx, hy = xy(mm[-1], pp[-1])
    return img, (hx, hy), len(mm) > n_rise


def head_dot(cv, x, y, color, t):
    r = 13
    pulse = 0.5 + 0.5 * np.sin(t * 9)
    halo = int(r * (2.2 + 0.8 * pulse))
    g = Image.new("RGBA", (halo * 4, halo * 4), (0, 0, 0, 0))
    ImageDraw.Draw(g).ellipse([halo, halo, halo * 3, halo * 3], fill=tuple(color) + (110,))
    g = g.filter(ImageFilter.GaussianBlur(halo / 2.5))
    place(cv, g, x, y)
    s = Image.new("RGBA", (r * 6, r * 6), (0, 0, 0, 0))
    ImageDraw.Draw(s).ellipse([r, r, r * 5, r * 5], fill=(255, 255, 255, 255))
    place(cv, s.resize((r * 2, r * 2), Image.LANCZOS), x, y)


def dashed_vline(cv, x, y0, y1, color, alpha=1.0, dash=14, gap=10, w=4):
    d = ImageDraw.Draw(cv)
    y = y0
    c = tuple(color) + (int(255 * alpha),)
    while y < y1:
        d.line([(x, y), (x, min(y + dash, y1))], fill=c, width=w)
        y += dash + gap


def avatar(symbol, d=150):
    h = hashlib.md5(symbol.encode()).digest()
    c1 = (120 + h[0] % 120, 60 + h[1] % 120, 160 + h[2] % 90)
    c2 = (255, 120 + h[3] % 100, 60 + h[4] % 80)
    s = d * 2
    y = np.linspace(0, 1, s, dtype=np.float32)[:, None, None]
    grad = (np.array(c1, np.float32) * (1 - y) + np.array(c2, np.float32) * y) * np.ones((1, s, 1))
    img = Image.fromarray(grad.astype(np.uint8), "RGB").convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, s - 1, s - 1], fill=255)
    img.putalpha(mask)
    img = img.resize((d, d), Image.LANCZOS)
    letter = text_sprite(symbol[0], "Black", int(d * 0.5), (255, 255, 255))
    place(img, letter, d / 2, d / 2 + 2)
    return img

# ------------------------------------------------------------------ scenes --


class Scene:
    def __init__(self, sc, d, series):
        self.sc, self.d, self.series = sc, d, series
        self.start, self.dur = sc.start, sc.end - sc.start

    def m(self, name):
        return self.sc.markers[name] - self.start

    def g(self, local_t):
        return self.start + local_t

    def events(self):
        return [("sfx", self.start + 0.02, {"name": "whoosh", "gain": 0.55})]

    def draw(self, cv, lt):
        raise NotImplementedError


class Hook(Scene):
    """Big green counter -> crash to red. The first frame already shows a big number."""

    def events(self):
        c = self.sc.markers["crash"]
        n_end = self.sc.markers["num"] + 0.9
        return [
            ("sfx", 0.0, {"name": "impact", "gain": 0.6}),
            ("sfx", 0.05, {"name": "riser", "gain": 0.45, "dur": n_end - 0.05}),
            ("sfx", c - 0.02, {"name": "boom", "gain": 1.0}),
            ("sfx", c, {"name": "glitch", "gain": 0.5}),
            ("shake", c, {"amp": 22, "dur": 0.55}),
            ("flash", c, {"color": COL["red"], "alpha": 0.42, "dur": 0.45}),
            ("glitch", c, {"dur": 0.3}),
        ]

    def draw(self, cv, lt):
        d = self.d
        crash = self.m("crash")
        n_end = self.m("num") + 0.9
        crashed = lt >= crash
        ms, ps, pk = self.series

        # ticker pill
        mo, al = enter(lt, -0.4, 0.35)
        tick = pill(f"${d['token']['symbol']}  ·  {d['token']['chain']}", "Bold", 40,
                    COL["white"], COL["card2"], outline=COL["stroke"], bg_alpha=230)
        place(cv, tick, CX, 430 - (1 - mo) * 40, alpha=al)

        # counter
        if not crashed:
            x = e_out(prog(lt, 0.0, n_end))
            val = mix(d["peak_gain_pct"] * 0.55, d["peak_gain_pct"], x)
            txt = f"+{fmt_int(val)} %"
            col = COL["green"]
            # suspense: slow push-in between the number landing and the crash
            scale = 1.0 + 0.07 * e_in_out(prog(lt, n_end, crash))
            if lt < n_end:
                scale *= 1 + 0.03 * np.sin(lt * 30) * (1 - x)
        else:
            txt = f"−{fmt_dec(d['drawdown_pct'])} %"
            col = COL["red"]
            k = prog(lt, crash, crash + 0.35)
            scale = mix(1.35, 1.0, e_out(k))
        size = fit_size(f"+{fmt_int(d['peak_gain_pct'])} %", "Black", 200, 920, True)
        spr = text_sprite(txt, "Black", size, col, glow=26, glow_strength=1.3, fixed_digits=True)
        place(cv, spr, CX, 650, scale=scale)

        # sub line
        if not crashed:
            sub = f"in {d['minutes_to_peak']} Minuten"
            sc = COL["muted"]
        else:
            sub = f"{d['minutes_peak_to_dead']} Minuten später"
            sc = COL["red"]
        mo, al = enter(lt, 0.15 if not crashed else crash, 0.35)
        place(cv, text_sprite(sub, "SemiBold", 56, sc), CX, 805 + (1 - mo) * 30, alpha=al)

        # mini chart
        reveal = (ms[pk] * mix(0.45, 1.0, e_out(prog(lt, 0.0, n_end))) if not crashed
                  else ms[pk] + (ms[-1] - ms[pk]) * e_out(prog(lt, crash, crash + 0.4)))
        img, head, after = draw_series(800, 300, ms, ps, reveal, pk, lw=6, glow=10, fill_alpha=80)
        place(cv, img, CX, 1040)
        if head:
            head_dot(cv, CX - 400 + head[0], 1040 - 150 + head[1],
                     COL["red"] if after else COL["green"], lt)


class Card(Scene):
    """Token profile card; status flips from LIVE to a drawdown stamp."""

    def stamp_t(self):
        return max(self.m("liq") + 0.9, self.dur - 0.85)

    def events(self):
        st = self.g(self.stamp_t())
        return super().events() + [
            ("sfx", self.sc.markers["launch"], {"name": "pop", "gain": 0.4}),
            ("sfx", self.sc.markers["liq"], {"name": "pop", "gain": 0.4}),
            ("sfx", st, {"name": "stamp", "gain": 0.95}),
            ("shake", st, {"amp": 12, "dur": 0.3}),
            ("flash", st, {"color": COL["red"], "alpha": 0.18, "dur": 0.25}),
        ]

    def draw(self, cv, lt):
        d = self.d
        tok = d["token"]
        mo, al = enter(lt, 0.0, 0.5)
        oy = (1 - mo) * 140
        card = panel(900, 640, 44, top_fill=0.05)
        place(cv, card, CX, 735 + oy, alpha=al)
        top = 735 - 320 + oy

        place(cv, avatar(tok["symbol"], 150), 200, top + 130, alpha=al)
        place(cv, text_sprite(f"${tok['symbol']}", "Black", 96, COL["white"]), 305, top + 108,
              anchor="lm", alpha=al)
        sub = f"{tok['chain']} · CA {short_ca(d.get('contract_address', 'DEMO'))}"
        place(cv, text_sprite(sub, "Text-Medium", 40, COL["muted"]), 310,
              top + 182, anchor="lm", alpha=al)
        ImageDraw.Draw(cv).line([(130, top + 262), (950, top + 262)],
                                fill=tuple(COL["stroke"]) + (int(255 * al),), width=2)

        stamp_t = self.stamp_t()
        rows = [
            ("launch", "Gestartet", f"{d.get('launch_day', 'gestern')}, {d['launch_time']}", COL["white"]),
            ("liq", "Liquidität", fmt_usd(d["initial_liquidity_usd"]), COL["white"]),
        ]
        for i, (mk, label, value, vc) in enumerate(rows):
            rm, ra = enter(lt, self.m(mk), 0.4)
            y = top + 345 + i * 105
            place(cv, text_sprite(label, "Text-Medium", 42, COL["muted"]), 130 + (1 - rm) * 60, y,
                  anchor="lm", alpha=ra * al)
            place(cv, text_sprite(value, "Bold", 58, vc), 950 - (1 - rm) * -60, y, anchor="rm",
                  alpha=ra * al)
        # status row
        y = top + 345 + 2 * 105
        place(cv, text_sprite("Status", "Text-Medium", 42, COL["muted"]), 130, y, anchor="lm",
              alpha=al)
        if lt < stamp_t:
            live = pill("LIVE", "Bold", 38, COL["green"], (10, 40, 25), dot=COL["green"],
                        bg_alpha=255)
            blink = 0.65 + 0.35 * np.sin(lt * 7)
            place(cv, live, 950, y, anchor="rm", alpha=al * blink)
        else:
            dead = pill("TOT", "Bold", 38, COL["white"], COL["red"], dot=(255, 255, 255))
            place(cv, dead, 950, y, anchor="rm")
            k = prog(lt, stamp_t, stamp_t + 0.22)
            stamp = text_sprite(f"−{int(d['drawdown_pct'])} %", "Black", 190, COL["red"], stroke=10,
                                stroke_color=(25, 0, 6), glow=20, glow_color=COL["red"])
            place(cv, stamp, CX, 700 + oy, scale=mix(2.2, 1.0, e_out(k)), alpha=clamp(k * 3),
                  rot=12)


class Chart(Scene):
    """Live price chart: rise with buyer counter, then the dev dump."""

    def events(self):
        dump = self.sc.markers["dump"]
        return super().events() + [
            ("sfx", self.sc.markers["rise"], {"name": "riser", "gain": 0.35,
                                               "dur": dump - self.sc.markers["rise"]}),
            ("sfx", dump - 0.02, {"name": "boom", "gain": 0.95}),
            ("sfx", dump + 0.05, {"name": "fall", "gain": 0.7}),
            ("shake", dump, {"amp": 18, "dur": 0.5}),
            ("flash", dump, {"color": COL["red"], "alpha": 0.3, "dur": 0.4}),
            ("glitch", dump, {"dur": 0.22}),
        ]

    def draw(self, cv, lt):
        d = self.d
        ms, ps, pk = self.series
        rise, dump = self.m("rise"), self.m("dump")
        mo, al = enter(lt, 0.0, 0.5)
        oy = (1 - mo) * 120

        place(cv, panel(920, 860, 40, top_fill=0.04), CX, 800 + oy, alpha=al)
        top = 800 - 430 + oy
        place(cv, text_sprite(f"${d['token']['symbol']}", "Black", 58, COL["white"]), 120, top + 70,
              anchor="lm", alpha=al)
        place(cv, text_sprite("Kurs live", "Text-Medium", 38, COL["muted"]), 960, top + 70,
              anchor="rm", alpha=al)

        if lt < dump:
            reveal = ms[pk] * e_in_out(prog(lt, rise, max(rise + 0.5, dump - 0.25)))
        else:
            reveal = ms[pk] + (ms[-1] - ms[pk]) * e_out(prog(lt, dump, dump + 0.6))
        k = int(np.searchsorted(ms, reveal))
        k = min(k, len(ps) - 1)
        cur = ps[k]

        # stat chips
        buyers = d["buyers"] * e_out(clamp(reveal / ms[pk]))
        place(cv, text_sprite("Käufer", "Text-Medium", 34, COL["muted"]), 120, top + 150,
              anchor="lm", alpha=al)
        place(cv, text_sprite(fmt_int(buyers), "Bold", 64, COL["white"], fixed_digits=True), 120,
              top + 210, anchor="lm", alpha=al)
        if lt < dump:
            gain = (cur - 1) * 100
            gtxt, gcol, glab = f"+{fmt_int(gain)} %", COL["green"], "seit Start"
        else:
            dd = (cur / ps[pk] - 1) * 100
            gtxt, gcol, glab = f"−{fmt_dec(-dd)} %", COL["red"], "seit Hoch"
        place(cv, text_sprite(glab, "Text-Medium", 34, COL["muted"]), 960, top + 150, anchor="rm",
              alpha=al)
        place(cv, text_sprite(gtxt, "Bold", 64, gcol, fixed_digits=True, glow=12), 960, top + 210,
              anchor="rm", alpha=al)

        # chart
        bx, by, bw, bh = 110, int(top + 280), 860, 540
        for i in range(1, 4):
            yy = by + bh * i / 4
            ImageDraw.Draw(cv).line([(bx + 10, yy), (bx + bw - 10, yy)],
                                    fill=tuple(COL["stroke"]) + (int(150 * al),), width=2)
        img, head, after = draw_series(bw, bh, ms, ps, reveal, pk, lw=7, glow=12)
        place(cv, img, bx, by, anchor="lt", alpha=al)
        if head:
            head_dot(cv, bx + head[0], by + head[1], COL["red"] if after else COL["green"], lt)

        # dump annotation
        if lt >= dump:
            px = bx + 10 + ms[pk] / ms[-1] * (bw - 20)
            a = clamp(prog(lt, dump, dump + 0.15))
            dashed_vline(cv, px, by + 20, by + bh - 10, COL["red"], alpha=a)
            k2 = prog(lt, dump + 0.08, dump + 0.45)
            lab = pill(f"ERSTELLER-WALLET VERKAUFT {d.get('dev_sold_pct', 100)} %", "Black", 34,
                       COL["white"], COL["red"])
            place(cv, lab, min(px, 960 - lab.width / 2), by + 40, anchor="mt",
                  scale=mix(0.6, 1, e_back(k2)) if k2 < 1 else 1, alpha=clamp(k2 * 3))
        # x axis
        place(cv, text_sprite("Minute 0", "Text-Medium", 30, COL["dim"]), bx + 10, by + bh + 30,
              anchor="lm", alpha=al)
        place(cv, text_sprite(f"Minute {int(round(ms[-1]))}", "Text-Medium", 30, COL["dim"]),
              bx + bw - 10, by + bh + 30, anchor="rm", alpha=al)


class Flags(Scene):
    """Three red flags that were visible on-chain before the rug."""

    def items(self):
        d = self.d
        return [
            ("f1", f"{d['dev_supply_pct']} % in Ersteller-Wallet", "Anteil am Gesamt-Supply"),
            ("f2", f"{d['bundle_wallets']} Wallets, 1 Block", "Gleichzeitige Käufe beim Start"),
            ("f3", f"{d['deployer_prior_rugs']} frühere Coins abgestürzt",
             f"Alle über −{d.get('prior_drop_threshold_pct', 90)} %, gleiche Ersteller-Wallet"),
        ]

    def events(self):
        ev = super().events()
        for mk, _, _ in self.items():
            ev.append(("sfx", self.sc.markers[mk], {"name": "alert", "gain": 0.55}))
            ev.append(("punch", self.sc.markers[mk], {"amt": 0.012, "dur": 0.25}))
        return ev

    def draw(self, cv, lt):
        mo, al = enter(lt, 0.0, 0.45)
        title = text_sprite("Die Signale", "Black", 92, COL["white"])
        icon = circle_icon(84, "warn", COL["yellow"])
        tw = title.width - 20 + icon.width + 20
        x0 = CX - tw / 2
        y = 360 - (1 - mo) * 50
        place(cv, icon, x0 + icon.width / 2, y, alpha=al)
        place(cv, title, x0 + icon.width + 10, y, anchor="lm", alpha=al)
        place(cv, text_sprite("Alle vorher on-chain sichtbar", "Text-Medium", 42, COL["muted"]),
              CX, 450, alpha=al)

        for i, (mk, big, small) in enumerate(self.items()):
            t0 = self.m(mk)
            if lt < t0:
                continue
            rm, ra = enter(lt, t0, 0.45)
            yc = 620 + i * 210
            xo = (1 - rm) * 160
            flash = 1 - prog(lt, t0, t0 + 0.5)
            card = panel(900, 176, 34, outline=mix_col(COL["stroke"], COL["red"], 0.35 + 0.65 * flash),
                         width=3, top_fill=0.04) if flash > 0.02 else panel(
                900, 176, 34, outline=mix_col(COL["stroke"], COL["red"], 0.35), width=3, top_fill=0.04)
            place(cv, card, CX + xo, yc, alpha=ra)
            place(cv, circle_icon(100, "x", COL["red"]), 175 + xo, yc, alpha=ra,
                  scale=mix(0.5, 1, rm) if rm < 1 else 1)
            place(cv, text_sprite(big, "Bold", fit_size(big, "Bold", 56, 650), COL["white"]),
                  255 + xo, yc - 26, anchor="lm",
                  alpha=ra)
            place(cv, text_sprite(small, "Text-Medium", fit_size(small, "Text-Medium", 36, 650),
                                  COL["muted"]), 257 + xo, yc + 34,
                  anchor="lm", alpha=ra)


class Loss(Scene):
    """Total buyer loss counter, then the follow call-to-action."""

    def events(self):
        loss, cta = self.sc.markers["loss"], self.sc.markers["cta"]
        return super().events() + [
            ("sfx", loss, {"name": "fall", "gain": 0.8}),
            ("sfx", loss + 1.05, {"name": "impact", "gain": 0.55}),
            ("shake", loss + 1.05, {"amp": 9, "dur": 0.3}),
            ("sfx", cta, {"name": "pop", "gain": 0.6}),
        ]

    def draw(self, cv, lt):
        d = self.d
        loss, cta = self.m("loss"), self.m("cta")
        mo, al = enter(lt, 0.0, 0.4)
        lab = d.get("loss_label", "Verlust der Käufer (geschätzt)")
        place(cv, text_sprite(lab, "SemiBold", 54, COL["muted"]), CX, 470 - (1 - mo) * 40, alpha=al)

        x = e_out(prog(lt, loss, loss + 1.05))
        val = d["buyer_loss_usd"] * x
        txt = f"−{fmt_int(val)} $"
        size = fit_size(f"−{fmt_int(d['buyer_loss_usd'])} $", "Black", 190, 940, True)
        land = prog(lt, loss + 1.05, loss + 1.3)
        scale = 1.0 + 0.12 * (1 - e_out(land)) * (land > 0)
        place(cv, text_sprite(txt, "Black", size, COL["red"], glow=28, glow_strength=1.3,
                              fixed_digits=True), CX, 640, scale=scale, alpha=al)
        note = d.get("loss_note", "Summe aller Käufer-Wallets, on-chain berechnet")
        place(cv, text_sprite(note, "Text-Medium", 32, COL["dim"]), CX, 770, alpha=al)

        if lt >= cta:
            cm, ca = enter(lt, cta, 0.45)
            ep = d.get("episode", 1)
            series = d.get("series", "RUG-CHECK")
            place(cv, pill(f"{series}  #{ep}", "Black", 44, COL["white"], COL["card2"],
                           outline=COL["stroke"], dot=COL["red"]), CX, 900 + (1 - cm) * 60, alpha=ca)
            place(cv, text_sprite(f"Morgen: Fall #{ep + 1}", "Black", 78, COL["white"]), CX,
                  1020 + (1 - cm) * 80, alpha=ca)
            fm, fa = enter(lt, cta + 0.25, 0.45)
            pulse = 1 + 0.045 * np.sin(max(0.0, lt - cta - 0.7) * 7)
            btn = ("Telegram · Link in Bio" if d.get("cta", {}).get("telegram") else "+  Folgen")
            place(cv, pill(btn, "Black", 50, COL["white"], COL["red"], pad_x=44, pad_y=20),
                  CX, 1145, scale=(mix(0.6, 1, fm) if fm < 1 else 1) * pulse, alpha=fa)
            place(cv, text_sprite("Nur On-Chain-Daten · keine Finanzberatung", "Text-Medium", 30,
                                  COL["dim"]), CX, 1222, alpha=fa)


SCENES = {"hook": Hook, "card": Card, "chart": Chart, "flags": Flags, "loss": Loss}
