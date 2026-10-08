"""Finds yesterday's most striking crash on Solana and turns it into a video data file.

Data source: Solana Tracker Data API (free plan: 10,000 requests/month, 3 req/s).
One run uses ~20-40 requests. Every raw API response is archived next to the output
so each number in the video can be traced back (evidence trail).

Only facts the API proves end up in the JSON. Anything uncertain is left out, and the
template then simply doesn't say it (see script.py).
"""
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .data import BASE58, DEAD_LEVEL, series_stats

API = "https://data.solanatracker.io"
TZ = ZoneInfo(os.environ.get("RUGTOK_TZ", "Europe/Berlin"))

# selection rules: what counts as a 'case'
MIN_GAIN_PCT = 300          # at least +300 % from first trade to peak
MIN_DRAWDOWN_PCT = 90       # at least −90 % from peak
MAX_MIN_TO_PEAK = 180
MAX_MIN_PEAK_TO_DEAD = 60
MIN_BUYERS = 100
PRIOR_THRESHOLD_PCT = 90
MAX_PRIOR_CHECKS = 8
# A crash = lots of trading volume, but almost no market cap left now.
SEARCH_MIN_VOLUME_24H = 30_000
SEARCH_MAX_MARKET_CAP = 15_000
# Symbols we never put on screen (platform guidelines)
BLOCKED_SYMBOLS = {"TITS", "PORN", "SEX", "CUM", "NAZI", "HITLER", "NIGGA", "FUCK", "SHIT",
                   "COCK", "DICK", "PUSSY", "ASS", "RAPE", "KKK", "JEW", "ISIS"}


class BudgetExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


class Client:
    """Tiny HTTP client: rate limit, retries with backoff, request budget, raw archive."""

    def __init__(self, api_key, budget=80, min_interval=0.4, archive_dir=None, timeout=20,
                 opener=None):
        if not api_key:
            raise ApiError("SOLANATRACKER_API_KEY fehlt")
        self.key, self.budget, self.min_interval = api_key, budget, min_interval
        self.timeout, self.used, self._last = timeout, 0, 0.0
        self.archive_dir = Path(archive_dir) if archive_dir else None
        self._open = opener or urllib.request.urlopen

    def get(self, path, params=None, tries=4):
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(tries):
            if self.used >= self.budget:
                raise BudgetExceeded(f"Request-Budget ({self.budget}) aufgebraucht")
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            self.used += 1
            req = urllib.request.Request(url, headers={"x-api-key": self.key,
                                                       "accept": "application/json",
                                                       "user-agent": "rug-tok/1.0"})
            try:
                with self._open(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode("utf-8"))
                self._archive(path, params, body)
                return body
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    ra = e.headers.get("Retry-After") if e.headers else None
                    time.sleep(float(ra) if ra and ra.isdigit() else 2 ** attempt)
                    continue
                raise ApiError(f"HTTP {e.code} bei {path}") from e
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if attempt < tries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise ApiError(f"{type(e).__name__} bei {path}: {e}") from e
        raise ApiError(f"Keine Antwort von {path}")

    def _archive(self, path, params, body):
        if not self.archive_dir:
            return
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        name = path.strip("/").replace("/", "_")[:120]
        if params:
            name += "__" + "_".join(f"{k}-{v}" for k, v in sorted(params.items()))[:80]
        (self.archive_dir / f"{self.used:03d}_{name}.json").write_text(
            json.dumps({"path": path, "params": params, "fetched_at": time.time(), "body": body},
                       ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------- parsing --

def to_ms(t):
    """API timestamps come as seconds or milliseconds. Normalize to ms."""
    if t is None:
        return None
    t = float(t)
    return int(t * 1000) if t < 1e11 else int(t)


def rows(body, *keys):
    """Return the list inside a response, whatever key the API wraps it in."""
    if isinstance(body, list):
        return body
    for k in keys + ("data", "tokens", "oclhv", "traders", "wallets"):
        v = body.get(k) if isinstance(body, dict) else None
        if isinstance(v, list):
            return v
    return []


def candles_to_series(body):
    """Chart response -> ([[minute, price], ...], first_candle_ms).
    Minute 0 is the open of the first candle."""
    cs = [c for c in rows(body, "oclhv") if c.get("close") is not None and c.get("time")]
    cs.sort(key=lambda c: c["time"])
    if len(cs) < 2:
        return [], None
    t0 = to_ms(cs[0]["time"])
    first_open = float(cs[0].get("open") or cs[0]["close"])
    out = [[0.0, first_open]]
    for c in cs:
        m = (to_ms(c["time"]) - t0) / 60000 + 0.0001  # candle close ~ after its open
        if m > out[-1][0] and float(c["close"]) > 0:
            out.append([round(m, 4), float(c["close"])])
    return out, t0


def trim_series(series, pad_frac=0.25):
    """Cut the series a bit after 'dead' so the chart shows the story, not hours of zero."""
    st = series_stats(series)
    end_m = st["minutes_to_peak"] + st["minutes_peak_to_dead"]
    end_m += max(1.0, pad_frac * end_m)
    return [p for p in series if p[0] <= end_m]


def pick_interval(span_min):
    """Finest candle size that still keeps the request small, >= ~40 points over the span."""
    for name, sec in (("5s", 5), ("15s", 15), ("1m", 60), ("3m", 180), ("5m", 300)):
        if span_min * 60 / sec <= 400:
            return name
    return "15m"


def evaluate(series):
    """Stats if the series qualifies as a case, else None."""
    if len(series) < 5:
        return None
    st = series_stats(series)
    ok = (st["peak_gain_pct"] >= MIN_GAIN_PCT and st["drawdown_pct"] >= MIN_DRAWDOWN_PCT
          and 0 < st["minutes_to_peak"] <= MAX_MIN_TO_PEAK
          and 0 < st["minutes_peak_to_dead"] <= MAX_MIN_PEAK_TO_DEAD)
    return st if ok else None


def score(st, volume):
    """Higher = better story: big pump, fast death, real money involved."""
    speed = 1 / math.sqrt(max(1.0, st["minutes_peak_to_dead"]))
    return math.log10(1 + st["peak_gain_pct"]) * speed * math.log10(10 + (volume or 0))


def launch_words(created_ms, now=None):
    now = now or datetime.now(TZ)
    dt = datetime.fromtimestamp(created_ms / 1000, TZ)
    delta = (now.date() - dt.date()).days
    day = {0: "heute", 1: "gestern", 2: "vorgestern"}.get(delta)
    return day, dt.strftime("%H:%M")


def say_symbol(sym):
    return sym if len(sym) <= 3 else sym.capitalize()

# -------------------------------------------------------------- pipeline --


def discover(c, now_ms, hours_back=36, min_age_h=2, limit=100, exclude=(), diag=None):
    body = c.get("/search", {
        "minCreatedAt": now_ms - hours_back * 3600_000, "maxCreatedAt": now_ms - min_age_h * 3600_000,
        "minVolume_24h": SEARCH_MIN_VOLUME_24H, "maxMarketCap": SEARCH_MAX_MARKET_CAP,
        "sortBy": "volume_24h", "sortOrder": "desc", "limit": limit})
    out, raw = [], rows(body, "data")
    if diag is not None:
        diag["search_rows"] = len(raw)
        diag["search_top_keys"] = sorted(body.keys()) if isinstance(body, dict) else "list"
        diag["search_row_keys"] = sorted(raw[0].keys()) if raw else []
        diag["skipped"] = []
    for r in raw:
        mint = r.get("mint") or (r.get("token") or {}).get("mint")
        sym = str(r.get("symbol") or (r.get("token") or {}).get("symbol") or "")
        if (not mint or mint in exclude or not BASE58.match(mint) or not sym.isascii()
                or not sym.isalnum() or len(sym) > 12
                or sym.upper() in BLOCKED_SYMBOLS
                or any(b in sym.upper() for b in BLOCKED_SYMBOLS if len(b) >= 4)):
            if diag is not None:
                diag["skipped"].append({"mint": mint, "symbol": sym, "reason": "symbol/mint/used"})
            continue
        out.append({"mint": mint, "symbol": sym.upper(), "createdAt": to_ms(r.get("createdAt")),
                    "deployer": r.get("deployer"), "volume": r.get("volume_24h") or r.get("volume") or 0})
    return out


def chart(c, mint, created_ms, hours=6, interval="1m"):
    """-> (series, first_candle_ms)"""
    t0 = created_ms // 1000 - 60
    body = c.get(f"/chart/{mint}", {"type": interval, "time_from": t0,
                                    "time_to": t0 + hours * 3600, "removeOutliers": "true"})
    return candles_to_series(body)


def traders(c, mint, max_pages=6):
    """All traders (wallets that bought) with PnL. Returns (rows, total_reported)."""
    out, cursor, total = [], None, None
    for _ in range(max_pages):
        params = {"limit": 500, "sort": "first_trade", "direction": "asc"}
        if cursor:
            params["cursor"] = cursor
        body = c.get(f"/v2/pnl/tokens/{mint}/traders", params)
        page = rows(body, "traders")
        out += page
        pag = body.get("pagination", {}) if isinstance(body, dict) else {}
        total = pag.get("total", total)
        cursor = pag.get("nextCursor") or pag.get("cursor") or pag.get("next")
        if not page or not cursor or (total and len(out) >= total):
            break
    return out, (total or len(out))


def _num(x, *path, default=0.0):
    for p in path:
        x = x.get(p, {}) if isinstance(x, dict) else {}
    return float(x) if isinstance(x, (int, float)) else default


def creator_crash(trs, creator, peak_ms):
    """Did the creator wallet sell everything, around the peak?"""
    row = next((t for t in trs if t.get("wallet") == creator
                or "developer" in ((t.get("identity") or {}).get("tags") or [])), None)
    if not row:
        return {}
    bal = _num(row, "position", "balance", default=-1)
    last = to_ms(((row.get("timing") or {}).get("lastTrade")))
    sold_all = bal == 0
    near_peak = bool(last and peak_ms and abs(last - peak_ms) <= 3 * 60_000)
    return {"by_creator": bool(sold_all and near_peak), "sold_all": sold_all}


def buyer_loss(trs, creator):
    loss = 0.0
    for t in trs:
        if t.get("wallet") == creator or "developer" in ((t.get("identity") or {}).get("tags") or []):
            continue
        total = _num(t, "pnl", "token", "total", default=0.0)
        if total < 0:
            loss += -total
    return loss


def prior_flag(c, creator, mint):
    """How many earlier coins of the same creator wallet fell > threshold from their high."""
    if not creator:
        return None
    body = c.get(f"/deployer/{creator}", {"limit": 50})
    others = [r for r in rows(body, "data") if (r.get("mint") or "") not in ("", mint)]
    bad = tot = 0
    for r in others[:MAX_PRIOR_CHECKS]:
        ath = c.get(f"/tokens/{r['mint']}/ath")
        hi = ath.get("highest_price") if isinstance(ath, dict) else None
        info = c.get(f"/tokens/{r['mint']}")
        pools = (info or {}).get("pools") or []
        cur = _num(pools[0], "price", "usd", default=-1) if pools else -1
        if not hi or cur < 0:
            continue
        tot += 1
        if cur <= hi * (1 - PRIOR_THRESHOLD_PCT / 100):
            bad += 1
    if tot >= 2 and bad >= 2:
        return {"kind": "prior", "bad": bad, "total": tot, "threshold_pct": PRIOR_THRESHOLD_PCT}
    return None


def _why_not(ser):
    if len(ser) < 5:
        return f"zu wenig Kerzen ({len(ser)})"
    st = series_stats(ser)
    r = []
    if st["peak_gain_pct"] < MIN_GAIN_PCT:
        r.append(f"Anstieg nur {st['peak_gain_pct']:.0f} %")
    if st["drawdown_pct"] < MIN_DRAWDOWN_PCT:
        r.append(f"Absturz nur {st['drawdown_pct']:.0f} %")
    if not 0 < st["minutes_to_peak"] <= MAX_MIN_TO_PEAK:
        r.append(f"Hoch nach {st['minutes_to_peak']:.0f} min")
    if not 0 < st["minutes_peak_to_dead"] <= MAX_MIN_PEAK_TO_DEAD:
        r.append(f"Absturz dauerte {st['minutes_peak_to_dead']:.0f} min")
    return ", ".join(r) or "?"


def build_case(c, now=None, max_candidates=25, exclude=(), log=print, diag=None):
    now = now or datetime.now(TZ)
    now_ms = int(now.timestamp() * 1000)
    diag = diag if diag is not None else {}
    cands = discover(c, now_ms, exclude=set(exclude), diag=diag)
    log(f"Kandidaten: {len(cands)} (Suchtreffer: {diag.get('search_rows')})")
    diag["candidates"] = []
    best = None
    for cand in cands[:max_candidates]:
        entry = {"symbol": cand["symbol"], "mint": cand["mint"], "createdAt": cand["createdAt"]}
        diag["candidates"].append(entry)
        if not cand["createdAt"]:
            entry["result"] = "kein createdAt"
            continue
        ser, _ = chart(c, cand["mint"], cand["createdAt"])
        entry["candles"] = len(ser)
        st = evaluate(ser)
        if not st:
            entry["result"] = _why_not(ser)
            log(f"  ✗ {cand['symbol']}: {entry['result']}")
            continue
        entry["result"] = "qualifiziert"
        sc = score(st, cand["volume"])
        log(f"  ✓ {cand['symbol']}: +{st['peak_gain_pct']:.0f} % / −{st['drawdown_pct']:.1f} % "
            f"in {st['minutes_peak_to_dead']:.1f} min  score {sc:.2f}")
        if not best or sc > best[0]:
            best = (sc, cand, st)
    if not best:
        return None
    _, cand, st = best
    mint = cand["mint"]

    info = c.get(f"/tokens/{mint}")
    creation = ((info.get("token") or {}).get("creation") or {}) if isinstance(info, dict) else {}
    creator = creation.get("creator") or cand.get("deployer")
    created_ms = to_ms(creation.get("created_time")) or cand["createdAt"]
    pools = info.get("pools") or []
    pool_id = (pools[0].get("poolId") or pools[0].get("address")) if pools else None

    # fine-grained series for the final video
    span = st["minutes_to_peak"] + st["minutes_peak_to_dead"]
    fine, t0 = chart(c, mint, created_ms, hours=max(1, math.ceil(span * 1.4 / 60) + 1),
                     interval=pick_interval(span * 1.4))
    ser = trim_series(fine) if evaluate(fine) else None
    if not ser or len(ser) < 20:
        coarse, t0 = chart(c, mint, created_ms)
        ser = trim_series(coarse) if evaluate(coarse) else []
    if len(ser) < 20:
        log("  Preisreihe zu kurz – Fall verworfen")
        return None
    st = series_stats(ser)

    trs, total = traders(c, mint)
    if total < MIN_BUYERS:
        log(f"  nur {total} Käufer – Fall verworfen")
        return None
    peak_ms = t0 + st["minutes_to_peak"] * 60000 if t0 else None
    crash = creator_crash(trs, creator, peak_ms)
    loss = buyer_loss(trs, creator)

    flags = []
    try:
        b = c.get(f"/tokens/{mint}/bundlers")
        nb = int(b.get("total") or 0) if isinstance(b, dict) else 0
        pct = b.get("initialPercentage") if isinstance(b, dict) else None
        if nb >= 3:
            f = {"kind": "bundle", "wallets": nb}
            if isinstance(pct, (int, float)) and pct >= 1:
                f["pct"] = int(round(pct))
            flags.append(f)
    except ApiError as e:
        log(f"  Bundler-Daten fehlen ({e}) – Signal wird weggelassen")
    try:
        pf = prior_flag(c, creator, mint)
        if pf:
            flags.append(pf)
    except (ApiError, BudgetExceeded) as e:
        log(f"  Ersteller-Historie fehlt ({e}) – Signal wird weggelassen")

    ath = c.get(f"/tokens/{mint}/ath")
    peak_mcap = ath.get("highest_market_cap") if isinstance(ath, dict) else None
    if not peak_mcap:
        log("  kein Marktwert-Hoch – Fall verworfen")
        return None

    day, hhmm = launch_words(created_ms, now)
    if not day:
        log("  Start liegt zu weit zurück – Fall verworfen")
        return None
    sources = [f"https://solscan.io/token/{mint}"]
    if creator:
        sources.append(f"https://solscan.io/account/{creator}")
    if pool_id:
        sources.append(f"https://dexscreener.com/solana/{pool_id}")
    covered = len(trs)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "demo": False,
        "token": {"symbol": cand["symbol"], "say": say_symbol(cand["symbol"]), "chain": "Solana"},
        "contract_address": mint,
        "creator_wallet": creator,
        "launch_day": day,
        "launch_time": hhmm,
        "peak_market_cap_usd": int(round(peak_mcap)),
        "minutes_to_peak": int(round(st["minutes_to_peak"])),
        "peak_gain_pct": int(round(st["peak_gain_pct"])),
        "minutes_peak_to_dead": max(1, int(round(st["minutes_peak_to_dead"]))),
        "drawdown_pct": round(st["drawdown_pct"], 1),
        "buyers": int(total),
        "crash": crash,
        "flags": flags[:3],
        "buyer_loss_usd": int(round(loss)),
        "loss_is_lower_bound": covered < total,
        "loss_method": (f"Summe der negativen Gewinne/Verluste (realisiert + unrealisiert) aller "
                        f"Käufer-Wallets ohne Ersteller-Wallet; {covered} von {total} Wallets "
                        f"erfasst; Quelle Solana Tracker PnL-API, Stand {stamp}"),
        "price_series": ser,
        "sources": sources,
        "fetched_at": stamp,
        "api_requests": c.used,
    }


def next_episode(state_path: Path, mint: str):
    st = {"episode": 0, "used_mints": []}
    if state_path.exists():
        st = json.loads(state_path.read_text(encoding="utf-8"))
    if mint in st["used_mints"]:
        return None, st
    st["episode"] += 1
    st["used_mints"] = (st["used_mints"] + [mint])[-500:]
    return st["episode"], st
