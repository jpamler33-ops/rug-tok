#!/usr/bin/env python3
"""Find the day's case and write a validated data file for build.py.

  SOLANATRACKER_API_KEY=... python3 fetch_case.py
  -> content/2026-10-09_GLIMMR.json   (+ raw API responses in data/raw/<run>/)

Exit codes: 0 = case written, 3 = no qualifying case today, 1 = error.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from rugtok.config import ROOT
from rugtok.data import DataError, validate
from rugtok.fetch import TZ, ApiError, BudgetExceeded, Client, build_case, next_episode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=int(os.environ.get("RUGTOK_BUDGET", 110)),
                    help="max API requests for this run")
    ap.add_argument("--candidates", type=int, default=25)
    ap.add_argument("--out-dir", default=str(ROOT / "content"))
    a = ap.parse_args()

    run = datetime.now(TZ).strftime("%Y-%m-%d_%H%M%S")
    state_path = Path(a.out_dir) / "state.json"
    used = json.loads(state_path.read_text())["used_mints"] if state_path.exists() else []
    client = Client(os.environ.get("SOLANATRACKER_API_KEY"), budget=a.budget,
                    archive_dir=ROOT / "data" / "raw" / run)
    diag = {"run": run}
    runs_dir = ROOT / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    def save_diag(status):
        diag.update(status=status, api_requests=client.used)
        (runs_dir / f"{run}.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1),
                                               encoding="utf-8")

    try:
        case = build_case(client, max_candidates=a.candidates, exclude=used, diag=diag)
    except (ApiError, BudgetExceeded) as e:
        diag["error"] = str(e)
        save_diag("error")
        print(f"FEHLER: {e} (Requests: {client.used})", file=sys.stderr)
        return 1
    print(f"API-Requests: {client.used}")
    if not case:
        save_diag("no_case")
        print("Heute kein Fall, der alle Kriterien erfüllt. Kein Video.")
        return 3

    episode, state = next_episode(state_path, case["contract_address"])
    if episode is None:
        print("Fall wurde schon verwendet.")
        return 3
    case["episode"] = episode
    case["series"] = os.environ.get("RUGTOK_SERIES", "RUG-CHECK")
    case["cta"] = {"telegram": os.environ.get("RUGTOK_TELEGRAM_CTA", "0") == "1"}
    case["raw_archive"] = f"data/raw/{run}"
    try:
        validate(case)
    except DataError as e:
        diag["error"] = str(e)
        save_diag("invalid")
        print(f"FEHLER: Daten aus der API sind inkonsistent: {e}", file=sys.stderr)
        return 1

    save_diag("case")
    out = Path(a.out_dir) / f"{run[:10]}_{case['token']['symbol']}.json"
    out.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(f"Fall #{episode}: ${case['token']['symbol']} +{case['peak_gain_pct']} % → "
          f"−{case['drawdown_pct']} %  -> {out}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"case={out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
