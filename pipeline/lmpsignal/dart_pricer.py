"""DART pricer: virtual bids and offers priced from joint DA/RT scenarios. Pure computation (arrays and DataFrames).

Declared in docs/ROADMAP.md ("DART pricer declaration"); loading, logging and the live table are in `dart_pricer_run.py`.

Per internal zone-hour the signal's DA and RT quantile rows and the zone's Gaussian-copula rho (M4, `scenarios.py`) give k joint
(DA, RT) draws. A virtual supply offer (INC, side +1) at price p clears iff DA >= p and earns DA - RT - c; a virtual load bid
(DEC, side -1) clears iff DA <= p and earns RT - DA - c, with c the all-in cost per cleared MWh. The bid curve is one step: the
price that maximises the draws' mean net P&L. Fixed bids (the 'taker' kind) always clear. Size is mu / sigma capped at the
per-zone-hour MW limit; the day's total is then scaled down to the daily-loss and collateral-proxy limits. Price taker: bids never
move prices; no dependence across hours or zones is modelled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from lmpsignal import cv, scenarios
from lmpsignal.evaluate import QCOLS

Kind = Literal["taker", "bidcurve"]
COST = 0.50                       # $ per cleared MWh, all-in (fees, uplift, slippage): the project's standing assumption
K = 500                           # draws per zone-hour (as M4)
KEYS = ["delivery_date", "ts_utc", "zone", "hour_local"]


@dataclass(frozen=True)
class Limits:
    """Per-delivery-day risk limits (assumptions; docs/ROADMAP.md). `inf` switches a limit off."""
    mw_cap: float = 1.0           # MW per zone-hour
    daily_loss: float = 3_000.0   # $: sum of x * (1% worst per-MW draw), zone-hours assumed to lose together
    collateral: float = 15_000.0  # $: sum of x * P(clear) * (99th percentile DA price), a stand-in for the credit requirement


NO_LIMITS = Limits(daily_loss=np.inf, collateral=np.inf)


def draw_joint(Q_da: np.ndarray, Q_rt: np.ndarray, rho: float, k: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """(n, k) joint DA and RT draws from quantile rows (n, 21) and a Gaussian copula."""
    u1, u2 = scenarios.draw_gaussian(rho, len(Q_da), k, rng)
    return scenarios.ppf(u1, Q_da), scenarios.ppf(u2, Q_rt)


def _best_step(da: np.ndarray, rt: np.ndarray, side: int, cost: float) -> tuple[np.ndarray, np.ndarray]:
    """Best one-step bid for `side`: (mean net P&L per MW, clearing price) per row. Clears iff side * DA >= side * price."""
    net = side * (da - rt) - cost
    order = np.argsort(-side * da, axis=1, kind="stable")                    # most favourable DA first
    cum = np.cumsum(np.take_along_axis(net, order, 1), axis=1) / da.shape[1]
    j = cum.argmax(axis=1)
    r = np.arange(len(da))
    return cum[r, j], np.take_along_axis(da, order, 1)[r, j]


def price(da: np.ndarray, rt: np.ndarray, kind: Kind, cost: float = COST, cap: float = 1.0) -> pd.DataFrame:
    """Side, clearing price, size and risk numbers per row from (n, k) joint draws. side 0 = no trade."""
    s = da - rt
    if kind == "bidcurve":
        v_inc, p_inc = _best_step(da, rt, +1, cost)
        v_dec, p_dec = _best_step(da, rt, -1, cost)
        side = np.where(v_inc >= v_dec, 1, -1)
        side = np.where(np.maximum(v_inc, v_dec) > 0, side, 0)
        thr = np.where(side == 1, p_inc, p_dec)
    else:
        m = s.mean(axis=1)
        side = np.where(m - cost > 0, 1, np.where(-m - cost > 0, -1, 0))
        thr = np.where(side == 1, -np.inf, np.where(side == -1, np.inf, np.nan))   # fixed bid: always clears
    sd = np.sign(side)[:, None]
    cleared = sd * da >= sd * thr[:, None]
    pnl = np.where(cleared & (sd != 0), sd * s - cost, 0.0)                     # per-MW net P&L draws
    mu, sigma = pnl.mean(axis=1), pnl.std(axis=1)
    if kind == "taker":
        sigma = s.std(axis=1)
        mu = np.where(side != 0, side * s.mean(axis=1) - cost, 0.0)
    x = np.where((side != 0) & (sigma > 0), np.minimum(mu / np.where(sigma > 0, sigma, 1.0), cap), 0.0)
    return pd.DataFrame({
        "side": side, "bid_price": np.where(side == 0, np.nan, thr), "p_clear": np.where(side == 0, 0.0, cleared.mean(axis=1)),
        "mu": mu, "sigma": sigma, "x_pre": np.clip(x, 0.0, None),
        "loss99": np.clip(-np.quantile(pnl, 0.01, axis=1), 0.0, None), "da_q99": np.quantile(da, 0.99, axis=1),
        "spread_mean": s.mean(axis=1), "spread_q05": np.quantile(s, 0.05, axis=1),
        "spread_q50": np.quantile(s, 0.50, axis=1), "spread_q95": np.quantile(s, 0.95, axis=1)})


def apply_limits(p: pd.DataFrame, limits: Limits) -> pd.DataFrame:
    """Final MW per row: x_pre capped per zone-hour, then each delivery day scaled to the daily-loss and collateral limits."""
    x = p["x_pre"].clip(upper=limits.mw_cap)
    day = p["delivery_date"]
    loss = (x * p["loss99"]).groupby(day).transform("sum")
    coll = (x * p["p_clear"] * p["da_q99"].clip(lower=0.0)).groupby(day).transform("sum")
    scale = np.minimum(1.0, np.minimum(limits.daily_loss / loss.where(loss > 0, np.inf),
                                       limits.collateral / coll.where(coll > 0, np.inf)))
    return p.assign(x=x * scale, limit_scale=scale)


def realize(p: pd.DataFrame, y_da: np.ndarray, y_rt: np.ndarray, cost: float = COST) -> pd.DataFrame:
    """Clearing and net P&L of positions p (side, bid_price, x) at outcomes y_da, y_rt: columns x_eff (cleared MW), pnl."""
    side = p["side"].to_numpy()
    cleared = (side * y_da >= side * p["bid_price"].fillna(0.0).to_numpy()) & (side != 0)
    x_eff = np.where(cleared, p["x"].to_numpy(), 0.0)
    return pd.DataFrame({"x_eff": x_eff, "pnl": x_eff * (side * (y_da - y_rt) - cost)}, index=p.index)


def fold_rho(w: pd.DataFrame, train_end: pd.Timestamp, lookback_days: int = 365) -> dict[str, float]:
    """Per-zone Gaussian-copula rho from the PIT pairs (u_da, u_rt) of the `lookback_days` before `train_end`;
    zones with fewer than MIN_HISTORY pairs get 0.0 (as DART v2's first month)."""
    h = w[(w["delivery_date"] < train_end) & (w["delivery_date"] >= train_end - pd.Timedelta(days=lookback_days))]
    return {z: scenarios.gaussian_rho(g["u_da"].to_numpy(), g["u_rt"].to_numpy()) if len(g) >= scenarios.MIN_HISTORY else 0.0
            for z, g in h.groupby("zone")}


def price_rows(w: pd.DataFrame, rho: dict[str, float], kind: Kind, k: int, rng: np.random.Generator, cost: float = COST,
               cap: float = 1.0) -> pd.DataFrame:
    """Price every row of wide frame `w` (to_wide columns) zone by zone; returns its non-quantile columns, rho and `price` columns."""
    out = []
    for zone, g in w.groupby("zone"):
        r = rho.get(zone, 0.0)
        da, rt = draw_joint(g[[f"da_{c}" for c in QCOLS]].to_numpy(float), g[[f"rt_{c}" for c in QCOLS]].to_numpy(float), r, k, rng)
        keep = g.drop(columns=[f"{m}_{c}" for m in ("da", "rt") for c in QCOLS])
        out.append(pd.concat([keep.assign(rho=r), price(da, rt, kind, cost, cap).set_axis(g.index)], axis=1))
    return pd.concat(out)


def backtest_rows(w: pd.DataFrame, folds: list[cv.Fold], kind: Kind, independent: bool = False, k: int = K, seed: int = 0,
                  cost: float = COST) -> pd.DataFrame:
    """Priced rows for every fold's test days. `w`: scenarios.to_wide frame of the signal's stored forecasts. The copula comes
    from PIT pairs of earlier out-of-sample rows only; `independent` forces rho = 0 (the ablation)."""
    wp = scenarios.with_pit(w)
    rows = []
    for fi, f in enumerate(folds):
        te = wp[(wp["delivery_date"] >= pd.Timestamp(f.test_start)) & (wp["delivery_date"] < pd.Timestamp(f.test_end))]
        rho = {} if independent else fold_rho(wp, pd.Timestamp(f.train_end))
        rows.append(price_rows(te, rho, kind, k, np.random.default_rng([seed, fi]), cost).assign(fold=f.name))
    return pd.concat(rows, ignore_index=True)


def shuffled_totals(p: pd.DataFrame, n_perm: int, seed: int = 0, cost: float = COST) -> np.ndarray:
    """Total net P&L of the fixed positions p (zone, hour_local, side, bid_price, x, y_da, y_rt) when the realized (DA, RT)
    pairs are shuffled across days within each zone and local hour: what the rules earn from outcomes they cannot predict."""
    rng = np.random.default_rng(seed)
    groups = [np.asarray(ix) for ix in p.groupby(["zone", "hour_local"]).indices.values()]
    y_da, y_rt = p["y_da"].to_numpy(), p["y_rt"].to_numpy()
    base = p.reset_index(drop=True)
    totals = np.empty(n_perm)
    for i in range(n_perm):
        perm = np.arange(len(p))
        for g in groups:
            perm[g] = rng.permutation(g)
        totals[i] = realize(base, y_da[perm], y_rt[perm], cost)["pnl"].sum()
    return totals


def naive_last_spread(w: pd.DataFrame) -> pd.Series:
    """Naive baseline: sign of the same zone-hour's DA - RT spread 48 hours earlier (the latest complete spread at the bid deadline).
    `w` has ts_utc, zone, y_da, y_rt for every day. ponytail: 48 h is an hour off on the two DST-change days a year."""
    lag = w[["ts_utc", "zone"]].assign(ts_utc=w["ts_utc"] + pd.Timedelta(hours=48), lag_spread=w["y_da"] - w["y_rt"])
    m = w[["ts_utc", "zone"]].merge(lag, on=["ts_utc", "zone"], how="left")
    return pd.Series(np.sign(m["lag_spread"]).fillna(0.0).to_numpy(), index=w.index)
