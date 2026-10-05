"""Forecast scoring: point and probabilistic metrics, per-group breakdowns, Diebold-Mariano test.

Primary metrics (decided 2026-09-28): CRPS (whole predictive distribution) and RMSE (conditional mean).
MAE is secondary: it rewards the median, and for zero-inflated targets such as congestion an always-zero
forecast can "win" on MAE while being useless for trading, where P&L is linear in the price.

Conventions follow the electricity price forecasting literature (Lago et al. 2021): rMAE is MAE
relative to a naive benchmark on the same rows; sMAPE instead of MAPE (prices near zero or negative);
DM on daily-averaged loss differentials with a Newey-West (HAC) variance.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from lmpsignal.config import QUANTILES


def qcol(q: float) -> str:
    return f"q{round(q * 100):02d}"


QCOLS = [qcol(q) for q in QUANTILES]


# ------------------------------------------------------------------------------------ point metrics

def mae(y, f) -> float:
    return float(np.mean(np.abs(y - f)))


def rmse(y, f) -> float:
    return float(np.sqrt(np.mean((y - f) ** 2)))


def smape(y, f) -> float:
    denom = (np.abs(y) + np.abs(f)) / 2
    ok = denom > 1e-9
    return float(np.mean(np.abs(y - f)[ok] / denom[ok]))


def normal_mae(y, f, pct: float = 95) -> float:
    """MAE over the hours whose |actual| is below the pct percentile (complement of tail_mae)."""
    thr = np.percentile(np.abs(y), pct)
    m = np.abs(y) < thr
    return float(np.mean(np.abs(y - f)[m]))


def tail_mae(y, f, pct: float = 95) -> float:
    """MAE over the hours whose |actual| is in the top (100 - pct)% — spike performance."""
    thr = np.percentile(np.abs(y), pct)
    m = np.abs(y) >= thr
    return float(np.mean(np.abs(y - f)[m]))


# ------------------------------------------------------------------------------------ probabilistic

def pinball(y: np.ndarray, qpred: np.ndarray, qs=QUANTILES) -> np.ndarray:
    """Mean pinball loss per quantile. qpred: (n, len(qs))."""
    qs = np.asarray(qs)
    diff = y[:, None] - qpred
    return np.mean(np.maximum(qs * diff, (qs - 1) * diff), axis=0)


def crps(y: np.ndarray, qpred: np.ndarray, qs=QUANTILES) -> float:
    """CRPS = 2 * integral over tau in (0,1) of the pinball loss, by the midpoint rule on the stored
    grid: each level gets the width of its cell (cell edges at midpoints between levels, 0 and 1)."""
    qs = np.asarray(qs)
    edges = np.concatenate([[0.0], (qs[1:] + qs[:-1]) / 2, [1.0]])
    return float(2 * np.sum(pinball(y, qpred, qs) * np.diff(edges)))


def crps_rows(y: np.ndarray, qpred: np.ndarray, qs=QUANTILES) -> np.ndarray:
    """Per-row CRPS (same midpoint rule as `crps`); NaN where a row has no quantiles."""
    qs = np.asarray(qs)
    w = np.diff(np.concatenate([[0.0], (qs[1:] + qs[:-1]) / 2, [1.0]]))
    diff = y[:, None] - qpred
    pin = np.maximum(qs * diff, (qs - 1) * diff)
    return 2 * (pin * w).sum(axis=1) + np.where(np.isnan(qpred).any(axis=1), np.nan, 0.0)


def coverage(y, lo, hi) -> float:
    return float(np.mean((y >= lo) & (y <= hi)))


# ------------------------------------------------------------------------------------ scoring tables

def score(df: pd.DataFrame, naive_mean: pd.Series | None = None) -> dict[str, float]:
    """df has columns y, mean and (optionally) the QCOLS. naive_mean aligned to df for rMAE."""
    y, f = df["y"].to_numpy(float), df["mean"].to_numpy(float)
    out = {"n": len(df), "mae": mae(y, f), "rmse": rmse(y, f), "smape": smape(y, f), "tail_mae": tail_mae(y, f),
           "normal_mae": normal_mae(y, f)}
    if naive_mean is not None:
        denom = mae(y, naive_mean.to_numpy(float))
        out["rmae"] = out["mae"] / denom if denom > 0 else float("nan")   # e.g. a zone with zero congestion all month
    if all(c in df for c in QCOLS):
        has_q = df[QCOLS].notna().all(axis=1).to_numpy()
        if has_q.any():
            dq = df[has_q]
            yq, Q = dq["y"].to_numpy(float), dq[QCOLS].to_numpy(float)
            out["n_prob"] = int(has_q.sum())
            out["crps"] = crps(yq, Q)
            out["pinball_mean"] = float(np.mean(pinball(yq, Q)))
            out["cov50"] = coverage(yq, dq["q25"], dq["q75"])
            out["cov90"] = coverage(yq, dq["q05"], dq["q95"])
            out["cov98"] = coverage(yq, dq["q01"], dq["q99"])
    return out


def score_table(joined: pd.DataFrame, by: list[str], naive_col: str | None = None) -> pd.DataFrame:
    rows = []
    for key, g in joined.groupby(by, dropna=False):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), **score(g, g[naive_col] if naive_col else None)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------ significance

def newey_west_var(d: np.ndarray, lag: int | None = None) -> float:
    n = len(d)
    lag = int(math.floor(n ** (1 / 3))) if lag is None else lag
    dc = d - d.mean()
    v = np.dot(dc, dc) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        v += 2 * w * np.dot(dc[k:], dc[:-k]) / n
    return v


def diebold_mariano(loss_a: pd.Series, loss_b: pd.Series, days: pd.Series) -> dict[str, float]:
    """DM test on daily mean loss differential d = loss_a - loss_b (HAC variance).

    Returns the statistic and the one-sided p-value for H1: model A is more accurate (d < 0).
    """
    d = (loss_a - loss_b).groupby(days).mean().to_numpy(float)
    n = len(d)
    var = newey_west_var(d)
    stat = d.mean() / math.sqrt(var / n) if var > 0 else float("nan")
    p = 0.5 * (1 + math.erf(stat / math.sqrt(2))) if stat == stat else float("nan")
    return {"dm_stat": stat, "p_a_better": p, "n_days": n, "mean_diff": float(d.mean())}


# ------------------------------------------------------------------------------------ coverage tests

def _chi2_1_sf(x: float) -> float:
    return float(math.erfc(math.sqrt(max(x, 0.0) / 2)))


def kupiec_pof(violations: np.ndarray, p: float) -> dict:
    """Kupiec (1995) proportion-of-failures test: H0 the miss rate equals p. Returns miss rate and p-value.
    Note: pooled hourly/zonal misses are dependent, so the p-value is optimistic."""
    v = np.asarray(violations, bool)
    n, x = len(v), int(v.sum())
    if n == 0:
        return {"miss_rate": float("nan"), "p_value": float("nan")}
    phat = x / n
    ll0 = (n - x) * math.log(1 - p) + x * math.log(p)
    ll1 = ((n - x) * math.log(1 - phat) if phat < 1 else 0.0) + (x * math.log(phat) if phat > 0 else 0.0)
    return {"miss_rate": phat, "p_value": _chi2_1_sf(-2 * (ll0 - ll1))}


def christoffersen_ind(violations: np.ndarray) -> float:
    """Christoffersen (1998) independence test p-value on a time-ordered miss sequence (H0: misses do not cluster)."""
    v = np.asarray(violations, int)
    if len(v) < 3:
        return float("nan")
    a, b = v[:-1], v[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    def ll(k0, k1):
        n_ = k0 + k1
        if n_ == 0:
            return 0.0
        q = k1 / n_
        return (k0 * math.log(1 - q) if q < 1 else 0.0) + (k1 * math.log(q) if q > 0 else 0.0)
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    l0 = (n00 + n10) * (math.log(1 - pi) if pi < 1 else 0) + (n01 + n11) * (math.log(pi) if pi > 0 else 0)
    l1 = ll(n00, n01) + ll(n10, n11)
    return _chi2_1_sf(-2 * (l0 - l1))


def coverage_tests(df: pd.DataFrame) -> dict:
    """Kupiec on pooled misses for the 90% and 98% intervals, and the median Christoffersen p over
    (zone, local hour) day-sequences for the 90% interval."""
    d = df[df[QCOLS].notna().all(axis=1)]
    out = {}
    for lvl, lo, hi in ((90, "q05", "q95"), (98, "q01", "q99")):
        miss = ((d["y"] < d[lo]) | (d["y"] > d[hi])).to_numpy()
        k = kupiec_pof(miss, 1 - lvl / 100)
        out[f"miss{lvl}"], out[f"kupiec_p{lvl}"] = k["miss_rate"], k["p_value"]
    d = d.sort_values("ts_utc").assign(_m=((d["y"] < d["q05"]) | (d["y"] > d["q95"])).astype(int))
    ps = [christoffersen_ind(g["_m"].to_numpy()) for _, g in d.groupby(["zone", "hour_local"])]
    out["christoffersen_p90_median"] = float(np.nanmedian(ps)) if ps else float("nan")
    return out
