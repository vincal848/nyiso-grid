"""TCC pricer: expected congestion payoff of a path over a contract period, from data before the auction.

Pure computation (DataFrames in, DataFrames out); the warehouse and TCC tables are read in `tcc/data.py`.

A TCC from POI (source) to POW (sink) pays, for every hour of its period, the DA congestion component at the sink minus
at the source, where congestion = -MCC (NYISO subtracts MCC from the LBMP). One TCC = 1 MW.
Hourly congestion frames: index = UTC hour start, columns = PTID; `grid` maps the same index to local (d, hr).

Forecasts (all use delivery days < `cutoff` only):
  market       the auction clearing price (no model)
  persistence  realized payoff of the same calendar dates one year earlier, scaled to the period's hours
  climatology  mean hourly payoff over the trailing 365 days x period hours
  struct_trailing  shift factors (ridge on the top-K DA constraint shadow prices, 365-day window, structural/congestion.py)
                   x each constraint's trailing-365-day mean shadow price x period hours
  struct_seasonal  same shift factors x each constraint's mean shadow price over the window's hours that fall in the
                   period's calendar months (all months for periods of a year or more)
  struct_blend     the mean of the two structural forecasts
Only the mean shadow price enters the expected payoff (it is linear in the shadow prices); the paths' risk is not priced.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from lmpsignal.structural.congestion import mu_cube, ridge_shift_factors, top_constraints
from nyiso.config import TZ

WINDOW_DAYS = 365
K = 60
RIDGE = 1.0
MIN_COVERAGE = 0.99          # share of a period's hours with prices at both ends for a realized payoff to count
NODE_COVERAGE = 0.90         # share of window hours a POI needs for its shift factors (as in the M3 node factors)
CUTOFF_LAG_DAYS = 7          # information cutoff = posted date minus this: bids close days before results are posted
STRUCT = ("struct_trailing", "struct_seasonal", "struct_blend")


@dataclass(frozen=True)
class Period:
    posted: pd.Timestamp     # results public
    start: pd.Timestamp      # first local day
    end: pd.Timestamp        # last local day (inclusive)

    @property
    def cutoff(self) -> pd.Timestamp:
        return self.posted.normalize() - pd.Timedelta(days=CUTOFF_LAG_DAYS)

    @property
    def months(self) -> set[int]:
        return set(pd.date_range(self.start, self.end, freq="D").month)

    @property
    def n_hours(self) -> int:
        """Exact hours in the period (DST days have 23 or 25)."""
        return len(pd.date_range(self.start, self.end + pd.Timedelta(days=1), freq="h", tz=TZ, inclusive="left"))


def hour_grid(index: pd.DatetimeIndex) -> pd.DataFrame:
    """UTC hour starts -> local day and local hour (the fall-back hour appears twice with the same local pair)."""
    local = index.tz_convert(TZ)
    return pd.DataFrame({"d": local.normalize().tz_localize(None), "hr": local.hour}, index=index)


def _in(grid: pd.DataFrame, start, end) -> np.ndarray:
    return ((grid["d"] >= start) & (grid["d"] <= end)).to_numpy()


def realized(cong: pd.DataFrame, grid: pd.DataFrame, p: Period, poi: np.ndarray, pow_: np.ndarray) -> np.ndarray:
    """Payoff per path over the period; NaN when fewer than MIN_COVERAGE of the period's hours have both prices."""
    m = _in(grid, p.start, p.end)
    diff = cong.loc[m, pow_].to_numpy() - cong.loc[m, poi].to_numpy()
    ok = np.isfinite(diff)
    return np.where(ok.sum(axis=0) >= MIN_COVERAGE * p.n_hours, np.nansum(diff, axis=0), np.nan)


def climatology(cong, grid, p: Period, poi, pow_) -> np.ndarray:
    m = _in(grid, p.cutoff - pd.Timedelta(days=WINDOW_DAYS), p.cutoff - pd.Timedelta(days=1))
    diff = cong.loc[m, pow_].to_numpy() - cong.loc[m, poi].to_numpy()
    n = np.isfinite(diff).sum(axis=0)
    return np.where(n >= MIN_COVERAGE * m.sum(), np.nanmean(diff, axis=0) * p.n_hours, np.nan)


def persistence(cong, grid, p: Period, poi, pow_) -> np.ndarray:
    """Realized payoff of the same dates a year earlier (per hour), times this period's hours. NaN if that period is not
    finished before the cutoff or lacks prices."""
    off = pd.DateOffset(years=1)
    prev = Period(p.posted, p.start - off, p.end - off)
    if prev.end >= p.cutoff:
        return np.full(len(poi), np.nan)
    return realized(cong, grid, prev, poi, pow_) / prev.n_hours * p.n_hours


def fit_shift_factors(sp: pd.DataFrame, cong: pd.DataFrame, grid: pd.DataFrame, p: Period, ptids: np.ndarray
                      ) -> tuple[list[str], pd.DataFrame, pd.DataFrame]:
    """Top-K DA constraints of the 365 days before the cutoff, and their shift factors (K x POIs) for the POIs with
    enough price history in the window. Also returns the window's (d, hr)-aligned shadow prices (rows = hours)."""
    days = pd.date_range(p.cutoff - pd.Timedelta(days=WINDOW_DAYS), p.cutoff - pd.Timedelta(days=1), freq="D")
    keys = top_constraints(sp, "da", days, K)
    X = mu_cube(sp, "da", keys, days).reshape(-1, len(keys))
    m = _in(grid, days[0], days[-1])
    y = cong.loc[m, ptids].groupby([grid.loc[m, "d"].to_numpy(), grid.loc[m, "hr"].to_numpy()]).mean()
    y = y.reindex(pd.MultiIndex.from_product([days, range(24)]))
    keep = y.columns[y.notna().mean() >= NODE_COVERAGE]
    Y = y[keep].ffill().bfill().to_numpy()
    A = pd.DataFrame(ridge_shift_factors(X, Y, RIDGE), index=keys, columns=keep)
    hours = pd.DataFrame(X, index=y.index, columns=keys)
    return keys, A, hours


def structural(sp, cong, grid, p: Period, poi: np.ndarray, pow_: np.ndarray) -> pd.DataFrame:
    """struct_trailing / struct_seasonal / struct_blend expected payoff per path (NaN if an end has no shift factors)."""
    _, A, hours = fit_shift_factors(sp, cong, grid, p, np.unique(np.concatenate([poi, pow_])))
    month = hours.index.get_level_values(0).month
    trailing = hours.mean().to_numpy() * p.n_hours
    season = hours[np.isin(month, list(p.months))]
    seasonal = (season if len(season) else hours).mean().to_numpy() * p.n_hours
    ok = np.isin(poi, A.columns) & np.isin(pow_, A.columns)
    diff = np.full((len(poi), len(A)), np.nan)
    diff[ok] = (A[pow_[ok]].to_numpy() - A[poi[ok]].to_numpy()).T
    out = pd.DataFrame({"struct_trailing": diff @ trailing, "struct_seasonal": diff @ seasonal})
    out["struct_blend"] = out.mean(axis=1, skipna=False)
    return out
