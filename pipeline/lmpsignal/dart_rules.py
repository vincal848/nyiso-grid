"""DART rules and P&L: pure computation. DataFrames in, DataFrames out; no DuckDB, registry, files or clocks.

Loading, the `live_dart` table, paper P&L reporting and the report files live in `dart.py` (the I/O edge); the
scenario-based pricer is `dart_pricer.py`.

A virtual INC sells energy day-ahead and buys it back in real time: P&L per MW = DA - RT. A DEC is the reverse.
NYISO allows virtuals at the 11 internal load zones. Rule v1 (declared 2026-10-05, not tuned):
    expected spread  s = mean_DA - mean_RT                                   (total price, $/MWh)
    spread scale     sigma = sqrt(sigma_DA^2 + sigma_RT^2), sigma = (q95 - q05) / 3.29 per market
    position         x = clip(s / sigma, -1, 1) MW per zone-hour (positive = INC); 0 if |s| <= COST
    P&L              x * (DA - RT) - COST * |x|
COST = $0.50/MWh traded: NYISO virtual fees plus an allowance for uplift and slippage (an assumption).
Benchmarks: 'persistence' x = sign(DA of D-1 - RT of D-2, same zone and hour) * 1 MW; 'always_dec' x = -1 MW.
Rule v2 (M4, declared 2026-10-05): distribution means, RT mean mixed with the spike member, DA/RT residual correlation.
Caveats: price-taker (bids do not move clearing prices), every zone-hour bid at the forecast, no credit or collateral limits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal.config import INTERNAL_ZONES
from lmpsignal.cv import month_fold
from lmpsignal.evaluate import QCOLS

COST = 0.50
SPIKE_DAY = pd.Timestamp("2025-06-24")
KEYS = ["delivery_date", "ts_utc", "zone", "hour_local"]


def pivot_signal(d: pd.DataFrame) -> pd.DataFrame:
    """Long hourly rows (market da / rt; mean, q05, q95, y) -> one row per internal zone-hour with *_da / *_rt columns."""
    w = d.pivot_table(index=KEYS, columns="market", values=["mean", "q05", "q95", "y"]).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    return w[w["zone"].isin(INTERNAL_ZONES)].dropna(subset=["mean_da", "mean_rt", "y_da", "y_rt"])


def positions(w: pd.DataFrame, lags: pd.DataFrame) -> pd.DataFrame:
    """Rule v1, persistence and always-DEC positions and P&L. `lags`: ts_utc, zone, lag_da_d1_total, lag_rt_d2_total."""
    w = w.copy()
    s = w["mean_da"] - w["mean_rt"]
    sig = np.sqrt(((w["q95_da"] - w["q05_da"]) / 3.29) ** 2 + ((w["q95_rt"] - w["q05_rt"]) / 3.29) ** 2)
    x = np.clip(s / sig.replace(0, np.nan), -1, 1).fillna(0.0)
    w["x_signal"] = np.where(np.abs(s) > COST, x, 0.0)
    w = w.merge(lags, on=["ts_utc", "zone"], how="left")
    w["x_persistence"] = np.sign(w["lag_da_d1_total"] - w["lag_rt_d2_total"]).fillna(0.0)
    w["x_always_dec"] = -1.0
    w["spread"] = w["y_da"] - w["y_rt"]
    for k in ("signal", "persistence", "always_dec"):
        w[f"pnl_{k}"] = w[f"x_{k}"] * w["spread"] - COST * np.abs(w[f"x_{k}"])
    return w


def stats(g: pd.DataFrame, k: str) -> dict:
    """Summary of strategy k over rows g (columns x_<k>, pnl_<k>, delivery_date)."""
    daily = g.groupby("delivery_date")[f"pnl_{k}"].sum()
    cum = daily.cumsum()
    traded = np.abs(g[f"x_{k}"]).sum()
    top = daily.abs().sort_values(ascending=False)
    return {"strategy": k, "days": len(daily), "pnl_total": daily.sum(), "pnl_per_mwh": daily.sum() / traded if traded else np.nan,
            "mwh_traded": traded, "hit_rate": float((g.loc[g[f"x_{k}"] != 0, f"pnl_{k}"] > 0).mean()),
            "sharpe_ann": daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan,
            "max_drawdown": float((cum - cum.cummax()).min()),
            "pnl_ex_2025_06_24": daily.drop(SPIKE_DAY, errors="ignore").sum(),
            "top1pct_days_share": daily.loc[top.index[: max(1, len(top) // 100)]].sum() / daily.sum() if daily.sum() else np.nan}


def backtest_tables(w: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """v1 summary per period (`w` has a `period` column) and P&L by zone."""
    rows = [{"period": p, **stats(g, k)} for p, g in w.groupby("period") for k in ("signal", "persistence", "always_dec")]
    return pd.DataFrame(rows), w.groupby(["period", "zone"])[["pnl_signal", "pnl_persistence"]].sum().reset_index()


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(f"{v:,.2f}" if isinstance(v, (float, np.floating)) else str(v) for v in r) + " |")
    return "\n".join(out)


# ----------------------------------------------------------------------------- DART v2 (M4, declared 2026-10-05)

def v2_position(dmean_da, m_rt, sd_da, sd_rt, rho):
    """DART v2 position from distribution means and scales: returns (spread, spread scale, MW position, + = INC)."""
    s = np.asarray(dmean_da, float) - np.asarray(m_rt, float)
    sd_da, sd_rt, rho = (np.asarray(v, float) for v in (sd_da, sd_rt, rho))
    sig = np.sqrt(np.clip(sd_da ** 2 + sd_rt ** 2 - 2 * rho * sd_da * sd_rt, 1e-6, None))
    return s, sig, np.where(np.abs(s) > COST, np.clip(s / sig, -1, 1), 0.0)


def rho_by_zone(resid: pd.DataFrame, end: pd.Timestamp) -> pd.Series:
    """Per-zone correlation of DA and RT residuals (r_da, r_rt) over the 365 days before `end`."""
    h = resid[(resid["delivery_date"] < end) & (resid["delivery_date"] >= end - pd.Timedelta(days=365))]
    if h.empty:
        return pd.Series(dtype=float)
    return h.groupby("zone").apply(lambda g: g["r_da"].corr(g["r_rt"]), include_groups=False)


def distribution_wide(d: pd.DataFrame, values: list[str]) -> pd.DataFrame:
    """Long total-price rows with QCOLS -> dmean (q05..q95 average) and sd ((q95 - q05)/3.29), pivoted by market."""
    d = d.assign(dmean=d[QCOLS[1:-1]].mean(axis=1), sd=(d["q95"] - d["q05"]) / 3.29)
    w = d.pivot_table(index=[c for c in ("issue_utc", *KEYS) if c in d.columns], columns="market", values=values).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    return w


def mix_spike(w: pd.DataFrame) -> pd.Series:
    """RT mean mixed with the spike member: (1 - p) * mean_RT + p * spike mean. `w` is merged with the spike rows."""
    p = w["p_spike"].fillna(0.0)
    return (1 - p) * w["dmean_rt"] + p * w["spike_mean"].fillna(w["dmean_rt"])


def positions_v2(d: pd.DataFrame, sp: pd.DataFrame, lags: pd.DataFrame) -> pd.DataFrame:
    """DART v2 backtest rows. `d`: signal total-price rows (KEYS, market, mean, QCOLS, y); `sp`: ts_utc, zone, p_spike,
    spike_mean. rho: DA/RT residual correlation over the 365 days before each month (as of the fold's training end)."""
    w = distribution_wide(d[d["zone"].isin(INTERNAL_ZONES)], ["mean", "dmean", "sd", "y", "q05", "q95"])
    w = w.dropna(subset=["dmean_da", "dmean_rt", "y_da", "y_rt"]).merge(sp, on=["ts_utc", "zone"], how="left")
    w["m_rt"] = mix_spike(w)
    w["delivery_date"] = pd.to_datetime(w["delivery_date"])
    w["r_da"], w["r_rt"] = w["y_da"] - w["mean_da"], w["y_rt"] - w["mean_rt"]
    w["month"] = w["delivery_date"].dt.to_period("M")
    rho = []
    for mon in w["month"].unique():
        c = rho_by_zone(w, pd.Timestamp(month_fold(mon.to_timestamp().date()).train_end))
        if not c.empty:                                            # first month: no prior OOS residuals -> rho = 0
            rho.append(pd.DataFrame({"month": mon, "zone": c.index, "rho": c.to_numpy()}))
    w = w.merge(pd.concat(rho, ignore_index=True), on=["month", "zone"], how="left")
    w["rho"] = w["rho"].fillna(0.0)
    _, _, w["x_signal_v2"] = v2_position(w["dmean_da"], w["m_rt"], w["sd_da"], w["sd_rt"], w["rho"])
    w["spread"] = w["y_da"] - w["y_rt"]
    w["pnl_signal_v2"] = w["x_signal_v2"] * w["spread"] - COST * np.abs(w["x_signal_v2"])
    base = positions(w[["delivery_date", "ts_utc", "zone", "hour_local", "mean_da", "mean_rt", "q05_da", "q95_da", "q05_rt",
                        "q95_rt", "y_da", "y_rt"]], lags)
    return w.merge(base[["ts_utc", "zone", "x_signal", "pnl_signal", "x_persistence", "pnl_persistence"]],
                   on=["ts_utc", "zone"])


def backtest_v2_table(w: pd.DataFrame) -> pd.DataFrame:
    w = w.rename(columns={"x_signal": "x_signal_v1", "pnl_signal": "pnl_signal_v1"})
    rows = []
    for lab, g in (("validation", w), ("validation ex 2025-06-24", w[w["delivery_date"] != SPIKE_DAY])):
        for k in ("signal_v2", "signal_v1", "persistence"):
            rows.append({"period": lab, **stats(g, k)})
    return pd.DataFrame(rows)


def live_positions_v2(f: pd.DataFrame, sp: pd.DataFrame, resid: pd.DataFrame, train_end: pd.Timestamp) -> pd.DataFrame:
    """DART v2 positions for one delivery day from live forecast rows `f` (issue_utc, KEYS, market, QCOLS) and spike rows
    `sp`; rho from `resid` (delivery_date, zone, r_da, r_rt) over the 365 days before `train_end`."""
    w = distribution_wide(f[f["zone"].isin(INTERNAL_ZONES)], ["dmean", "sd"]).merge(sp, on=["ts_utc", "zone"], how="left")
    m_rt = mix_spike(w)
    w["rho"] = w["zone"].map(rho_by_zone(resid, train_end)).fillna(0.0)
    w["spread_fcst"], w["spread_scale"], w["x_mw"] = v2_position(w["dmean_da"], m_rt, w["sd_da"], w["sd_rt"], w["rho"])
    return w[["issue_utc", "delivery_date", "ts_utc", "zone", "hour_local", "spread_fcst", "spread_scale", "rho",
              "p_spike", "x_mw"]]


def paper_pnl(x: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Daily paper P&L of positions `x` (delivery_date, ts_utc, zone, x_mw) on settled hours (outcomes: y_da, y_rt)."""
    x = x.merge(outcomes, on=["ts_utc", "zone"], how="inner").dropna(subset=["y_da", "y_rt"])
    if x.empty:
        return pd.DataFrame()
    x["pnl"] = x["x_mw"] * (x["y_da"] - x["y_rt"]) - COST * np.abs(x["x_mw"])
    x["mwh"] = np.abs(x["x_mw"])
    g = x.groupby("delivery_date").agg(mwh=("mwh", "sum"), net_mw=("x_mw", "sum"), pnl=("pnl", "sum")).reset_index()
    g["cum_pnl"] = g["pnl"].cumsum()
    return g
