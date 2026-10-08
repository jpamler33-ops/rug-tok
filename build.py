#!/usr/bin/env python3
"""Build one 'Rug des Tages' TikTok video from a data file.

  python3 build.py content/demo_rug.json                  # full video -> out/
  python3 build.py content/demo_rug.json --stills 1,4.7,9  # quick PNG checks, no encoding
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from rugtok.audio import mix
from rugtok.config import ROOT
from rugtok.render import Video
from rugtok.script import rug_des_tages
from rugtok.tts import build_timeline, get_tts, voice_track

REQUIRED = ["token", "launch_time", "initial_liquidity_usd", "minutes_to_peak", "peak_gain_pct",
            "minutes_peak_to_dead", "drawdown_pct", "buyers", "dev_supply_pct", "bundle_wallets",
            "deployer_prior_rugs", "buyer_loss_usd"]


def validate(d):
    missing = [k for k in REQUIRED if k not in d]
    if missing:
        sys.exit(f"Data file is missing fields: {', '.join(missing)}")
    if not 0 < d["drawdown_pct"] <= 100:
        sys.exit("drawdown_pct must be in (0, 100]")
    if d["minutes_to_peak"] <= 0 or d["minutes_peak_to_dead"] <= 0:
        sys.exit("minute values must be > 0")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tts", default="auto", choices=["auto", "edge", "piper"])
    ap.add_argument("--no-music", action="store_true")
    ap.add_argument("--stills", default=None, help="comma separated seconds, writes PNGs only")
    ap.add_argument("--preview-every", type=int, default=0, help="save every Nth frame as JPG")
    a = ap.parse_args()

    data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    validate(data)
    stem = Path(a.data).stem
    out = Path(a.out) if a.out else ROOT / "out" / f"{stem}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    tts = get_tts(a.tts)
    print(f"Voice: {tts.name}")
    script = rug_des_tages(data)
    total = build_timeline(script, tts)
    print(f"Duration: {total:.1f}s")
    video = Video(script, data, total)

    if a.stills:
        sd = out.parent / f"{stem}_stills"
        sd.mkdir(exist_ok=True)
        for s in a.stills.split(","):
            video.frame(float(s)).save(sd / f"t{float(s):05.2f}.png")
        print(f"Stills -> {sd}")
        return

    with tempfile.TemporaryDirectory() as td:
        audio = mix(voice_track(script, total), video.events, total, Path(td), music=not a.no_music)
        pdir = None
        if a.preview_every:
            pdir = out.parent / f"{stem}_frames"
            pdir.mkdir(exist_ok=True)
        video.render(out, audio, preview_every=a.preview_every, preview_dir=pdir)
    print(f"Done: {out}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
