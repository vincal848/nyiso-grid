"""DART prototype: zonal virtual positions from the signal's DA and RT forecasts, backtested on stored forecasts.

A virtual INC sells energy day-ahead and buys it back in real time: P&L per MW = DA - RT. A DEC is the reverse.
NYISO allows virtuals at the 11 internal load zones. Rule (declared 2026-10-05, not tuned):
    expected spread  s = mean_DA - mean_RT                                   (total price, $/MWh)
    spread scale     sigma = sqrt(sigma_DA^2 + sigma_RT^2), sigma = (q95 - q05) / 3.29 per market
    position         x = clip(s / sigma, -1, 1) MW per zone-hour (positive = INC); 0 if |s| <= COST
    P&L              x * (DA - RT) - COST * |x|
COST = $0.50/MWh traded: NYISO virtual fees plus an allowance for uplift and slippage (an assumption).
Benchmarks: 'persistence' x = sign(DA of D-1 - RT of D-2, same zone and hour) * 1 MW; 'always_dec' x = -1 MW.
Caveats: price-taker (bids do not move clearing prices), DA and RT forecast errors treated as independent (no
joint distribution yet: M4), every zone-hour bid at the forecast, no credit or collateral limits.
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd

from lmpsignal.config import EXPERIMENTS_DIR, FEATURES_DB, HOLDOUT_START, INTERNAL_ZONES

COST = 0.50
SPIKE_DAY = pd.Timestamp("2025-06-24")


def load_signal(run_spec: str) -> pd.DataFrame:
    """Hourly zone rows with DA/RT total forecast mean, q05, q95 and outcomes, from one or more '+'-joined runs."""
    frames = []
    for rid in run_spec.split("+"):
        frames.append(duckdb.sql(f"""
            SELECT delivery_date, ts_utc, zone, hour_local, market, mean, q05, q95, y
            FROM read_parquet('{(EXPERIMENTS_DIR / rid).as_posix()}/fold=*.parquet')
            WHERE component = 'total'""").df())
    d = pd.concat(frames, ignore_index=True).drop_duplicates(["ts_utc", "zone", "market"], keep="last")
    w = d.pivot_table(index=["delivery_date", "ts_utc", "zone", "hour_local"], columns="market",
                      values=["mean", "q05", "q95", "y"]).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    return w[w["zone"].isin(INTERNAL_ZONES)].dropna(subset=["mean_da", "mean_rt", "y_da", "y_rt"])


def positions(w: pd.DataFrame, lags: pd.DataFrame | None = None) -> pd.DataFrame:
    w = w.copy()
    s = w["mean_da"] - w["mean_rt"]
    sig = np.sqrt(((w["q95_da"] - w["q05_da"]) / 3.29) ** 2 + ((w["q95_rt"] - w["q05_rt"]) / 3.29) ** 2)
    x = np.clip(s / sig.replace(0, np.nan), -1, 1).fillna(0.0)
    w["x_signal"] = np.where(np.abs(s) > COST, x, 0.0)
    if lags is None:
        con = duckdb.connect(str(FEATURES_DB), read_only=True)
        lags = con.execute("SELECT ts_utc, zone, lag_da_d1_total, lag_rt_d2_total FROM panel").df()
        con.close()
    w = w.merge(lags, on=["ts_utc", "zone"], how="left")
    w["x_persistence"] = np.sign(w["lag_da_d1_total"] - w["lag_rt_d2_total"]).fillna(0.0)
    w["x_always_dec"] = -1.0
    w["spread"] = w["y_da"] - w["y_rt"]
    for k in ("signal", "persistence", "always_dec"):
        w[f"pnl_{k}"] = w[f"x_{k}"] * w["spread"] - COST * np.abs(w[f"x_{k}"])
    return w


def _stats(g: pd.DataFrame, k: str) -> dict:
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


def backtest(validation_run: str, holdout_spec: str | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    w = load_signal(validation_run + (("+" + holdout_spec) if holdout_spec else ""))
    w["delivery_date"] = pd.to_datetime(w["delivery_date"])
    w["period"] = np.where(w["delivery_date"] >= pd.Timestamp(HOLDOUT_START), "holdout", "validation")
    w = positions(w)
    rows = [{"period": p, **_stats(g, k)} for p, g in w.groupby("period") for k in ("signal", "persistence", "always_dec")]
    by_zone = (w.groupby(["period", "zone"])[["pnl_signal", "pnl_persistence"]].sum().reset_index())
    return pd.DataFrame(rows), by_zone


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(f"{v:,.2f}" if isinstance(v, (float, np.floating)) else str(v) for v in r) + " |")
    return "\n".join(out)


def write_report(summary: pd.DataFrame, by_zone: pd.DataFrame, path) -> None:
    doc =["# DART prototype backtest", "", "_Generated by `lmp dart`. Rule and caveats: `pipeline/lmpsignal/dart.py`._", "",
           f"Positions per internal zone and hour, at most 1 MW, cost ${COST:.2f}/MWh traded. P&L in $ per 1 MW position "
           "limit summed over zones and hours. Validation = stored out-of-sample forecasts 2022-10..2025-09; holdout = "
           "the M7 run 2025-10..2026-09.", "", "## Summary", "", md(summary), "", "## P&L by zone", "",
           md(by_zone.pivot(index="zone", columns="period", values="pnl_signal").reset_index()), "",
           "## Diagnosis (2026-10-05)", "",
           "The declared rule loses despite a 55-56% hit rate: losing hours are much larger than winning ones. Signal "
           "v1's point forecast behaves like a median (LightGBM-L1 targets the median; LEAR is fit in asinh space), "
           "and RT prices are right-skewed, so the RT forecast understates the RT mean more than DA: validation "
           "averages RT 38.0 forecast vs 42.5 actual, DA 41.2 vs 42.6. The forecast spread therefore leans ~+$3 to "
           "INC while the realized spread averages ~0, and RT spikes punish the INC bias. A DART rule needs "
           "conditional-mean forecasts (mean-targeting models, or the forecast distribution's mean) and explicit RT "
           "spike risk (M3b, joint DA/RT in M4). Logged in docs/RESEARCH_LOG.md; the declared rule is not re-tuned.", ""]
    path.write_text("\n".join(doc), encoding="utf-8")


def lineage_holdout(signal: str) -> str | None:
    p = EXPERIMENTS_DIR / "m7_lineage.json"
    if not p.exists():
        return None
    lin = json.loads(p.read_text())
    return lin.get(signal) if lin.get("candidate") == signal else None


# ----------------------------------------------------------------------------- DART v2 (M4, declared 2026-10-05)

def positions_v2(signal_run: str, spike_run: str, lags: pd.DataFrame | None = None) -> pd.DataFrame:
    """DART v2: distribution means (q05..q95 average), RT mean mixed with the spike member, DA/RT residual correlation
    over the 365 days before each month (as of the fold's training end). See docs/ROADMAP.md, M4 declaration."""
    from lmpsignal.evaluate import QCOLS
    from lmpsignal.live import month_fold

    inner = QCOLS[1:-1]                                            # q05..q95
    d = duckdb.sql(f"""SELECT delivery_date, ts_utc, zone, hour_local, market, mean, {', '.join(QCOLS)}, y
                       FROM read_parquet('{(EXPERIMENTS_DIR / signal_run).as_posix()}/fold=*.parquet')
                       WHERE component = 'total'""").df()
    d = d[d["zone"].isin(INTERNAL_ZONES)]
    d["dmean"] = d[inner].mean(axis=1)
    d["sd"] = (d["q95"] - d["q05"]) / 3.29
    w = d.pivot_table(index=["delivery_date", "ts_utc", "zone", "hour_local"], columns="market",
                      values=["mean", "dmean", "sd", "y", "q05", "q95"]).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    w = w.dropna(subset=["dmean_da", "dmean_rt", "y_da", "y_rt"])
    sp = duckdb.sql(f"""SELECT ts_utc, zone, p_spike, mean AS spike_mean
                        FROM read_parquet('{(EXPERIMENTS_DIR / spike_run).as_posix()}/fold=*.parquet')""").df()
    w = w.merge(sp, on=["ts_utc", "zone"], how="left")
    p = w["p_spike"].fillna(0.0)
    w["m_rt"] = (1 - p) * w["dmean_rt"] + p * w["spike_mean"].fillna(w["dmean_rt"])
    # residual correlation per zone, from the 365 days before each month's training end
    w["delivery_date"] = pd.to_datetime(w["delivery_date"])
    w["r_da"], w["r_rt"] = w["y_da"] - w["mean_da"], w["y_rt"] - w["mean_rt"]
    w["month"] = w["delivery_date"].dt.to_period("M")
    rho = []
    for mon in w["month"].unique():
        end = pd.Timestamp(month_fold(mon.to_timestamp().date()).train_end)
        h = w[(w["delivery_date"] < end) & (w["delivery_date"] >= end - pd.Timedelta(days=365))]
        if h.empty:                                                # first months: no prior OOS residuals -> rho = 0
            continue
        c = h.groupby("zone").apply(lambda g: g["r_da"].corr(g["r_rt"]), include_groups=False)
        rho.append(pd.DataFrame({"month": mon, "zone": c.index, "rho": c.to_numpy()}))
    w = w.merge(pd.concat(rho, ignore_index=True), on=["month", "zone"], how="left")
    w["rho"] = w["rho"].fillna(0.0)
    s = w["dmean_da"] - w["m_rt"]
    sig = np.sqrt((w["sd_da"] ** 2 + w["sd_rt"] ** 2 - 2 * w["rho"] * w["sd_da"] * w["sd_rt"]).clip(lower=1e-6))
    w["x_signal_v2"] = np.where(np.abs(s) > COST, np.clip(s / sig, -1, 1), 0.0)
    w["spread"] = w["y_da"] - w["y_rt"]
    w["pnl_signal_v2"] = w["x_signal_v2"] * w["spread"] - COST * np.abs(w["x_signal_v2"])
    # v1 rule and persistence on the same rows, for comparison
    base = positions(w.rename(columns={"mean_da": "mean_da", "mean_rt": "mean_rt"})[
        ["delivery_date", "ts_utc", "zone", "hour_local", "mean_da", "mean_rt", "q05_da", "q95_da", "q05_rt", "q95_rt",
         "y_da", "y_rt"]], lags)
    return w.merge(base[["ts_utc", "zone", "x_signal", "pnl_signal", "x_persistence", "pnl_persistence"]],
                   on=["ts_utc", "zone"])


def backtest_v2(signal_run: str, spike_run: str) -> pd.DataFrame:
    w = positions_v2(signal_run, spike_run)
    w = w.rename(columns={"x_signal": "x_signal_v1", "pnl_signal": "pnl_signal_v1"})
    rows = []
    for lab, g in (("validation", w), ("validation ex 2025-06-24", w[w["delivery_date"] != SPIKE_DAY])):
        for k in ("signal_v2", "signal_v1", "persistence"):
            rows.append({"period": lab, **_stats(g, k)})
    return pd.DataFrame(rows)
