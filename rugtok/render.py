"""Frame loop: background -> scene -> overlays -> captions -> effects -> ffmpeg."""
import subprocess
import time

import numpy as np
from PIL import Image, ImageChops, ImageDraw

from .captions import draw_captions, make_chunks
from .config import CAPTION_Y, COL, FPS, H, W
from .gfx import comp, e_out, make_background, make_grain, pill, place, prog
from .scenes import SCENES, price_series

EXIT = 0.16  # scene cross-out duration


class Video:
    def __init__(self, scenes_script, data, total):
        self.data, self.total = data, total
        self.series = price_series(data)
        self.scenes = [SCENES[s.kind](s, data, self.series) for s in scenes_script]
        self.events = sorted((e for s in self.scenes for e in s.events()), key=lambda e: e[1])
        self.chunks = make_chunks(scenes_script)
        self.bg = make_background()
        self.grain = make_grain()

    # ------------------------------------------------------------- effects --
    def _shake(self, t):
        dx = dy = 0.0
        for kind, t0, p in self.events:
            if kind == "shake" and t0 <= t < t0 + p["dur"]:
                k = 1 - (t - t0) / p["dur"]
                a = p["amp"] * k * k
                dx += a * np.sin(t * 91.0 + t0)
                dy += a * np.cos(t * 77.0 + t0 * 3)
        return dx, dy

    def _punch(self, t):
        s = 1.0
        for kind, t0, p in self.events:
            if kind == "punch" and t0 <= t < t0 + p["dur"]:
                s += p["amt"] * (1 - e_out((t - t0) / p["dur"]))
        return s

    def _flash(self, cv, t):
        for kind, t0, p in self.events:
            if kind == "flash" and t0 <= t < t0 + p["dur"]:
                a = p["alpha"] * (1 - (t - t0) / p["dur"]) ** 2
                ov = Image.new("RGBA", cv.size, tuple(p["color"]) + (int(255 * a),))
                cv.alpha_composite(ov)

    def _glitch(self, frame, t):
        for kind, t0, p in self.events:
            if kind == "glitch" and t0 <= t < t0 + p["dur"]:
                k = 1 - (t - t0) / p["dur"]
                off = int(16 * k * (1 if int(t * 60) % 2 else -1))
                r, g, b = frame.split()
                r = ImageChops.offset(r, off, 0)
                b = ImageChops.offset(b, -off, 0)
                frame = Image.merge("RGB", (r, g, b))
                # horizontal slice displacement
                rng = np.random.default_rng(int(t * 1000))
                for _ in range(3):
                    y = int(rng.integers(200, H - 400))
                    hgt = int(rng.integers(20, 90))
                    sl = frame.crop((0, y, W, y + hgt))
                    frame.paste(ImageChops.offset(sl, int(rng.integers(-60, 60)), 0), (0, y))
        return frame

    # ------------------------------------------------------------ overlays --
    def _overlays(self, cv, t):
        d = self.data
        # progress bar (signals 'short video' -> better completion)
        ImageDraw.Draw(cv).rectangle([0, 0, int(W * t / self.total), 7],
                                     fill=tuple(COL["red"]) + (230,))
        badge = pill(f"RUG DES TAGES  #{d.get('episode', 1)}", "Bold", 34, COL["white"],
                     (12, 12, 18), outline=COL["stroke"], dot=COL["red"], bg_alpha=200)
        blink = 0.75 + 0.25 * np.sin(t * 5)
        place(cv, badge, 60, 230, anchor="lm", alpha=blink if t > 0.1 else 1)
        if d.get("demo", True):
            place(cv, pill("DEMO-DATEN", "Black", 30, COL["red"], (30, 0, 8), outline=COL["red"],
                           bg_alpha=200), W - 60, 230, anchor="rm")

    # --------------------------------------------------------------- frame --
    def frame(self, t) -> Image.Image:
        cv = self.bg.copy()
        for i, sc in enumerate(self.scenes):
            if sc.start <= t < sc.start + sc.dur or (i == len(self.scenes) - 1 and t >= sc.start):
                lt = t - sc.start
                last = i == len(self.scenes) - 1
                if not last and lt > sc.dur - EXIT:
                    layer = Image.new("RGBA", cv.size, (0, 0, 0, 0))
                    sc.draw(layer, lt)
                    k = prog(lt, sc.dur - EXIT, sc.dur)
                    place(cv, layer, W / 2, H / 2, scale=1 - 0.05 * k, alpha=1 - k)
                else:
                    sc.draw(cv, lt)
                break
        punch = self._punch(t)
        if punch > 1.0005:
            big = cv.resize((int(W * punch), int(H * punch)), Image.BILINEAR)
            cv = big.crop(((big.width - W) // 2, (big.height - H) // 2,
                           (big.width - W) // 2 + W, (big.height - H) // 2 + H))
        dx, dy = self._shake(t)
        if abs(dx) + abs(dy) > 0.5:
            shaken = self.bg.copy()
            comp(shaken, cv, dx, dy)
            cv = shaken
        self._flash(cv, t)
        self._overlays(cv, t)
        draw_captions(cv, self.chunks, t, CAPTION_Y)
        cv.alpha_composite(self.grain[int(t * FPS) % len(self.grain)])
        return self._glitch(cv.convert("RGB"), t)

    def render(self, out_path, audio_path, log=print, preview_every=None, preview_dir=None):
        n = int(self.total * FPS)
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
               "-i", str(audio_path),
               "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
               "-profile:v", "high", "-g", str(FPS * 2),
               "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k",
               "-ar", "48000", "-movflags", "+faststart", "-shortest", str(out_path)]
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        t0 = time.time()
        try:
            for i in range(n):
                t = i / FPS
                fr = self.frame(t)
                if preview_every and i % preview_every == 0 and preview_dir:
                    fr.save(preview_dir / f"f_{i:04d}.jpg", quality=88)
                p.stdin.write(fr.tobytes())
                if i % (FPS * 5) == 0:
                    el = time.time() - t0
                    log(f"  frame {i}/{n}  ({el:.0f}s, {el / max(1, i):.3f}s/frame)")
        finally:
            p.stdin.close()
            rc = p.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {rc}")
