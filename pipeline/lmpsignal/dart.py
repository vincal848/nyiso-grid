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

def v2_position(dmean_da, m_rt, sd_da, sd_rt, rho):
    """DART v2 position from distribution means and scales: returns (spread, spread scale, MW position, + = INC)."""
    s = np.asarray(dmean_da, float) - np.asarray(m_rt, float)
    sd_da, sd_rt, rho = (np.asarray(v, float) for v in (sd_da, sd_rt, rho))
    sig = np.sqrt(np.clip(sd_da ** 2 + sd_rt ** 2 - 2 * rho * sd_da * sd_rt, 1e-6, None))
    return s, sig, np.where(np.abs(s) > COST, np.clip(s / sig, -1, 1), 0.0)


def _rho(resid: pd.DataFrame, end: pd.Timestamp) -> pd.Series:
    """Per-zone correlation of DA and RT residuals (r_da, r_rt) over the 365 days before `end`."""
    h = resid[(resid["delivery_date"] < end) & (resid["delivery_date"] >= end - pd.Timedelta(days=365))]
    if h.empty:
        return pd.Series(dtype=float)
    return h.groupby("zone").apply(lambda g: g["r_da"].corr(g["r_rt"]), include_groups=False)


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
        c = _rho(w, pd.Timestamp(month_fold(mon.to_timestamp().date()).train_end))
        if not c.empty:                                            # first month: no prior OOS residuals -> rho = 0
            rho.append(pd.DataFrame({"month": mon, "zone": c.index, "rho": c.to_numpy()}))
    w = w.merge(pd.concat(rho, ignore_index=True), on=["month", "zone"], how="left")
    w["rho"] = w["rho"].fillna(0.0)
    _, _, w["x_signal_v2"] = v2_position(w["dmean_da"], w["m_rt"], w["sd_da"], w["sd_rt"], w["rho"])
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


# ----------------------------------------------------------------------------- DART v2 live paper trading
# Positions for delivery day D from the live signal (`live_forecasts`) and the live spike member (`live_spike`), with
# rho from the signal's residuals over the 365 days before D's training end (validation run + M7 holdout + earlier
# live days). Paper only: validated on the validation folds, no out-of-sample confirmation yet (ROADMAP, M4 result).

LIVE_SCHEMA = """CREATE TABLE IF NOT EXISTS live_dart (
    rule VARCHAR, signal VARCHAR, issue_utc TIMESTAMPTZ, delivery_date DATE, ts_utc TIMESTAMPTZ, zone VARCHAR,
    hour_local INTEGER, spread_fcst DOUBLE, spread_scale DOUBLE, rho DOUBLE, p_spike DOUBLE, x_mw DOUBLE,
    git_commit VARCHAR, created_utc TIMESTAMPTZ)"""


def _outcomes() -> pd.DataFrame:
    con = duckdb.connect(str(FEATURES_DB), read_only=True)
    try:
        return con.execute("SELECT ts_utc, zone, da_total AS y_da, rt_total AS y_rt FROM panel").df()
    finally:
        con.close()


def residual_history(signal: str) -> pd.DataFrame:
    """delivery_date, zone, r_da, r_rt of the signal's total-price mean: validation + M7 holdout + live days."""
    from lmpsignal import registry
    from lmpsignal.diagnostics import completed_runs

    runs = [completed_runs([signal])[signal]]
    hold = lineage_holdout(signal)
    runs += hold.split("+") if hold else []
    d = pd.concat([duckdb.sql(f"""SELECT delivery_date, ts_utc, zone, market, mean, y
                                  FROM read_parquet('{(EXPERIMENTS_DIR / r).as_posix()}/fold=*.parquet')
                                  WHERE component = 'total'""").df() for r in runs], ignore_index=True)
    d = d.drop_duplicates(["ts_utc", "zone", "market"], keep="last")
    w = d.pivot_table(index=["delivery_date", "ts_utc", "zone"], columns="market", values=["mean", "y"]).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    with registry.connect(read_only=True) as con:
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'live_forecasts'").fetchone()[0]
        lv = con.execute("""SELECT delivery_date, ts_utc, zone, market, mean FROM live_forecasts
                            WHERE signal = ? AND component = 'total'""", [signal]).df() if has else pd.DataFrame()
    if not lv.empty:
        lw = lv.pivot_table(index=["delivery_date", "ts_utc", "zone"], columns="market", values="mean").reset_index()
        lw = lw.rename(columns={"da": "mean_da", "rt": "mean_rt"}).merge(_outcomes(), on=["ts_utc", "zone"], how="left")
        w = pd.concat([w, lw[lw["ts_utc"] > w["ts_utc"].max()]], ignore_index=True)
    w["delivery_date"] = pd.to_datetime(w["delivery_date"])
    w = w.dropna(subset=["mean_da", "mean_rt", "y_da", "y_rt"])
    return w.assign(r_da=w["y_da"] - w["mean_da"], r_rt=w["y_rt"] - w["mean_rt"])


def live_v2(d, signal: str | None = None) -> pd.DataFrame:
    """DART v2 paper positions for delivery day D -> experiments.duckdb live_dart."""
    from datetime import datetime, timezone

    from lmpsignal import registry
    from lmpsignal.evaluate import QCOLS
    from lmpsignal.live import month_fold
    from lmpsignal.presets import SIGNAL_V1

    signal = signal or SIGNAL_V1
    inner = QCOLS[1:-1]
    with registry.connect(read_only=True) as con:
        f = con.execute(f"""SELECT issue_utc, delivery_date, ts_utc, zone, hour_local, market, {', '.join(QCOLS)}
                            FROM live_forecasts WHERE signal = ? AND delivery_date = ? AND component = 'total'""",
                        [signal, d]).df()
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'live_spike'").fetchone()[0]
        sp = con.execute("""SELECT ts_utc, zone, p_spike, mean AS spike_mean FROM live_spike
                            WHERE delivery_date = ? AND model = 'spike_full'""", [d]).df() if has else pd.DataFrame()
    if f.empty or sp.empty:
        raise ValueError(f"need live_forecasts and live_spike for {d}: run `lmp forecast` and `lmp risk` first")
    f = f[f["zone"].isin(INTERNAL_ZONES)].copy()
    f["dmean"] = f[inner].mean(axis=1)
    f["sd"] = (f["q95"] - f["q05"]) / 3.29
    w = f.pivot_table(index=["issue_utc", "delivery_date", "ts_utc", "zone", "hour_local"], columns="market",
                      values=["dmean", "sd"]).reset_index()
    w.columns = ["_".join(c).strip("_") for c in w.columns]
    w = w.merge(sp, on=["ts_utc", "zone"], how="left")
    p = w["p_spike"].fillna(0.0)
    m_rt = (1 - p) * w["dmean_rt"] + p * w["spike_mean"].fillna(w["dmean_rt"])
    rho = _rho(residual_history(signal), pd.Timestamp(month_fold(d).train_end))
    w["rho"] = w["zone"].map(rho).fillna(0.0)
    w["spread_fcst"], w["spread_scale"], w["x_mw"] = v2_position(w["dmean_da"], m_rt, w["sd_da"], w["sd_rt"], w["rho"])
    out = w[["issue_utc", "delivery_date", "ts_utc", "zone", "hour_local", "spread_fcst", "spread_scale", "rho",
             "p_spike", "x_mw"]].assign(rule="v2", signal=signal, git_commit=registry.git_commit(),
                                        created_utc=datetime.now(timezone.utc))
    with registry.connect() as con:
        con.execute(LIVE_SCHEMA)
        con.execute("DELETE FROM live_dart WHERE rule = 'v2' AND delivery_date = ?", [d])
        con.register("o", out)
        con.execute("""INSERT INTO live_dart SELECT rule, signal, issue_utc, delivery_date, ts_utc, zone, hour_local,
                       spread_fcst, spread_scale, rho, p_spike, x_mw, git_commit, created_utc FROM o""")
    return out


def paper() -> pd.DataFrame:
    """Daily paper P&L of the live DART v2 positions on settled days (DA and RT outcomes known)."""
    from lmpsignal import registry

    with registry.connect(read_only=True) as con:
        if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'live_dart'").fetchone()[0]:
            return pd.DataFrame()
        x = con.execute("SELECT delivery_date, ts_utc, zone, x_mw FROM live_dart WHERE rule = 'v2'").df()
    x = x.merge(_outcomes(), on=["ts_utc", "zone"], how="inner").dropna(subset=["y_da", "y_rt"])
    if x.empty:
        return pd.DataFrame()
    x["pnl"] = x["x_mw"] * (x["y_da"] - x["y_rt"]) - COST * np.abs(x["x_mw"])
    x["mwh"] = np.abs(x["x_mw"])
    g = x.groupby("delivery_date").agg(mwh=("mwh", "sum"), net_mw=("x_mw", "sum"), pnl=("pnl", "sum")).reset_index()
    g["cum_pnl"] = g["pnl"].cumsum()
    return g
