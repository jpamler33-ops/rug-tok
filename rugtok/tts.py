"""Text-to-speech + word timing.

Providers:
  edge  - Microsoft neural voices via `edge-tts` (best quality, free, needs internet)
  piper - local neural TTS (vendor/piper + vendor/voices), offline fallback

Word timings are estimated from syllable weights inside the voiced region of each
sentence and snapped to real pauses in the audio at punctuation. One code path for
every provider, no forced-alignment model needed.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
import wave
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

from .config import (GAP_SCENE, GAP_SENTENCE, LEAD_IN, SR, TAIL, VENDOR)
from .text_de import syllables

EDGE_VOICE = os.environ.get("RUGTOK_EDGE_VOICE", "de-DE-ConradNeural")
EDGE_RATE = os.environ.get("RUGTOK_EDGE_RATE", "+8%")
PIPER_BIN = VENDOR / "piper" / "piper"
PIPER_MODEL = Path(os.environ.get("RUGTOK_PIPER_MODEL", VENDOR / "voices" / "de-thorsten-low.onnx"))
PIPER_LENGTH = os.environ.get("RUGTOK_PIPER_LENGTH", "0.86")  # <1 = faster speech


def _read_wav(path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError(f"Expected 16-bit wav, got {sw * 8}-bit")
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def _to_sr(a: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return a
    g = gcd(sr, SR)
    return resample_poly(a, SR // g, sr // g).astype(np.float32)


def _decode_to_wav(src: Path, dst: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1",
                    "-ar", str(SR), "-sample_fmt", "s16", str(dst)], check=True)


class PiperTTS:
    name = "piper"

    def available(self) -> bool:
        return PIPER_BIN.exists() and PIPER_MODEL.exists()

    def synth(self, text: str) -> np.ndarray:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "s.wav"
            env = dict(os.environ, LD_LIBRARY_PATH=str(PIPER_BIN.parent))
            subprocess.run([str(PIPER_BIN), "--model", str(PIPER_MODEL), "--output_file", str(out),
                            "--length_scale", PIPER_LENGTH, "--sentence_silence", "0"],
                           input=text.encode("utf-8"), env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            a, sr = _read_wav(out)
        return _to_sr(a, sr)


class EdgeTTS:
    name = "edge"

    def available(self) -> bool:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False
        return shutil.which("ffmpeg") is not None

    def synth(self, text: str) -> np.ndarray:
        import edge_tts

        async def run(path):
            comm = edge_tts.Communicate(text, EDGE_VOICE, rate=EDGE_RATE)
            await asyncio.wait_for(comm.save(str(path)), timeout=30)

        with tempfile.TemporaryDirectory() as td:
            mp3, wav = Path(td) / "s.mp3", Path(td) / "s.wav"
            asyncio.run(run(mp3))
            _decode_to_wav(mp3, wav)
            a, sr = _read_wav(wav)
        return _to_sr(a, sr)


def get_tts(pref: str = "auto"):
    order = {"auto": [EdgeTTS, PiperTTS], "edge": [EdgeTTS], "piper": [PiperTTS]}[pref]
    for cls in order:
        eng = cls()
        if eng.available():
            return eng
    raise RuntimeError("No TTS engine available. Install edge-tts or run scripts/setup_piper.sh")


# ---------------------------------------------------------------- timing ----

def _envelope(a: np.ndarray, hop: int = 480) -> np.ndarray:
    """RMS in 10 ms frames, in dB relative to the sentence peak."""
    n = len(a) // hop
    if n == 0:
        return np.array([-80.0])
    fr = a[: n * hop].reshape(n, hop)
    rms = np.sqrt((fr ** 2).mean(axis=1) + 1e-12)
    return 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-9)


def trim(a: np.ndarray, thresh_db: float = -38, pad: float = 0.03) -> np.ndarray:
    env = _envelope(a)
    voiced = np.where(env > thresh_db)[0]
    if len(voiced) == 0:
        return a
    s = max(0, voiced[0] * 480 - int(pad * SR))
    e = min(len(a), (voiced[-1] + 1) * 480 + int(pad * SR))
    return a[s:e]


def _pauses(a: np.ndarray, thresh_db: float = -34, min_len: float = 0.05):
    """Silent runs inside the sentence -> list of (start, end) seconds."""
    env = _envelope(a)
    quiet = env < thresh_db
    runs, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) * 0.01 >= min_len and i > 0 and j < len(quiet):
                runs.append((i * 0.01, j * 0.01))
            i = j
        else:
            i += 1
    return runs


def word_times(sentence, audio: np.ndarray) -> list[tuple[float, float]]:
    """Estimate (start, end) per word, relative to sentence start."""
    words = sentence.words
    dur = len(audio) / SR
    w = np.array([syllables(x.say) for x in words], dtype=float)
    pause_after = np.array([0.9 if x.say.rstrip()[-1:] in ",.:;!?" else 0.0 for x in words])
    pause_after[-1] = 0.0
    total = w.sum() + pause_after.sum()
    # proportional layout
    t, bounds = 0.03, []
    usable = max(0.1, dur - 0.06)
    for wi, pa in zip(w, pause_after):
        s = t
        t += usable * wi / total
        bounds.append([s, t])
        t += usable * pa / total
    # snap punctuation boundaries to real pauses
    pauses = _pauses(audio)
    for i, x in enumerate(words[:-1]):
        if pause_after[i] <= 0 or not pauses:
            continue
        guess = bounds[i][1]
        p = min(pauses, key=lambda r: abs((r[0] + r[1]) / 2 - guess))
        if abs((p[0] + p[1]) / 2 - guess) < 0.45:
            bounds[i][1] = p[0]
            bounds[i + 1][0] = p[1]
    # re-distribute words between pinned points so nothing overlaps
    for i in range(1, len(bounds)):
        if bounds[i][0] < bounds[i - 1][1]:
            bounds[i][0] = bounds[i - 1][1]
        if bounds[i][1] <= bounds[i][0]:
            bounds[i][1] = bounds[i][0] + 0.08
    return [(s, e) for s, e in bounds]


def build_timeline(scenes, tts, log=print) -> float:
    """Synthesize every sentence, place it on the timeline, fill word/marker times.
    Returns total video duration (seconds)."""
    t = LEAD_IN
    for si, sc in enumerate(scenes):
        if si > 0:
            t += GAP_SCENE
        sc.start = 0.0 if si == 0 else t - 0.12
        for sen in sc.sentences:
            audio = trim(tts.synth(sen.say_text))
            sen.audio, sen.start, sen.dur = audio, t, len(audio) / SR
            for word, (ws, we) in zip(sen.words, word_times(sen, audio)):
                word.start, word.end = t + ws, t + we
                if word.marker:
                    sc.markers[word.marker] = word.start
            log(f"  [{tts.name}] {t:6.2f}s +{sen.dur:4.2f}s  {sen.say_text}")
            t += sen.dur + GAP_SENTENCE
        t -= GAP_SENTENCE
        t += sc.hold
    total = t + TAIL
    for i, sc in enumerate(scenes):
        sc.end = scenes[i + 1].start if i + 1 < len(scenes) else total
    return total


def voice_track(scenes, total: float) -> np.ndarray:
    out = np.zeros(int(total * SR) + SR, dtype=np.float32)
    for sc in scenes:
        for sen in sc.sentences:
            s = int(sen.start * SR)
            out[s: s + len(sen.audio)] += sen.audio
    return out[: int(total * SR)]
