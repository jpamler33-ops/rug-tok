"""Global settings: format, colors, fonts, timing."""
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "assets" / "fonts"
VENDOR = ROOT / "vendor"

# TikTok: 9:16, 1080x1920, 30 fps
W, H, FPS = 1080, 1920, 30
SR = 48000  # audio sample rate

# Safe zones (TikTok UI covers top bar, right action column, bottom caption area)
SAFE_TOP = 170
SAFE_BOTTOM = 1500      # nothing important below this y
SAFE_RIGHT = 950        # right action buttons start around here (y 700-1500)
CAPTION_Y = 1330        # vertical center of subtitles

# Narration pacing (seconds)
LEAD_IN = 0.12
GAP_SENTENCE = 0.16
GAP_SCENE = 0.28
TAIL = 1.4

COL = {
    "bg0": (6, 6, 10),
    "bg1": (22, 13, 30),
    "white": (246, 246, 250),
    "muted": (150, 150, 170),
    "dim": (90, 90, 110),
    "green": (36, 242, 140),
    "red": (255, 48, 82),
    "yellow": (255, 226, 72),
    "card": (20, 20, 29),
    "card2": (28, 27, 40),
    "stroke": (52, 50, 70),
    "black": (0, 0, 0),
}


@lru_cache(maxsize=256)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """weight e.g. 'Black', 'Bold', 'SemiBold' -> Inter Display; 'Text-Medium' -> Inter."""
    if weight.startswith("Text-"):
        name = f"Inter-{weight[5:]}.otf"
    else:
        name = f"InterDisplay-{weight}.otf"
    for base in (FONT_DIR, Path("/usr/share/fonts/opentype/inter")):
        p = base / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    raise FileNotFoundError(f"Font not found: {name} (expected in {FONT_DIR})")
