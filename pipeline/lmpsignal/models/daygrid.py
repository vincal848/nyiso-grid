"""Daily 24-hour grid of panel variables, for per-hour models such as LEAR.

Rows = (zone, delivery_date), columns = local clock hours 0..23. DST handling follows the electricity
price forecasting convention (e.g. epftoolbox): the repeated fall-back hour is averaged and the
missing spring-forward hour is interpolated, giving every day 24 slots. Predictions are mapped back to
the panel's rows by local hour.

Lags are taken by calendar date (not by row), so a missing day never shifts a lag onto the wrong day.
All inputs come from panel columns that are already as-of-verified; a lag of a *target* column is only
used at offsets that were published before the 05:00 D-1 issue (DA: >= 1 day, RT: >= 2 days).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HOURS = list(range(24))


def grid(p: pd.DataFrame, col: str) -> pd.DataFrame:
    g = p.groupby(["zone", "delivery_date", "hour_local"])[col].mean().unstack("hour_local")
    g = g.reindex(columns=HOURS)
    return g.interpolate(axis=1, limit_direction="both")


def lagged(g: pd.DataFrame, days: int, idx: pd.MultiIndex) -> pd.DataFrame:
    """Value of the grid `days` calendar days before each (zone, date) in idx."""
    g = g.reindex(full_index_from(g, idx))
    shifted = g.groupby(level="zone").shift(days)
    return shifted.reindex(idx)


def full_index_from(g: pd.DataFrame, idx: pd.MultiIndex) -> pd.MultiIndex:
    dates = pd.date_range(min(g.index.get_level_values(1).min(), idx.get_level_values(1).min()),
                          max(g.index.get_level_values(1).max(), idx.get_level_values(1).max()), freq="D")
    zones = sorted(set(g.index.get_level_values(0)) | set(idx.get_level_values(0)))
    return pd.MultiIndex.from_product([zones, dates], names=["zone", "delivery_date"])


def to_rows(pred: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    """Map a (zone, date) x 24 prediction grid back onto panel rows (by zone, date, local hour)."""
    long = pred.stack().rename("v").reset_index()
    long.columns = ["zone", "delivery_date", "hour_local", "v"]
    m = rows[["zone", "delivery_date", "hour_local"]].merge(long, on=["zone", "delivery_date", "hour_local"], how="left")
    return m["v"].to_numpy()
