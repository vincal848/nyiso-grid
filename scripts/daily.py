"""Daily signal job: refresh data, rebuild the panel and issue tomorrow's forecast.

Runs the project CLIs in order (each a separate process, so warehouse ingestion and the forecasting pipeline stay
in their own layers):
  1. nyiso backfill   current + previous month (complete months are skipped; incomplete ones re-fetched)
  2. nyiso external   gas, weather observations/forecasts, HRRR, P-14B outage-schedule snapshot
  3. nyiso build      DuckDB views (fails if `nyiso serve` holds the database: stop it or schedule around it)
  4. lmp panel        with feature rows through tomorrow
  5. lmp forecast     frozen signal -> experiments.duckdb live_forecasts
  6. lmp nodes        node-level forecasts for tomorrow -> live_node_forecasts

Schedule: before the 05:00 ET DAM bid deadline (e.g. 04:30 ET). The panel's as-of rules mean a later run gives the
same features, so a late run is still a valid (if unusable for bidding) forecast.
Log: data/logs/daily_YYYY-MM-DD.log.

Usage:  uv run python scripts/daily.py [--date YYYY-MM-DD] [--skip-data]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "data" / "logs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Delivery day (default: tomorrow, America/New_York)")
    ap.add_argument("--skip-data", action="store_true", help="Skip steps 1-3 (data already refreshed)")
    a = ap.parse_args()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    d = date.fromisoformat(a.date) if a.date else today + timedelta(days=1)
    prev = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    steps = [
        ["nyiso", "backfill", "--start", f"{prev:%Y-%m}"],
        ["nyiso", "external", "--start", f"{today:%Y-%m}"],
        ["nyiso", "build"],
        ["lmp", "panel", "--through", str(d)],
        ["lmp", "forecast", "--date", str(d)],
        ["lmp", "nodes", "--date", str(d)],
    ]
    if a.skip_data:
        steps = steps[3:]
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"daily_{today}.log"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} daily job for delivery day {d} ===\n")
        for cmd in steps:
            t = time.time()
            fh.write(f"$ uv run {' '.join(cmd)}\n")
            fh.flush()
            uv = os.environ.get("UV", "uv")         # `uv run` exports its own path; scheduled tasks may lack PATH
            r = subprocess.run([uv, "run", *cmd], cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
            fh.write(f"-> exit {r.returncode} in {time.time() - t:.0f}s\n")
            fh.flush()
            if r.returncode != 0:
                print(f"daily job failed at: {' '.join(cmd)} (see {log})", file=sys.stderr)
                return r.returncode
    print(f"daily job done for {d} (log: {log})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
