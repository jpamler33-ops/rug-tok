"""Offline tests for the data pipeline. A fake HTTP layer serves API-shaped fixtures
(shapes taken from the Solana Tracker docs). Run: python3 tests/test_fetch.py"""
import io
import json
import sys
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rugtok import fetch  # noqa: E402
from rugtok.data import series_stats, validate  # noqa: E402
from rugtok.script import rug_des_tages  # noqa: E402

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=fetch.TZ)
NOW_S = int(NOW.timestamp())
RUG = "RuGmint1111111111111111111111111111111111111"[:44]
OK = "HeaLthy22222222222222222222222222222222222222"[:44]
EMO = "EmoJi333333333333333333333333333333333333333"[:44]
CREATOR = "CreaTor44444444444444444444444444444444444444"[:44]
PRIORS = [f"PrioR{i}555555555555555555555555555555555555555"[:44] for i in range(3)]
CREATED_S = NOW_S - 20 * 3600            # yesterday 12:00 Berlin


def price_rug(t_min):
    """Pump to x50 at minute 12, creator dump, dead by minute 15."""
    if t_min <= 12:
        return 1e-6 * (1 + 49 * (t_min / 12) ** 2)
    if t_min <= 15:
        return 5e-5 * (0.25 ** (t_min - 12))
    return 5e-5 * 0.25 ** 3


def price_ok(t_min):
    return 1e-6 * (1 + t_min / 30)


def candles(fn, frm, to, step):
    out, t = [], CREATED_S
    while t <= min(to, CREATED_S + 6 * 3600):
        if t >= frm:
            m = (t - CREATED_S) / 60
            p0, p1 = fn(m), fn(m + step / 60)
            out.append({"time": t, "open": p0, "close": p1, "high": max(p0, p1),
                        "low": min(p0, p1), "volume": 100})
        t += step
    return out


STEP = {"5s": 5, "15s": 15, "1m": 60, "3m": 180, "5m": 300, "15m": 900}


class FakeAPI:
    def __init__(self, fail_first=0):
        self.calls, self.fail_first = [], fail_first

    def __call__(self, req, timeout=None):
        u = urllib.parse.urlparse(req.full_url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        self.calls.append(u.path)
        assert req.headers.get("X-api-key") == "test-key"
        if self.fail_first:
            self.fail_first -= 1
            raise urllib.error.HTTPError(req.full_url, 429, "rate", {}, None)
        body = self.route(u.path, q)
        return io.BytesIO(json.dumps(body).encode())

    def route(self, path, q):
        p = path.split("/")
        if path == "/search":
            return {"status": "success", "data": [
                {"mint": OK, "symbol": "CALM", "createdAt": CREATED_S * 1000, "deployer": "x",
                 "volume_24h": 900000},
                {"mint": EMO, "symbol": "🚀X", "createdAt": CREATED_S * 1000, "volume_24h": 5e6},
                {"mint": RUG, "symbol": "glimmr", "createdAt": CREATED_S * 1000,
                 "deployer": CREATOR, "volume_24h": 400000}]}
        if p[1] == "chart":
            fn = price_rug if p[2] == RUG else price_ok
            return {"oclhv": candles(fn, int(q["time_from"]), int(q["time_to"]), STEP[q["type"]])}
        if path.endswith("/traders"):
            if q.get("cursor") == "p2":
                rows = [{"wallet": f"w{i}", "pnl": {"token": {"total": -100.0}},
                         "position": {"balance": 0}} for i in range(150)]
                return {"traders": rows, "pagination": {"total": 350}}
            rows = [{"wallet": CREATOR, "identity": {"tags": ["developer"]},
                     "pnl": {"token": {"total": 9000.0}}, "position": {"balance": 0},
                     "timing": {"lastTrade": (CREATED_S + 12 * 60 + 20) * 1000}}]
            rows += [{"wallet": f"v{i}", "pnl": {"token": {"total": -50.0 if i % 2 else 20.0}},
                      "position": {"balance": 1}} for i in range(199)]
            return {"traders": rows, "pagination": {"total": 350, "nextCursor": "p2"}}
        if path.endswith("/bundlers"):
            return {"total": 14, "initialPercentage": 27.4, "wallets": []}
        if path.endswith("/ath"):
            if p[2] == RUG:
                return {"highest_price": 5e-5, "highest_market_cap": 51234.7, "timestamp": 0}
            return {"highest_price": 1.0, "highest_market_cap": 1e6}
        if p[1] == "deployer":
            return {"status": "success", "total": 4, "data": [{"mint": RUG}] +
                    [{"mint": m} for m in PRIORS]}
        if p[1] == "tokens":
            if p[2] == RUG:
                return {"token": {"symbol": "GLIMMR", "creation": {
                    "creator": CREATOR, "created_time": CREATED_S}},
                    "pools": [{"poolId": "PooL1", "price": {"usd": 1.5e-7}}]}
            cur = 0.02 if p[2] != PRIORS[2] else 0.5   # two of three fell > 90 %
            return {"pools": [{"price": {"usd": cur}}]}
        raise AssertionError(f"unexpected path {path}")


def client(api, budget=200):
    c = fetch.Client("test-key", budget=budget, min_interval=0, opener=api)
    return c


def test_full_case():
    api = FakeAPI()
    case = fetch.build_case(client(api), now=NOW, log=lambda *a: None)
    assert case, "rug should qualify"
    assert case["contract_address"] == RUG and case["token"]["symbol"] == "GLIMMR"
    assert case["token"]["say"] == "Glimmr"
    assert case["launch_day"] == "gestern" and case["launch_time"] == "12:00"
    st = series_stats(case["price_series"])
    assert abs(st["peak_gain_pct"] - case["peak_gain_pct"]) < 1
    assert case["minutes_to_peak"] == 12, case["minutes_to_peak"]
    assert 1 <= case["minutes_peak_to_dead"] <= 3
    assert case["buyers"] == 350
    assert case["crash"] == {"by_creator": True, "sold_all": True}
    # loss: 100 losers * 50 (page 1, odd i) + 150 * 100 (page 2); creator profit excluded
    assert case["buyer_loss_usd"] == 99 * 50 + 150 * 100, case["buyer_loss_usd"]
    assert case["loss_is_lower_bound"] is False
    kinds = {f["kind"]: f for f in case["flags"]}
    assert kinds["bundle"] == {"kind": "bundle", "wallets": 14, "pct": 27}
    assert kinds["prior"]["bad"] == 2 and kinds["prior"]["total"] == 3
    assert case["peak_market_cap_usd"] == 51235
    assert "https://dexscreener.com/solana/PooL1" in case["sources"]
    assert len(case["price_series"]) >= 20
    validate(case)              # the produced file must pass the strict real-data checks
    rug_des_tages(case)         # and render into a script
    assert case["api_requests"] < 60, case["api_requests"]


def test_retry_on_429():
    api = FakeAPI(fail_first=1)
    c = client(api)
    fetch.time.sleep = lambda s: None        # no real waiting in tests
    body = c.get("/search", {})
    assert body["status"] == "success" and c.used == 2


def test_budget():
    c = client(FakeAPI(), budget=3)
    try:
        fetch.build_case(c, now=NOW, log=lambda *a: None)
    except fetch.BudgetExceeded:
        return
    raise AssertionError("budget must stop the run")


def test_excluded_and_no_case():
    case = fetch.build_case(client(FakeAPI()), now=NOW, exclude={RUG}, log=lambda *a: None)
    assert case is None, "healthy token must not qualify; used mint must be skipped"


def test_units():
    assert fetch.to_ms(1737122459) == 1737122459000
    assert fetch.to_ms(1737196771000) == 1737196771000
    ser, t0 = fetch.candles_to_series([{"time": 100, "open": 1, "close": 2},
                                       {"time": 160, "open": 2, "close": 3}])
    assert t0 == 100000 and ser[0] == [0.0, 1.0] and len(ser) == 3


def test_partial_traders_marks_lower_bound():
    class Short(FakeAPI):
        def route(self, path, q):
            b = super().route(path, q)
            if path.endswith("/traders"):
                b["pagination"].pop("nextCursor", None)   # API gives only one page
            return b
    case = fetch.build_case(client(Short()), now=NOW, log=lambda *a: None)
    assert case["loss_is_lower_bound"] is True
    assert "200 von 350" in case["loss_method"]
    assert "mindestens" in " ".join(w.show for sc in rug_des_tages(case)
                                     for s in sc.sentences for w in s.words)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("OK – Fetcher-Tests bestanden")
