"""Does a TCC pricer's gap to the auction price predict the realized gap? Pure functions on an observation table.

One row per (auction period, path) with columns: auction (cluster id, ordered by time), path, months (contract length),
c (clearing price), y (realized payoff), and one column per forecast. All amounts are $ per TCC (1 MW) over the period;
the statistics divide by `months`, so they are $ per MW-month.

  s = (forecast - c) / months      the pricer's claimed edge
  o = (y - c) / months             what buying at the clearing price actually earned
Buy rule (long only): buy 1 MW when s exceeds the assumed cost; P&L = o - cost. Cost per MW-month =
FEE_REL * |c|/months + FEE_ABS (an assumption: NYISO's auction charges and the bid-ask/price-impact a real bidder pays
are not in the public results).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal.evaluate import diebold_mariano

FEE_REL = 0.02      # share of the clearing price |c|
FEE_ABS = 0.5       # $ per MW-month


def edge(obs: pd.DataFrame, f: str, fee_rel: float = FEE_REL) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(s, o, cost) per row, $ per MW-month."""
    m = obs["months"].to_numpy(float)
    return ((obs[f] - obs["c"]).to_numpy() / m, (obs["y"] - obs["c"]).to_numpy() / m,
            fee_rel * np.abs(obs["c"].to_numpy()) / m + FEE_ABS)


def trade_pnl(s: np.ndarray, o: np.ndarray, cost: np.ndarray) -> np.ndarray:
    """Per-row P&L of the buy rule; NaN where the rule does not trade."""
    return np.where(s > cost, o - cost, np.nan)


def _cluster_sums(pnl: np.ndarray, cluster: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ids, inv = np.unique(cluster, return_inverse=True)
    traded = np.isfinite(pnl)
    return (np.bincount(inv, np.where(traded, pnl, 0.0), len(ids)), np.bincount(inv, traded.astype(float), len(ids)))


def bootstrap_mean_pnl(pnl: np.ndarray, cluster: np.ndarray, B: int = 4000, seed: int = 0) -> dict:
    """Cluster bootstrap of the mean P&L per trade (resample whole clusters: paths, or auctions). p = share of
    resamples with mean <= 0 (H1: the rule earns money)."""
    tot, n = _cluster_sums(pnl, cluster)
    if n.sum() == 0:
        return {"n_trades": 0, "mean": np.nan, "lo": np.nan, "hi": np.nan, "p": np.nan}
    w = np.random.default_rng(seed).multinomial(len(tot), np.full(len(tot), 1 / len(tot)), size=B)
    denom = w @ n
    boot = (w @ tot)[denom > 0] / denom[denom > 0]
    return {"n_trades": int(n.sum()), "mean": float(tot.sum() / n.sum()), "lo": float(np.quantile(boot, 0.025)),
            "hi": float(np.quantile(boot, 0.975)), "p": float((boot <= 0).mean())}


def slope(s: np.ndarray, o: np.ndarray, cluster: np.ndarray) -> dict:
    """OLS o = a + b*s with auction-clustered standard errors (b = 1: the pricer's gap is the true gap)."""
    X = np.column_stack([np.ones(len(s)), s])
    beta = np.linalg.lstsq(X, o, rcond=None)[0]
    r = o - X @ beta
    bread = np.linalg.inv(X.T @ X)
    meat = np.zeros((2, 2))
    for g in np.unique(cluster):
        u = X[cluster == g].T @ r[cluster == g]
        meat += np.outer(u, u)
    se = np.sqrt(np.diag(bread @ meat @ bread))
    return {"slope": float(beta[1]), "se": float(se[1]), "t": float(beta[1] / se[1]) if se[1] > 0 else np.nan}


def permutation_null(obs: pd.DataFrame, f: str, B: int = 1000, seed: int = 0, fee_rel: float = FEE_REL) -> dict:
    """Shuffle the pricer's edge s across the paths of each auction (the labels of which path gets which edge), keep o and
    cost, and recompute the buy rule's mean P&L. A pricer with real skill beats this null; shuffled edges must not."""
    s, o, cost = edge(obs, f, fee_rel)
    ok = np.isfinite(s) & np.isfinite(o)
    s, o, cost, auction = s[ok], o[ok], cost[ok], obs["auction"].to_numpy()[ok]
    groups = [np.flatnonzero(auction == a) for a in np.unique(auction)]
    rng = np.random.default_rng(seed)
    stat = lambda s_: np.nanmean(trade_pnl(s_, o, cost)) if (s_ > cost).any() else np.nan   # noqa: E731
    observed, null = stat(s), []
    for _ in range(B):
        sh = s.copy()
        for g in groups:
            sh[g] = s[rng.permutation(g)]
        null.append(stat(sh))
    null = np.array(null)
    null = null[np.isfinite(null)]
    return {"observed": float(observed), "null_mean": float(null.mean()), "null_sd": float(null.std()),
            "p": float((np.sum(null >= observed) + 1) / (len(null) + 1))}


def dm_vs(obs: pd.DataFrame, f: str, base: str) -> dict:
    """Diebold-Mariano on squared error per MW-month, averaged within each auction (HAC over the auction sequence);
    p_a_better is one-sided for 'the pricer is more accurate than the baseline'."""
    m = obs["months"]
    la, lb = ((obs["y"] - obs[f]) / m) ** 2, ((obs["y"] - obs[base]) / m) ** 2
    ok = la.notna() & lb.notna()
    return diebold_mariano(la[ok], lb[ok], obs.loc[ok, "auction"])


def summarize(obs: pd.DataFrame, f: str, baselines: tuple[str, ...], B: int = 4000, seed: int = 0,
              fee_rel: float = FEE_REL) -> dict:
    """All declared statistics for one forecast column on the rows where the forecast and the target exist."""
    d = obs[obs[f].notna() & obs["y"].notna()].reset_index(drop=True)
    s, o, cost = edge(d, f, fee_rel)
    pnl = trade_pnl(s, o, cost)
    return {"n": len(d), "n_auctions": int(d["auction"].nunique()), "n_paths": int(d["path"].nunique()),
            "slope": slope(s, o, d["auction"].to_numpy()),
            "pnl_path_boot": bootstrap_mean_pnl(pnl, d["path"].to_numpy(), B, seed),
            "pnl_auction_boot": bootstrap_mean_pnl(pnl, d["auction"].to_numpy(), B, seed),
            "placebo": permutation_null(d, f, seed=seed, fee_rel=fee_rel),
            "dm": {b: dm_vs(d, f, b) for b in baselines}}
