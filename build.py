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
from rugtok.data import DataError, tiktok_description, validate
from rugtok.render import Video
from rugtok.script import rug_des_tages
from rugtok.tts import build_timeline, get_tts, voice_track

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
    try:
        for w in validate(data):
            print("WARNUNG:", w)
    except DataError as e:
        sys.exit(f"Daten ungültig: {e}")
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
    desc = out.with_name(out.stem + "_beschreibung.txt")
    desc.write_text(tiktok_description(data), encoding="utf-8")
    print(f"Done: {out}  ({time.time() - t0:.0f}s)\nBeschreibung: {desc}")


if __name__ == "__main__":
    main()
