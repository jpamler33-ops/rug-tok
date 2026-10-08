"""Run: python3 tests/test_data.py  — guards that real videos need verifiable data."""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rugtok.data import DataError, series_stats, tiktok_description, validate  # noqa: E402

DEMO = json.loads((Path(__file__).parent.parent / "content" / "demo_rug.json").read_text())


def real_case():
    d = copy.deepcopy(DEMO)
    d["demo"] = False
    d["contract_address"] = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
    d["sources"] = ["https://solscan.io/token/7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"]
    d["loss_method"] = "Summe Kaufbeträge minus Verkaufserlöse minus Restwert aller Käufer-Wallets"
    ser = [[m * 0.5, 1 + (42.18 * (m / 22) ** 2)] for m in range(23)]   # peak at minute 11
    ser += [[11.5, 20.0], [12.5, 8.0], [14.0, 0.1265]]                   # crash, dead (−90 %) at 14
    d["price_series"] = ser
    st = series_stats(ser)
    d.update(peak_gain_pct=round(st["peak_gain_pct"]), minutes_to_peak=round(st["minutes_to_peak"]),
             drawdown_pct=round(st["drawdown_pct"], 1),
             minutes_peak_to_dead=round(st["minutes_peak_to_dead"]))
    assert d["minutes_to_peak"] == 11 and d["minutes_peak_to_dead"] == 3
    return d


def expect_error(d, needle):
    try:
        validate(d)
    except DataError as e:
        assert needle in str(e), f"expected '{needle}' in: {e}"
        return
    raise AssertionError(f"expected DataError containing '{needle}'")


def main():
    assert validate(DEMO), "demo must warn"
    assert validate(real_case()) == []                       # complete real data passes

    d = real_case(); del d["contract_address"]
    expect_error(d, "contract_address")
    d = real_case(); d["contract_address"] = "0xdeadbeef"
    expect_error(d, "keine gültige Solana-Adresse")
    d = real_case(); d["sources"] = ["http://unsicher.example"]
    expect_error(d, "https")
    d = real_case(); d["peak_gain_pct"] = 9999                # numbers that don't match chart
    expect_error(d, "peak_gain_pct")
    d = real_case(); d["price_series"] = d["price_series"][:5]
    expect_error(d, ">= 20 Punkte")
    d = real_case(); d["drawdown_pct"] = 0
    expect_error(d, "drawdown_pct")
    d = real_case(); del d["buyers"]
    expect_error(d, "fehlt: buyers")
    d = real_case(); d["flags"] = [{"kind": "prior", "bad": 3, "total": 2}]
    expect_error(d, "bad <= total")
    d = real_case(); d["flags"] = [{"kind": "rumor"}]
    expect_error(d, "unbekannter flag")
    d = real_case(); d["crash"] = {"single_tx": True, "sold_all": False}
    expect_error(d, "single_tx")
    d = real_case(); d["token"]["symbol"] = "🚀MOON"
    expect_error(d, "token.symbol")
    txt = tiktok_description(real_case())
    assert "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU" in txt and "Keine Finanzberatung" in txt
    print("OK – alle Datenprüfungen bestanden")


if __name__ == "__main__":
    main()
