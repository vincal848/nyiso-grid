"""M4: joint DA/RT scenarios and the EVT tail splice. Pure computation: arrays and DataFrames in, out. No DuckDB,
registry or file access (loading and logging live in `scenario_run.py`); the DART and TCC pricers consume this module.

Marginals. A forecast is its stored quantile row (the 21 levels of `config.QUANTILES`): piecewise-linear CDF between
levels, exponential tails beyond q01 / q99 (density matched at the outermost segment). `pit` and `ppf` are inverses.

Dependence. For each zone, the DA and RT probability-integral transforms (PITs) of the signal's own out-of-sample
forecasts over the `lookback_days` before the fold's training end (all known at issue time) give the dependence:
    'indep'  independent draws (the incumbent: DART v1/v2 treat the errors as independent or use a Pearson rho only)
    'gauss'  Gaussian copula, rho = correlation of the normal scores of the zone's PIT pairs
    'emp'    empirical copula: draw PIT pairs from the zone's history
A scenario is (DA, RT) = (ppf_da(u1), ppf_rt(u2)) with (u1, u2) from the copula; the DA - RT spread distribution is
summarised by quantiles. Rows are zone-hours; no cross-hour or cross-zone dependence is modelled (a limit for TCC path
pricing, which needs it).

Tail splice. Above the base forecast's q90 the RT quantiles (q95, q99) are replaced by a generalized Pareto fit to the
zone's past out-of-sample exceedances, normalised by the forecast's own width (q95 - q05).
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri
from scipy.stats import genpareto, spearmanr

from lmpsignal import cv
from lmpsignal.config import QUANTILES
from lmpsignal.evaluate import QCOLS

QS = np.asarray(QUANTILES)
Method = Literal["indep", "gauss", "emp"]
MIN_HISTORY = 500            # PIT pairs a zone needs before a dependence model is fitted
MIN_EXCEEDANCES = 50
EPS = 1e-9


# ------------------------------------------------------------------------------------------ marginals

def _sorted(Q: np.ndarray) -> np.ndarray:
    return np.sort(np.asarray(Q, float), axis=1)


def pit(y: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """PIT of outcomes y (n,) under quantile rows Q (n, 21). Exponential tails outside [q01, q99]."""
    Q, y = _sorted(Q), np.asarray(y, float)
    r = np.arange(len(y))
    j = np.clip((Q <= y[:, None]).sum(axis=1) - 1, 0, len(QS) - 2)
    q0, q1 = Q[r, j], Q[r, j + 1]
    frac = np.clip((y - q0) / np.maximum(q1 - q0, EPS), 0, 1)
    u = QS[j] + frac * (QS[j + 1] - QS[j])
    sl = np.maximum(Q[:, 1] - Q[:, 0], EPS) / 4          # density 0.04 / (q05 - q01) at the end: scale = 0.01 / density
    su = np.maximum(Q[:, -1] - Q[:, -2], EPS) / 4
    lo, hi = y < Q[:, 0], y > Q[:, -1]
    u = np.where(lo, QS[0] * np.exp(np.minimum(y - Q[:, 0], 0) / sl), u)
    return np.where(hi, 1 - (1 - QS[-1]) * np.exp(-np.maximum(y - Q[:, -1], 0) / su), u)


def ppf(u: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Quantile function of quantile rows Q (n, 21) at levels u (n, k)."""
    Q = _sorted(Q)
    j = np.clip(np.searchsorted(QS, u) - 1, 0, len(QS) - 2)
    q0, q1 = np.take_along_axis(Q, j, 1), np.take_along_axis(Q, j + 1, 1)
    x = q0 + (u - QS[j]) / (QS[j + 1] - QS[j]) * (q1 - q0)
    sl = (np.maximum(Q[:, 1] - Q[:, 0], EPS) / 4)[:, None]
    su = (np.maximum(Q[:, -1] - Q[:, -2], EPS) / 4)[:, None]
    x = np.where(u < QS[0], Q[:, :1] + sl * np.log(np.maximum(u, EPS) / QS[0]), x)
    return np.where(u > QS[-1], Q[:, -1:] - su * np.log(np.maximum(1 - u, EPS) / (1 - QS[-1])), x)


# ------------------------------------------------------------------------------------------ dependence

def normal_scores(u: np.ndarray) -> np.ndarray:
    return ndtri(np.clip(u, 1e-6, 1 - 1e-6))


def gaussian_rho(u1: np.ndarray, u2: np.ndarray) -> float:
    return float(np.corrcoef(normal_scores(u1), normal_scores(u2))[0, 1])


def draw_gaussian(rho: float, n: int, k: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    z1, e = rng.standard_normal((n, k)), rng.standard_normal((n, k))
    return ndtr(z1), ndtr(rho * z1 + np.sqrt(1 - rho**2) * e)


def draw_empirical(pairs: np.ndarray, n: int, k: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """pairs (m, 2) of historical PITs; draws (n, k) pairs with replacement."""
    p = pairs[rng.integers(0, len(pairs), (n, k))]
    return p[..., 0], p[..., 1]


def to_wide(long: pd.DataFrame) -> pd.DataFrame:
    """Long rows (market in da / rt; mean, y, QCOLS) -> one row per zone-hour with y_da, y_rt, da_q.., rt_q.."""
    keys = ["delivery_date", "ts_utc", "zone", "hour_local"]
    cols = ["y", *QCOLS]
    w = long.pivot_table(index=keys, columns="market", values=cols).reset_index()
    w.columns = ["_".join(reversed(c)).strip("_") if c[1] else c[0] for c in w.columns]   # e.g. da_q05, rt_y
    w = w.rename(columns={"da_y": "y_da", "rt_y": "y_rt"})
    return w.dropna(subset=["y_da", "y_rt", *[f"{m}_{c}" for m in ("da", "rt") for c in QCOLS]]).reset_index(drop=True)


def _q(w: pd.DataFrame, m: str) -> np.ndarray:
    return w[[f"{m}_{c}" for c in QCOLS]].to_numpy(float)


def with_pit(w: pd.DataFrame) -> pd.DataFrame:
    return w.assign(u_da=pit(w["y_da"].to_numpy(), _q(w, "da")), u_rt=pit(w["y_rt"].to_numpy(), _q(w, "rt")))


def spread_forecast(w: pd.DataFrame, folds: list[cv.Fold], method: Method, k: int = 500, seed: int = 0,
                    lookback_days: int = 365) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Joint DA/RT scenarios per fold; returns (spread forecast rows, per-fold-zone diagnostics).

    Spread = DA - RT. Output rows: keys, y (realized spread), mean (of the draws), QCOLS (quantiles of the draws),
    pit (realized spread's rank among the draws). Zones with fewer than MIN_HISTORY earlier PIT pairs get no row for
    'gauss' / 'emp' (the first fold never has history). Diagnostics: fitted rho, Spearman of the drawn PIT pairs vs
    of the realized PIT pairs in the fold."""
    w = with_pit(w)
    rows, diag = [], []
    for fi, f in enumerate(folds):
        rng = np.random.default_rng([seed, fi])
        te = w[(w["delivery_date"] >= pd.Timestamp(f.test_start)) & (w["delivery_date"] < pd.Timestamp(f.test_end))]
        end = pd.Timestamp(f.train_end)
        hist = w[(w["delivery_date"] < end) & (w["delivery_date"] >= end - pd.Timedelta(days=lookback_days))]
        for zone, g in te.groupby("zone"):
            h = hist[hist["zone"] == zone]
            if method != "indep" and len(h) < MIN_HISTORY:
                continue
            n = len(g)
            if method == "indep":
                u1, u2, rho = *draw_gaussian(0.0, n, k, rng), 0.0
            elif method == "gauss":
                rho = gaussian_rho(h["u_da"].to_numpy(), h["u_rt"].to_numpy())
                u1, u2 = draw_gaussian(rho, n, k, rng)
            else:
                rho = gaussian_rho(h["u_da"].to_numpy(), h["u_rt"].to_numpy())
                u1, u2 = draw_empirical(h[["u_da", "u_rt"]].to_numpy(), n, k, rng)
            s = ppf(u1, _q(g, "da")) - ppf(u2, _q(g, "rt"))
            y = (g["y_da"] - g["y_rt"]).to_numpy()
            out = g[["delivery_date", "ts_utc", "zone", "hour_local"]].assign(
                y=y, mean=s.mean(axis=1), pit=(s <= y[:, None]).mean(axis=1))
            out[QCOLS] = np.quantile(s, QS, axis=1).T
            rows.append(out)
            diag.append({"fold": f.name, "zone": zone, "n_hist": len(h), "rho_fit": rho,
                         "spearman_samples": float(spearmanr(u1[:, :20].ravel(), u2[:, :20].ravel())[0]),
                         "spearman_realized": float(spearmanr(g["u_da"], g["u_rt"])[0]) if n > 2 else np.nan})
    return pd.concat(rows, ignore_index=True), pd.DataFrame(diag)


# ------------------------------------------------------------------------------------------ EVT tail splice

def _exceedances(y: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Exceedances over q90 as a multiple of the forecast width (q95 - q05)."""
    Q = _sorted(Q)
    e = (y - Q[:, 18]) / np.maximum(Q[:, 19] - Q[:, 1], EPS)
    return e[y > Q[:, 18]]


def fit_tail(y: np.ndarray, Q: np.ndarray) -> tuple[float, float]:
    """GPD (xi, sigma) of the width-normalised exceedances over q90."""
    xi, _, sigma = genpareto.fit(_exceedances(np.asarray(y, float), Q), floc=0)
    return float(xi), float(sigma)


def splice_upper(Q: np.ndarray, xi: float, sigma: float) -> np.ndarray:
    """Replace q95 and q99 by q90 + width * GPD quantile at conditional levels (0.95-0.90)/0.10 and (0.99-0.90)/0.10."""
    Q = _sorted(Q).copy()
    width = np.maximum(Q[:, 19] - Q[:, 1], EPS)
    for col, level in ((19, 0.5), (20, 0.9)):
        Q[:, col] = Q[:, 18] + width * genpareto.ppf(level, xi, scale=sigma)
    return Q


def splice_frame(df: pd.DataFrame, folds: list[cv.Fold], lookback_days: int = 730) -> pd.DataFrame:
    """RT total rows (y, QCOLS, scored, zone, delivery_date): per fold, per-zone GPD fit on earlier out-of-sample
    rows (pooled fit for zones with too few exceedances), applied to the fold's rows. Fold 1 (no history) unchanged."""
    out = df.copy()
    for f in folds:
        end = pd.Timestamp(f.train_end)
        te = ((out["delivery_date"] >= pd.Timestamp(f.test_start)) & (out["delivery_date"] < pd.Timestamp(f.test_end))).to_numpy()
        h = df[(df["delivery_date"] < end) & (df["delivery_date"] >= end - pd.Timedelta(days=lookback_days))
               & df["scored"] & df["y"].notna() & df[QCOLS].notna().all(axis=1)]
        if len(h) < MIN_HISTORY or len(_exceedances(h["y"].to_numpy(float), h[QCOLS].to_numpy(float))) < MIN_EXCEEDANCES:
            continue
        pooled = fit_tail(h["y"].to_numpy(float), h[QCOLS].to_numpy(float))
        for zone, rows in out[te].groupby("zone"):
            hz = h[h["zone"] == zone]
            ez = _exceedances(hz["y"].to_numpy(float), hz[QCOLS].to_numpy(float)) if len(hz) else []
            xi, sigma = fit_tail(hz["y"].to_numpy(float), hz[QCOLS].to_numpy(float)) if len(ez) >= MIN_EXCEEDANCES else pooled
            ok = rows[QCOLS].notna().all(axis=1)
            out.loc[ok[ok].index, QCOLS] = splice_upper(rows.loc[ok, QCOLS].to_numpy(float), xi, sigma)
    return out
