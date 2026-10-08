"""DART pricer edge: validation runs (logged), the live table `live_dart_pricer`, and the forward score.

Declared in docs/ROADMAP.md ("DART pricer declaration"). Pure computation is in `dart_pricer.py` / `dart_forward.py`.
Runs are logged like model runs (`dart_taker`, `dart_bidcurve`, `dart_bidcurve_indep`; market "dart", component "pnl").
Validation numbers are development only: the holdout is spent. The forward window is the only clean test.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from lmpsignal import cv, registry, scenarios
from lmpsignal import dart as dart_io
from lmpsignal import dart_forward as fw
from lmpsignal import dart_pricer as dp
from lmpsignal.config import INTERNAL_ZONES
from lmpsignal.diagnostics import completed_runs
from lmpsignal.evaluate import QCOLS
from lmpsignal.presets import SIGNAL_V1

CANDIDATES: dict[str, tuple[dp.Kind, bool]] = {          # name -> (kind, independent draws)
    "dart_taker": ("taker", False), "dart_bidcurve": ("bidcurve", False), "dart_bidcurve_indep": ("bidcurve", True)}
LIMITS = dp.Limits()
SEED = 0
FORWARD_START = date(2026, 10, 9)    # first delivery day of the forward window: set to the first day after the daily job is re-enabled


def wide_signal(run_id: str) -> pd.DataFrame:
    """Signal v1's stored total-price forecasts and outcomes, one row per internal zone-hour (scenarios.to_wide)."""
    d = dart_io.load_long(run_id)
    d["delivery_date"] = pd.to_datetime(d["delivery_date"])
    return scenarios.to_wide(d[d["zone"].isin(INTERNAL_ZONES)])


# ----------------------------------------------------------------------------- validation runs

def priced(name: str, w: pd.DataFrame, folds: list[cv.Fold], k: int = dp.K) -> pd.DataFrame:
    """Candidate `name` over `folds`: priced rows with limits on (x, pnl) and off (x_nolimit, pnl_nolimit), cost dp.COST."""
    kind, indep = CANDIDATES[name]
    p = dp.backtest_rows(w, folds, kind, indep, k, SEED)
    lim, off = dp.apply_limits(p, LIMITS), dp.apply_limits(p, dp.NO_LIMITS)
    out = lim.join(dp.realize(lim, lim["y_da"].to_numpy(), lim["y_rt"].to_numpy()))
    r0 = dp.realize(off, off["y_da"].to_numpy(), off["y_rt"].to_numpy())
    return out.assign(x_nolimit=off["x"], x_eff_nolimit=r0["x_eff"], pnl_nolimit=r0["pnl"]).sort_values(["ts_utc", "zone"])


def run(name: str, folds: list[cv.Fold] | None = None, log: bool = True) -> str | None:
    folds = folds or cv.folds()
    parent = completed_runs([SIGNAL_V1])[SIGNAL_V1]
    out = priced(name, wide_signal(parent), folds)
    if not log:
        return None
    kind, indep = CANDIDATES[name]
    cfg = {"model": f"DART pricer ({kind}, {'independent' if indep else 'Gaussian copula'} draws)", "parent": parent,
           "kind": kind, "independent": indep, "draws": dp.K, "seed": SEED, "cost": dp.COST, "limits": LIMITS.__dict__,
           "lookback_days": 365, "folds": len(folds), "first_fold": folds[0].name, "last_fold": folds[-1].name}
    run_id = registry.start_run(name, cfg, len(out))
    try:
        for f in folds:
            part = out[out["fold"] == f.name]
            scores = pd.DataFrame({"market": "dart", "component": "pnl", "zone": "ALL", "pnl": [part["pnl"].sum()],
                                   "mwh_cleared": [part["x_eff"].sum()]})
            registry.save_fold(run_id, f.name, part, scores)
    except Exception as e:
        registry.finish_run(run_id, "failed", repr(e))
        raise
    registry.finish_run(run_id)
    return run_id


def load_run(run_id: str) -> pd.DataFrame:
    p = registry.predictions(run_id)
    p["delivery_date"] = pd.to_datetime(p["delivery_date"])
    return p


# ----------------------------------------------------------------------------- live

LIVE_SCHEMA = """CREATE TABLE IF NOT EXISTS live_dart_pricer (
    candidate VARCHAR, signal VARCHAR, issue_utc TIMESTAMPTZ, delivery_date DATE, ts_utc TIMESTAMPTZ, zone VARCHAR,
    hour_local INTEGER, rho DOUBLE, side INTEGER, bid_price DOUBLE, p_clear DOUBLE, spread_mean DOUBLE, spread_q05 DOUBLE,
    spread_q50 DOUBLE, spread_q95 DOUBLE, mu DOUBLE, sigma DOUBLE, x_mw DOUBLE, limit_scale DOUBLE,
    git_commit VARCHAR, created_utc TIMESTAMPTZ)"""
SCORE_SCHEMA = """CREATE TABLE IF NOT EXISTS dart_forward_score (
    candidate VARCHAR, scored_utc TIMESTAMPTZ, n_days INTEGER, first_day DATE, last_day DATE, mean_daily DOUBLE, total DOUBLE,
    t_stat DOUBLE, p_value DOUBLE, verdict VARCHAR, git_commit VARCHAR)"""


def _long_to_wide(f: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    w = f.pivot_table(index=keys, columns="market", values=QCOLS)
    w.columns = [f"{m}_{q}" for q, m in w.columns]
    return w.reset_index()


def _pit_history(signal: str) -> pd.DataFrame:
    """Wide rows with outcomes and PITs: validation run + M7 holdout continuation + live days that have settled."""
    parent = completed_runs([signal])[signal]
    hold = dart_io.lineage_holdout(signal)
    h = wide_signal(parent + (("+" + hold) if hold else ""))
    with registry.connect(read_only=True) as con:
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'live_forecasts'").fetchone()[0]
        lv = con.execute(f"""SELECT delivery_date, ts_utc, zone, hour_local, market, {', '.join(QCOLS)} FROM live_forecasts
                             WHERE signal = ? AND component = 'total'""", [signal]).df() if has else pd.DataFrame()
    if not lv.empty:
        lw = _long_to_wide(lv, ["delivery_date", "ts_utc", "zone", "hour_local"]).merge(dart_io.outcomes(), on=["ts_utc", "zone"])
        lw["delivery_date"] = pd.to_datetime(lw["delivery_date"])
        lw = lw[lw["zone"].isin(INTERNAL_ZONES)].dropna(subset=["y_da", "y_rt"])
        h = pd.concat([h, lw[lw["ts_utc"] > h["ts_utc"].max()]], ignore_index=True)
    return scenarios.with_pit(h)


def live_price(d: date, candidate: str, signal: str = SIGNAL_V1) -> pd.DataFrame:
    """Pricer positions for delivery day D from the live forecast -> experiments.duckdb live_dart_pricer. The copula's rho comes
    from earlier out-of-sample rows only (the validation rule for D's month, as DART v2's rho)."""
    kind, indep = CANDIDATES[candidate]
    f = dart_io.live_rows(d, signal)
    w = _long_to_wide(f[f["zone"].isin(INTERNAL_ZONES)], ["issue_utc", "delivery_date", "ts_utc", "zone", "hour_local"])
    rho = {} if indep else dp.fold_rho(_pit_history(signal), pd.Timestamp(cv.month_fold(d).train_end))
    rows = dp.apply_limits(dp.price_rows(w, rho, kind, dp.K, np.random.default_rng([SEED, d.toordinal()])), LIMITS)
    out = rows.assign(candidate=candidate, signal=signal, x_mw=rows["x"], git_commit=registry.git_commit(),
                      created_utc=datetime.now(UTC))
    with registry.connect() as con:
        con.execute(LIVE_SCHEMA)
        con.execute("DELETE FROM live_dart_pricer WHERE candidate = ? AND delivery_date = ?", [candidate, d])
        con.register("o", out)
        con.execute("""INSERT INTO live_dart_pricer SELECT candidate, signal, issue_utc, delivery_date, ts_utc, zone, hour_local,
                       rho, side, bid_price, p_clear, spread_mean, spread_q05, spread_q50, spread_q95, mu, sigma, x_mw,
                       limit_scale, git_commit, created_utc FROM o""")
    return out


def daily_pnl(x: pd.DataFrame) -> pd.Series:
    """Net daily P&L of counted-day positions (columns side, bid_price, x, y_da, y_rt, delivery_date)."""
    r = dp.realize(x, x["y_da"].to_numpy(), x["y_rt"].to_numpy())
    return r["pnl"].groupby(x["delivery_date"]).sum()


def forward_positions(candidate: str) -> pd.DataFrame:
    """Stored forward positions as (delivery_date, ts_utc, zone, side, bid_price, x, created_utc). `dart_v2` is the live_dart rule
    (fixed bids: always clear); a pricer candidate is read from live_dart_pricer."""
    with registry.connect(read_only=True) as con:
        table = "live_dart" if candidate == "dart_v2" else "live_dart_pricer"
        if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]).fetchone()[0]:
            return pd.DataFrame(columns=["delivery_date"])
        if candidate == "dart_v2":
            x = con.execute("SELECT delivery_date, ts_utc, zone, x_mw, created_utc FROM live_dart WHERE rule = 'v2'").df()
            side = np.sign(x["x_mw"]).astype(int)
            x = x.assign(side=side, bid_price=np.where(side == 0, np.nan, -side * np.inf), x=x["x_mw"].abs())
        else:
            x = con.execute("""SELECT delivery_date, ts_utc, zone, side, bid_price, x_mw AS x, created_utc FROM live_dart_pricer
                               WHERE candidate = ?""", [candidate]).df()
    x["delivery_date"] = pd.to_datetime(x["delivery_date"])
    return x


def score(candidate: str = "dart_v2") -> str:
    """The forward score (docs/ROADMAP.md, DART pricer declaration). Before N counted days: progress only. At N: the declared
    test, stored once (the first N days); later calls return the stored result and never re-test."""
    with registry.connect() as con:
        con.execute(SCORE_SCHEMA)
        done = con.execute("SELECT * FROM dart_forward_score WHERE candidate = ?", [candidate]).df()
    if not done.empty:
        r = done.iloc[0]
        return (f"{candidate}: scored {r['scored_utc']:%Y-%m-%d} on {r['n_days']} days {r['first_day']}..{r['last_day']}: "
                f"mean ${r['mean_daily']:,.2f}/day, total ${r['total']:,.0f}, p = {r['p_value']:.3f}: {r['verdict']}")
    x = forward_positions(candidate)
    x = fw.counted(x, dart_io.outcomes(), pd.Timestamp(FORWARD_START)) if not x.empty else x
    daily = daily_pnl(x) if not x.empty else pd.Series(dtype=float)
    r = fw.evaluate(daily, pd.Timestamp(FORWARD_START), pd.Timestamp(date.today()))
    if r["status"] == "waiting":
        return (f"{candidate}: {r['n_days']} of {fw.FORWARD_N} counted settled days since {FORWARD_START} "
                f"(coverage {r['coverage']:.0%}); cum net P&L ${r['total']:,.0f}. Not scoring before {fw.FORWARD_N} (declared, no early looks).")
    if r["status"] == "invalid":
        return f"{candidate}: invalid forward record, coverage {r['coverage']:.0%} < {fw.MIN_COVERAGE:.0%} of days since {FORWARD_START}"
    with registry.connect() as con:
        con.execute("INSERT INTO dart_forward_score VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [candidate, datetime.now(UTC), r["n_days"], r["first_day"].date(), r["last_day"].date(), r["mean_daily"],
                     r["total"], r["t_stat"], r["p_value"], r["verdict"], registry.git_commit()])
    return (f"{candidate}: scored on {r['n_days']} days {r['first_day']:%Y-%m-%d}..{r['last_day']:%Y-%m-%d}: "
            f"mean ${r['mean_daily']:,.2f}/day, total ${r['total']:,.0f}, p = {r['p_value']:.3f}: {r['verdict']}")
