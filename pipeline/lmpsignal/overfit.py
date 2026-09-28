"""Backtest-overfitting and multiple-testing diagnostics for the validation results.

Reported as numbers only: nothing here accepts or rejects a model.

Setting. These tools were built for trading strategies' returns. We apply them to *forecast skill*:
for each run (trial) and delivery day t,
    skill_t = daily MAE of the benchmark − daily MAE of the model        ($/MWh; > 0 = model better)
averaged over the day's scored hours and zones. "SR" below is the non-annualized Sharpe ratio of that
daily skill series (mean / std). Every run in the registry is a trial, which is why all runs,
including discarded ones, are logged.

Sources (formulas checked against the papers):
  PSR, MinTRL ......... Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier", J. of Risk.
  DSR, SR0, N-hat ..... Bailey & López de Prado (2014), "The Deflated Sharpe Ratio", J. Portfolio Mgmt:
                        eq. 1-2 and appendix A.3 eq. 9 (N-hat = rho + (1 - rho) M). Kurtosis is raw (Normal = 3).
  PBO via CSCV ........ Bailey, Borwein, López de Prado & Zhu (2017), "The Probability of Backtest
                        Overfitting", J. Computational Finance: Algorithm 2.3, PBO = P(logit <= 0),
                        performance degradation, probability of loss, stochastic dominance.
  Reality Check ....... White (2000), Econometrica.  SPA: Hansen (2005), J. Business & Economic Statistics.
  Stationary bootstrap  Politis & Romano (1994), JASA.
  Holm / BHY .......... Holm (1979); Benjamini & Yekutieli (2001); as applied in Harvey, Liu & Zhu (2016),
                        "... and the Cross-Section of Expected Returns", Review of Financial Studies.
"""
from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

import numpy as np
import pandas as pd

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()


# ------------------------------------------------------------------------------ Sharpe-ratio inference

def moments(x: np.ndarray) -> dict[str, float]:
    x = np.asarray(x, float)
    mu, sd = x.mean(), x.std(ddof=1)
    if not sd > 0:                      # constant series (e.g. the benchmark's skill vs itself)
        return {"T": len(x), "mean": float(mu), "std": 0.0, "sr": float("nan"), "skew": float("nan"),
                "kurt": float("nan")}
    z = (x - mu) / x.std(ddof=0)
    return {"T": len(x), "mean": float(mu), "std": float(sd), "sr": float(mu / sd) if sd > 0 else float("nan"),
            "skew": float(np.mean(z ** 3)), "kurt": float(np.mean(z ** 4))}   # raw kurtosis


def _sr_se_term(sr: float, skew: float, kurt: float) -> float:
    return 1 - skew * sr + (kurt - 1) / 4 * sr ** 2


def psr(sr: float, T: int, skew: float, kurt: float, sr_star: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true SR > sr_star) given T obs and the returns' skew / raw kurtosis."""
    den = _sr_se_term(sr, skew, kurt)
    if not (den > 0) or T < 2 or sr != sr:
        return float("nan")
    return _N.cdf((sr - sr_star) * math.sqrt(T - 1) / math.sqrt(den))


def expected_max_sr(var_sr: float, n_trials: float) -> float:
    """SR0: expected maximum SR among n_trials independent trials whose true SR is 0 (DSR paper, eq. 1-2)."""
    if n_trials <= 1 or not (var_sr > 0):
        return 0.0
    return math.sqrt(var_sr) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


def dsr(sr: float, T: int, skew: float, kurt: float, var_sr: float, n_trials: float) -> float:
    """Deflated Sharpe Ratio = PSR evaluated at the expected-maximum threshold SR0."""
    return psr(sr, T, skew, kurt, expected_max_sr(var_sr, n_trials))


def min_track_record(sr: float, skew: float, kurt: float, sr_star: float = 0.0, confidence: float = 0.95) -> float:
    """Minimum Track Record Length (observations) for PSR(sr_star) to reach `confidence`."""
    if not (sr > sr_star):
        return float("inf")
    return 1 + _sr_se_term(sr, skew, kurt) * (_N.inv_cdf(confidence) / (sr - sr_star)) ** 2


def implied_independent_trials(series: pd.DataFrame) -> tuple[float, float]:
    """N-hat = rho + (1 - rho) * M, rho = mean pairwise correlation of the trials' series (DSR appx. A.3)."""
    M = series.shape[1]
    if M < 2:
        return float(M), float("nan")
    c = series.corr().to_numpy()
    rho = float((c.sum() - M) / (M * (M - 1)))
    return rho + (1 - rho) * M, rho


# ------------------------------------------------------------------------------ PBO via CSCV

def pbo_cscv(perf: pd.DataFrame, S: int = 16, stat: str = "mean") -> dict:
    """Probability of Backtest Overfitting by Combinatorially Symmetric Cross-Validation.

    perf: T x N matrix (rows = time-ordered days, columns = trials), higher = better.
    stat: 'mean' (mean daily skill) or 'sharpe' (mean / std) — the selection criterion.
    Returns PBO, the logit distribution summary, performance degradation (OLS of OOS on IS perf of the
    selected trial), probability of OOS loss, and a first-order stochastic-dominance check.
    """
    if S % 2:
        raise ValueError("S must be even")
    X = perf.to_numpy(float)
    T, N = X.shape
    if N < 2:
        return {"pbo": float("nan"), "n_trials": N}
    T_use = (T // S) * S
    X = X[T - T_use:]                               # drop the oldest remainder rows so blocks are equal
    blocks = X.reshape(S, T_use // S, N)
    bsum, bsq = blocks.sum(axis=1), (blocks ** 2).sum(axis=1)       # (S, N)
    n_blk = T_use // S
    combos = list(combinations(range(S), S // 2))
    sel = np.zeros((len(combos), S), bool)
    for i, c in enumerate(combos):
        sel[i, list(c)] = True

    def stat_of(mask):
        k = mask.sum(axis=1, keepdims=True) * n_blk
        s, q = mask.astype(float) @ bsum, mask.astype(float) @ bsq
        mean = s / k
        if stat == "mean":
            return mean
        var = (q - k * mean ** 2) / (k - 1)
        return mean / np.sqrt(np.maximum(var, 1e-300))

    R_is, R_oos = stat_of(sel), stat_of(~sel)                       # (C, N)
    best = R_is.argmax(axis=1)
    rows = np.arange(len(combos))
    oos_best = R_oos[rows, best]
    rank = (R_oos < oos_best[:, None]).sum(axis=1) + 1              # 1 = worst ... N = best
    omega = rank / (N + 1)
    logit = np.log(omega / (1 - omega))
    is_best = R_is[rows, best]
    beta, alpha = np.polyfit(is_best, oos_best, 1) if np.std(is_best) > 0 else (float("nan"), float("nan"))
    # stochastic dominance: selected-OOS vs all-trials-OOS distributions, compared on a quantile grid
    grid = np.linspace(0.05, 0.95, 19)
    q_sel, q_all = np.quantile(oos_best, grid), np.quantile(R_oos.ravel(), grid)
    return {
        "pbo": float(np.mean(logit <= 0)),
        "logit_median": float(np.median(logit)),
        "n_trials": N, "S": S, "combinations": len(combos), "days_used": T_use, "stat": stat,
        "degradation_slope": float(beta), "degradation_intercept": float(alpha),
        "prob_oos_loss": float(np.mean(oos_best < 0)),
        "oos_selected_median": float(np.median(oos_best)),
        "fsd_share_quantiles_selected_ge_all": float(np.mean(q_sel >= q_all)),
    }


# ------------------------------------------------------------------------------ data-snooping tests

def stationary_bootstrap_indices(T: int, B: int, mean_block: float, rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap: (B, T) index matrix, geometric block lengths."""
    p = 1.0 / mean_block
    idx = np.empty((B, T), dtype=np.int64)
    idx[:, 0] = rng.integers(0, T, B)
    new_block = rng.random((B, T)) < p
    starts = rng.integers(0, T, (B, T))
    for t in range(1, T):
        idx[:, t] = np.where(new_block[:, t], starts[:, t], (idx[:, t - 1] + 1) % T)
    return idx


def spa_test(d: pd.DataFrame, B: int = 2000, mean_block: float = 10.0, seed: int = 0) -> dict:
    """Hansen (2005) SPA test and White (2000) Reality Check for H0: no model beats the benchmark.

    d: T x K matrix of loss differentials (benchmark loss − model loss; > 0 = model better).
    Returns p-values for SPA (consistent, lower and upper) and RC; small p = evidence some model beats
    the benchmark after accounting for the search over all K models.
    """
    D = d.to_numpy(float)
    T, K = D.shape
    rng = np.random.default_rng(seed)
    idx = stationary_bootstrap_indices(T, B, mean_block, rng)
    dbar = D.mean(axis=0)
    boot_means = np.stack([D[i].mean(axis=0) for i in idx])          # (B, K)
    omega = np.sqrt(T * boot_means.var(axis=0))
    omega = np.where(omega > 0, omega, np.nan)
    t_stat = np.nanmax(np.sqrt(T) * dbar / omega)
    t_spa = max(0.0, t_stat)
    thr = -np.sqrt(omega ** 2 / T * 2 * np.log(np.log(T)))
    centred = boot_means - dbar
    out = {}
    # Null recentring mu = dbar - g(dbar) (Hansen 2005): lower g=max(x,0) (liberal), consistent g=x*1{x>=-A},
    # upper g=x (conservative, RC-like). Hence p_lower <= p_consistent <= p_upper.
    for name, mu in (("spa_lower", np.minimum(dbar, 0)),
                     ("spa_consistent", np.where(dbar >= thr, 0.0, dbar)),
                     ("spa_upper", np.zeros(K))):
        stat_b = np.nanmax(np.sqrt(T) * (centred + mu) / omega, axis=1)
        out[f"p_{name}"] = float(np.mean(np.maximum(stat_b, 0) >= t_spa))
    rc_b = np.max(np.sqrt(T) * centred, axis=1)
    out["p_reality_check"] = float(np.mean(rc_b >= np.sqrt(T) * dbar.max()))
    out.update({"spa_stat": float(t_spa), "models": K, "days": T, "bootstrap": B, "mean_block": mean_block})
    return out


def holm(p: pd.Series) -> pd.Series:
    order = p.sort_values().index
    m = len(p)
    adj, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * p[k]))
        adj[k] = running
    return pd.Series(adj).reindex(p.index)


def bhy(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg-Yekutieli FDR-adjusted p-values (valid under arbitrary dependence)."""
    m = len(p)
    c_m = sum(1 / i for i in range(1, m + 1))
    order = p.sort_values(ascending=False).index
    adj, running = {}, 1.0
    for rank_desc, k in enumerate(order):
        i = m - rank_desc
        running = min(running, min(1.0, p[k] * m * c_m / i))
        adj[k] = running
    return pd.Series(adj).reindex(p.index)
