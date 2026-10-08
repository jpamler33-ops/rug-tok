"""Synthesized sound design (no samples, no licensing issues) + mix with ducking."""
import subprocess
import wave

import numpy as np
from scipy.signal import butter, sosfilt

from .config import SR

rng = np.random.default_rng(11)


def _t(dur):
    return np.arange(int(dur * SR)) / SR


def _env(n, a=0.005, decay=0.2, shape=1.0):
    t = np.arange(n) / SR
    att = np.clip(t / max(a, 1e-4), 0, 1)
    return att * np.exp(-t / max(decay, 1e-4)) ** shape


def _bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], btype="band", fs=SR, output="sos"), x)


def _lp(x, f, order=2):
    return sosfilt(butter(order, f, btype="low", fs=SR, output="sos"), x)


def _hp(x, f, order=2):
    return sosfilt(butter(order, f, btype="high", fs=SR, output="sos"), x)


def _sweep(f0, f1, dur, curve="exp"):
    t = _t(dur)
    if curve == "exp":
        f = f0 * (f1 / f0) ** (t / dur)
    else:
        f = f0 + (f1 - f0) * t / dur
    return np.sin(2 * np.pi * np.cumsum(f) / SR)


def whoosh(dur=0.38):
    n = int(dur * SR)
    noise = rng.normal(0, 1, n)
    x = 0.6 * _bp(noise, 300, 2500) + 0.4 * _bp(noise, 2500, 9000)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t ** 0.6) ** 2
    return x * env * 0.5


def impact(dur=0.6):
    sub = _sweep(110, 38, dur) * _env(int(dur * SR), 0.002, 0.22)
    click = _hp(rng.normal(0, 1, int(dur * SR)), 2000) * _env(int(dur * SR), 0.0005, 0.012)
    return np.tanh((sub * 1.4 + click * 0.5) * 1.6) * 0.8


def boom(dur=1.4):
    n = int(dur * SR)
    sub = _sweep(140, 30, dur) * _env(n, 0.002, 0.45)
    body = _lp(rng.normal(0, 1, n), 900) * _env(n, 0.001, 0.12) * 1.8
    crack = _hp(rng.normal(0, 1, n), 3000) * _env(n, 0.0005, 0.02)
    return np.tanh((sub * 1.6 + body + crack * 0.6) * 1.8) * 0.9


def riser(dur=2.0):
    dur = max(0.4, dur)
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    tone = 0.5 * _sweep(180, 900, dur) + 0.3 * _sweep(181.5, 905, dur)
    noise = _bp(rng.normal(0, 1, n), 1500, 7000) * 0.35
    env = t ** 2.2
    return (tone + noise) * env * 0.35


def fall(dur=1.1):
    n = int(dur * SR)
    t = np.linspace(0, 1, n)
    tone = _sweep(700, 70, dur) + 0.4 * _sweep(1050, 105, dur)
    trem = 0.7 + 0.3 * np.sin(2 * np.pi * 9 * t)
    return np.tanh(tone * 1.3) * trem * (1 - t) ** 1.2 * 0.35


def pop(dur=0.12):
    return _sweep(900, 320, dur) * _env(int(dur * SR), 0.001, 0.035) * 0.6


def alert(dur=0.32):
    n = int(dur * SR)
    a = np.sin(2 * np.pi * 880 * _t(dur)) + 0.5 * np.sin(2 * np.pi * 1320 * _t(dur))
    gate = np.where(_t(dur) % 0.16 < 0.1, 1.0, 0.0)
    return a * gate * _env(n, 0.002, 0.25) * 0.28 + impact(dur) * 0.35


def stamp(dur=0.5):
    n = int(dur * SR)
    thud = _sweep(180, 50, dur) * _env(n, 0.001, 0.09)
    slap = _bp(rng.normal(0, 1, n), 400, 4000) * _env(n, 0.0005, 0.03)
    return np.tanh((thud * 1.8 + slap * 0.9) * 1.5) * 0.85


def glitch(dur=0.3):
    n = int(dur * SR)
    x = np.sign(np.sin(2 * np.pi * rng.choice([180, 360, 720, 1440], n // 800 + 1).repeat(800)[:n]
                       * _t(dur)))
    gate = (rng.random(n // 600 + 1) > 0.35).repeat(600)[:n]
    return _lp(x * gate, 5000) * 0.18


SFX = {"whoosh": whoosh, "impact": impact, "boom": boom, "riser": riser, "fall": fall,
       "pop": pop, "alert": alert, "stamp": stamp, "glitch": glitch}


def bed(total, bpm=100):
    """Dark minimal pulse: sub kick on beats, soft hats on 8ths, filtered pad."""
    n = int(total * SR)
    out = np.zeros(n)
    beat = 60 / bpm
    kick = _sweep(90, 42, 0.35) * _env(int(0.35 * SR), 0.003, 0.12)
    hat = _hp(rng.normal(0, 1, int(0.05 * SR)), 8000, order=4) * _env(int(0.05 * SR), 0.002, 0.010)
    t = 0.0
    i = 0
    while t < total:
        s = int(t * SR)
        if i % 2 == 0:
            seg = kick[: n - s]
            out[s: s + len(seg)] += seg * 0.9
        else:
            seg = hat[: n - s]
            out[s: s + len(seg)] += seg * 0.12
        t += beat / 2
        i += 1
    tt = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tt + p) for f, p in ((110, 0), (130.8, 1), (164.8, 2), (110.4, 3)))
    pad = _lp(pad, 700) * (0.6 + 0.4 * np.sin(2 * np.pi * tt / (beat * 8)))
    out += pad * 0.05
    fade = np.minimum(1, np.minimum(tt / 0.8, (total - tt) / 1.0))
    return out * np.clip(fade, 0, 1)


def _write_wav(path, x):
    x = np.clip(x, -1, 1)
    st = np.repeat((x * 32767).astype(np.int16)[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(st.tobytes())


def _read_wav_mono(path):
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        ch = w.getnchannels()
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    return a.reshape(-1, ch).mean(axis=1) if ch > 1 else a


def process_voice(vo, workdir):
    """Broadcast-style chain via ffmpeg: rumble cut, presence lift, compression."""
    raw, proc = workdir / "vo_raw.wav", workdir / "vo_proc.wav"
    _write_wav(raw, vo)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-af",
                    "highpass=f=85,equalizer=f=220:t=q:w=1:g=-2,equalizer=f=3200:t=q:w=1.2:g=4,"
                    "acompressor=threshold=-20dB:ratio=3.5:attack=4:release=90:makeup=3",
                    "-ar", str(SR), str(proc)], check=True)
    out = _read_wav_mono(proc)
    if len(out) < len(vo):
        out = np.pad(out, (0, len(vo) - len(out)))
    return out[: len(vo)]


def mix(vo, events, total, workdir, music=True):
    n = int(total * SR)
    vo = process_voice(vo[:n], workdir)
    fx = np.zeros(n)
    for kind, t, p in events:
        if kind != "sfx":
            continue
        fn = SFX[p["name"]]
        clip = fn(p["dur"]) if "dur" in p else fn()
        s = int(max(0, t) * SR)
        seg = clip[: max(0, n - s)]
        fx[s: s + len(seg)] += seg * p.get("gain", 1.0)
    out = vo * 1.0 + fx * 0.42
    if music:
        b = bed(total)
        # sidechain ducking under the voice (envelope follower)
        env = np.abs(vo)
        k = int(0.08 * SR)
        env = np.convolve(env, np.ones(k) / k, mode="same")
        duck = 1 - 0.65 * np.clip(env / (env.max() * 0.25 + 1e-9), 0, 1)
        out += b * 0.22 * duck
    peak = np.abs(out).max()
    if peak > 0.98:
        out = out / peak * 0.98
    path = workdir / "mix.wav"
    _write_wav(path, out)
    return path
