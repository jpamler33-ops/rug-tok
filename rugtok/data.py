"""Input schema + validation. Real (non-demo) videos must be fully backed by verifiable data."""
import re

import numpy as np

from .text_de import fmt_dec, fmt_int

REQUIRED = ["token", "launch_time", "peak_market_cap_usd", "minutes_to_peak", "peak_gain_pct",
            "minutes_peak_to_dead", "drawdown_pct", "buyers", "buyer_loss_usd"]
REQUIRED_REAL = ["contract_address", "price_series", "sources", "loss_method"]
FLAG_FIELDS = {"creator_hold": ["pct"], "bundle": ["wallets"], "prior": ["bad", "total"]}
BASE58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEAD_LEVEL = 0.10  # 'tot' = first point at or below 10 % of the peak price (−90 %)


class DataError(ValueError):
    pass


def short_ca(ca: str) -> str:
    return f"{ca[:4]}…{ca[-4:]}" if ca and len(ca) > 10 else ca or ""


def series_stats(series):
    """price_series [[minute, price], ...] -> the key numbers the video states.
    peak = highest price; dead = first point after the peak at/below DEAD_LEVEL * peak
    (falls back to the lowest point); drawdown = peak -> lowest point after the peak."""
    a = np.asarray(series, dtype=float)
    m, p = a[:, 0], a[:, 1]
    pk = int(np.argmax(p))
    after = p[pk:]
    low = after.min()
    hit = np.where(after <= p[pk] * DEAD_LEVEL)[0]
    dead_idx = pk + (int(hit[0]) if len(hit) else int(np.argmin(after)))
    return {"peak_gain_pct": (p[pk] / p[0] - 1) * 100,
            "minutes_to_peak": m[pk] - m[0],
            "drawdown_pct": (1 - low / p[pk]) * 100,
            "minutes_peak_to_dead": m[dead_idx] - m[pk],
            "peak_index": pk}


def validate(d: dict) -> list:
    """Raises DataError on hard problems. Returns a list of warnings."""
    errs, warns = [], []
    for k in REQUIRED:
        if k not in d:
            errs.append(f"fehlt: {k}")
    if errs:
        raise DataError("; ".join(errs))
    if not 0 < d["drawdown_pct"] <= 100:
        errs.append("drawdown_pct muss in (0, 100] liegen")
    if d["minutes_to_peak"] <= 0 or d["minutes_peak_to_dead"] <= 0:
        errs.append("Minutenwerte müssen > 0 sein")
    if not re.match(r"^\d{1,2}:\d{2}$", str(d["launch_time"])):
        errs.append("launch_time muss HH:MM sein")
    if not re.match(r"^[A-Za-z0-9]{1,12}$", str(d["token"].get("symbol", ""))):
        errs.append("token.symbol muss 1-12 Zeichen A-Z/0-9 sein")
    for f in d.get("flags", []):
        need = FLAG_FIELDS.get(f.get("kind"))
        if need is None:
            errs.append(f"unbekannter flag kind: {f.get('kind')}")
        elif any(k not in f for k in need):
            errs.append(f"flag {f['kind']} braucht {need}")
        elif f["kind"] == "prior" and not 0 < f["bad"] <= f["total"]:
            errs.append("flag prior: 0 < bad <= total")
        elif "pct" in f and not 0 < f["pct"] <= 100:
            errs.append(f"flag {f['kind']}: pct {f['pct']} nicht in (0, 100]")
    crash = d.get("crash", {})
    if crash.get("single_tx") and not crash.get("sold_all"):
        errs.append("crash.single_tx nur zusammen mit sold_all")

    if not d.get("demo", True):
        for k in REQUIRED_REAL:
            if not d.get(k):
                errs.append(f"echtes Video braucht: {k}")
        ca = d.get("contract_address", "")
        if ca and not BASE58.match(ca):
            errs.append("contract_address ist keine gültige Solana-Adresse")
        src = d.get("sources") or []
        if any(not str(u).startswith("https://") for u in src):
            errs.append("sources müssen https-Links sein")
        ser = d.get("price_series")
        if ser:
            a = np.asarray(ser, dtype=float)
            if a.ndim != 2 or a.shape[1] != 2 or len(a) < 20:
                errs.append("price_series braucht >= 20 Punkte [minute, preis]")
            elif np.any(np.diff(a[:, 0]) <= 0) or np.any(a[:, 1] <= 0):
                errs.append("price_series: Minuten steigend, Preise > 0")
            else:
                st = series_stats(ser)
                checks = [("peak_gain_pct", 0.03, "rel"), ("drawdown_pct", 0.5, "abs"),
                          ("minutes_to_peak", 0.75, "abs"), ("minutes_peak_to_dead", 0.75, "abs")]
                for key, tol, mode in checks:
                    want, got = float(d[key]), st[key]
                    bad = abs(want - got) > (tol * abs(got) if mode == "rel" else tol)
                    if bad:
                        errs.append(f"{key}={want} passt nicht zur price_series ({got:.2f})")
    if errs:
        raise DataError("; ".join(errs))
    if d.get("demo", True):
        warns.append("DEMO-Daten: Video wird mit Wasserzeichen gerendert und darf nicht gepostet werden.")
    return warns


def tiktok_description(d: dict) -> str:
    """Post text: facts, full contract address, sources, method, disclaimer, hashtags."""
    tok = d["token"]
    lines = [
        f"{d.get('series', 'RUG-CHECK')} #{d.get('episode', 1)}: ${tok['symbol']} "
        f"+{fmt_int(d['peak_gain_pct'])} % → −{fmt_dec(d['drawdown_pct'])} %",
        "",
        f"Contract: {d.get('contract_address', '(DEMO)')}",
    ]
    for u in d.get("sources", []):
        lines.append(f"Quelle: {u}")
    if d.get("loss_method"):
        lines.append(f"Verlust-Berechnung: {d['loss_method']}")
    lines += ["", "Nur öffentliche On-Chain-Daten. Keine Finanzberatung, keine Kaufempfehlung.",
              "", "#krypto #solana #memecoin #rugpull #onchain"]
    return "\n".join(lines)
