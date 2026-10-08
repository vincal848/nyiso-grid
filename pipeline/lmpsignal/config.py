"""LMP signal configuration: issue time, locations, cross-validation calendar, holdout guard."""
from __future__ import annotations

import os
from datetime import date

from nyiso.config import DATA, EXTERNAL_ZONES, ZONES

FEATURES_DB = DATA / "features.duckdb"
EXPERIMENTS_DB = DATA / "experiments.duckdb"
EXPERIMENTS_DIR = DATA / "experiments"

# Anchor horizon h0: forecasts for delivery day D issued at 05:00 ET on D-1 (DAM bid deadline).
ISSUE_HOUR_ET = 5
HORIZON = "h0"

INTERNAL_ZONES = list(ZONES.values())
LOCATIONS = INTERNAL_ZONES + EXTERNAL_ZONES

MARKETS = ("da", "rt")
# Price identity (verified): lbmp = energy + mlc - mcc. We forecast additive components:
#   energy, loss (= mlc), congestion (= -mcc), so total = energy + loss + congestion.
COMPONENTS = ("total", "energy", "loss", "congestion")

# Quantile grid stored for probabilistic forecasts
QUANTILES = (0.01, *[round(0.05 * i, 2) for i in range(1, 20)], 0.99)

OOS_SCHEMA = """CREATE TABLE IF NOT EXISTS load_fix_oos (ts_utc TIMESTAMPTZ, zone VARCHAR, delivery_date DATE,
                load_fix DOUBLE, r_hat DOUBLE, run_id VARCHAR)"""

# ---------------------------------------------------------------- time-block CV
BURN_IN_START = date(2021, 10, 1)     # training only, never scored
VALIDATION_START = date(2022, 10, 1)  # 36 monthly blocks
VALIDATION_END = date(2025, 10, 1)    # exclusive
HOLDOUT_START = date(2025, 10, 1)     # final test: touched once (milestone M7)
HOLDOUT_END = date(2026, 10, 1)       # exclusive
EMBARGO_DAYS = 7                      # gap between the end of training targets and a scored block


class HoldoutLocked(RuntimeError):
    pass


def holdout_unlocked() -> bool:
    return os.environ.get("LMP_UNLOCK_HOLDOUT") == "I_AM_RUNNING_M7"


def guard(delivery_date: date) -> None:
    """Raise if code tries to score or train on the holdout before it is explicitly unlocked."""
    if HOLDOUT_START <= delivery_date < HOLDOUT_END and not holdout_unlocked():     # later dates are live, not holdout
        raise HoldoutLocked(f"{delivery_date} is in the final holdout ({HOLDOUT_START}..{HOLDOUT_END}). "
                            "Set LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7 only for the single final evaluation.")
