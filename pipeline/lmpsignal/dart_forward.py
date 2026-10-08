"""Forward-test statistics for the DART pricer: pure computation on daily net P&L series (no I/O).

The 2025-10..2026-09 holdout is spent, so the only clean test of a DART claim is the live window (docs/ROADMAP.md,
"DART pricer declaration"). Two things are needed before it starts and once it ends:
  * `power_curve`: how many settled days the test needs, from the validation daily-P&L distribution (heavy tails and
    day-to-day dependence kept, by resampling blocks of the observed days);
  * `bootstrap_p`: the one-sided test of "mean daily net P&L > 0" on the forward days, same statistic and resampler.
Statistic: studentised mean t = mean / (std / sqrt(n)). Null: observed days demeaned, resampled in stationary blocks
(mean length `block`), so serial dependence enters the critical value. Power = P(t > null 95th percentile) when days
are drawn from the observed (not demeaned) series, i.e. the validation estimate taken as the truth, which is
optimistic: validation is where the rule was chosen.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BLOCK = 5            # mean block length (days); v2's validation daily P&L has lag-1 autocorrelation 0.28


def _stationary_idx(n_obs: int, n: int, size: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """(size, n) indices into a series of n_obs days: stationary bootstrap, a new block starts with prob 1/block."""
    new = rng.random((size, n)) < 1.0 / block
    new[:, 0] = True
    pos = np.arange(n)
    last = np.maximum.accumulate(np.where(new, pos, 0), axis=1)
    start = np.take_along_axis(np.where(new, rng.integers(0, n_obs, (size, n)), 0), last, axis=1)
    return (start + pos - last) % n_obs


def _t(x: np.ndarray) -> np.ndarray:
    """Studentised mean along the last axis (0 where a sample has no variance)."""
    sd = x.std(axis=-1, ddof=1)
    return np.where(sd > 0, x.mean(axis=-1) / np.where(sd > 0, sd, 1.0) * np.sqrt(x.shape[-1]), 0.0)


def bootstrap_p(daily: np.ndarray, n_boot: int = 10_000, block: int = BLOCK, seed: int = 0) -> float:
    """One-sided p-value of mean(daily) > 0: share of null resamples (demeaned, stationary blocks) with t* >= t."""
    x = np.asarray(daily, float)
    rng = np.random.default_rng(seed)
    null = (x - x.mean())[_stationary_idx(len(x), len(x), n_boot, block, rng)]
    return float((_t(null) >= _t(x)).mean())


def power_curve(daily: np.ndarray, ns: list[int], n_sim: int = 2000, block: int = BLOCK, alpha: float = 0.05,
                seed: int = 0) -> pd.DataFrame:
    """Power of the one-sided test at each forward length n (days), taking `daily` as the true P&L distribution."""
    x = np.asarray(daily, float)
    rng = np.random.default_rng(seed)
    rows = []
    for n in ns:
        t_null = _t((x - x.mean())[_stationary_idx(len(x), n, n_sim, block, rng)])
        t_alt = _t(x[_stationary_idx(len(x), n, n_sim, block, rng)])
        crit = float(np.quantile(t_null, 1 - alpha))
        rows.append({"n_days": n, "crit_t": crit, "power": float((t_alt > crit).mean())})
    return pd.DataFrame(rows)


def required_n(curve: pd.DataFrame, target: float = 0.8) -> float:
    """Smallest simulated n with power >= target (NaN if the grid never reaches it)."""
    ok = curve[curve["power"] >= target]
    return float(ok["n_days"].min()) if len(ok) else float("nan")
