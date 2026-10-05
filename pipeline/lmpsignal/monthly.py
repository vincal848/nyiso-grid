"""M5: monthly DA products, horizons 1-6 months (declared in docs/ROADMAP.md, "M5 declaration", before any run).

Targets per internal zone, month and period (on-peak = Mon-Fri except NERC holidays, HE08-HE23; off-peak = the rest):
average DA total LBMP and average DA congestion (-mcc). Vintage: one issue per month, cutoff = first day of the first
target month minus 7 days; target month M at horizon h has cutoff first(M - (h-1) months) - 7 days. Inputs: DA zonal
LBMP with delivery date < cutoff (warehouse, backfilled to 2015-01) and Henry Hub spot (last 10 trade days with trade
date <= cutoff - 7 days). Forecasts are made for every target month from 2016-01, so each model accumulates its own past
errors, which give its quantiles (total in logs, congestion in levels; per horizon and zone, pooled over zones while
fewer than MIN_ERR) and its mean (point corrected by the mean past error).

Models: baselines m5_persist / m5_lastyear / m5_norm; candidates m5_anchor (implied heat rate x gas, congestion norm)
and m5_decay (anchor + phi_h / psi_h times the last full month's deviation, phi/psi fit on earlier target months).
Stored like other runs: one fold per target month (rows for all six horizons), scored under market "da_month" so the
daily scoreboard ignores it; forecasts before the scored window are kept as the artifact "history".
"""
from __future__ import annotations

import time
from datetime import UTC, date

import duckdb
import numpy as np
import pandas as pd

from lmpsignal import registry
from lmpsignal.calendar import holiday_table
from lmpsignal.config import EMBARGO_DAYS, INTERNAL_ZONES, QUANTILES
from lmpsignal.evaluate import QCOLS, crps_rows
from nyiso.config import DB_PATH

HORIZONS = range(1, 7)
FIRST_TARGET = pd.Timestamp("2016-01-01")
WINDOWS = {"validation": (pd.Timestamp("2022-10-01"), pd.Timestamp("2025-10-01")),
           "holdout": (pd.Timestamp("2025-10-01"), pd.Timestamp("2026-10-01"))}
GAS_DAYS, GAS_LAG_DAYS, NORM_YEARS, MIN_ERR, MIN_COVERAGE = 10, 7, 5, 24, 0.95
BASELINES = ("m5_persist", "m5_lastyear", "m5_norm")
CANDIDATES = ("m5_anchor", "m5_decay")
MODELS = BASELINES + CANDIDATES
COMPONENTS = ("total", "congestion")


# ----------------------------------------------------------------------------- data

def actuals(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """month, zone, period ('peak'/'offpeak'), total, congestion: monthly averages over complete months only."""
    own = con is None
    con = con or duckdb.connect(str(DB_PATH), read_only=True)
    try:
        h = con.execute(f"""SELECT ts_local, zone, lbmp, -mcc AS congestion FROM da_lbmp_zone
                            WHERE zone IN ({', '.join(f"'{z}'" for z in INTERNAL_ZONES)})""").df()
    finally:
        if own:
            con.close()
    t = pd.to_datetime(h["ts_local"])
    hol = {d for d, _ in holiday_table(int(t.dt.year.min()), int(t.dt.year.max()))}
    day = t.dt.date
    peak = (t.dt.weekday < 5) & t.dt.hour.between(7, 22) & ~day.isin(hol)
    h = h.assign(month=t.dt.to_period("M").dt.to_timestamp(), period=np.where(peak, "peak", "offpeak"))
    m = h.groupby(["month", "zone", "period"]).agg(total=("lbmp", "mean"), congestion=("congestion", "mean"),
                                                   hours=("lbmp", "size")).reset_index()
    full = h.groupby(["month", "zone"]).size().rename("n").reset_index()
    full["expected"] = full["month"].dt.days_in_month * 24
    ok = full[full["n"] >= MIN_COVERAGE * full["expected"]][["month", "zone"]]
    return m.merge(ok, on=["month", "zone"]).drop(columns="hours")


def gas(con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    own = con is None
    con = con or duckdb.connect(str(DB_PATH), read_only=True)
    try:
        g = con.execute("SELECT trade_date, price_usd_mmbtu AS hh FROM gas_henry_hub ORDER BY trade_date").df()
    finally:
        if own:
            con.close()
    g["trade_date"] = pd.to_datetime(g["trade_date"])
    return g.dropna()


def cutoff(month: pd.Timestamp, h: int) -> pd.Timestamp:
    return (month - pd.DateOffset(months=h - 1)) - pd.Timedelta(days=EMBARGO_DAYS)


def gas_at(g: pd.DataFrame, cut: pd.Timestamp) -> float:
    v = g.loc[g["trade_date"] <= cut - pd.Timedelta(days=GAS_LAG_DAYS), "hh"].tail(GAS_DAYS)
    return float(v.mean()) if len(v) else np.nan


# ----------------------------------------------------------------------------- point forecasts

def _known(a: pd.DataFrame, cut: pd.Timestamp) -> pd.DataFrame:
    """Months fully delivered before the cutoff."""
    return a[a["month"] + pd.DateOffset(months=1) <= cut]


def _same_month(k: pd.DataFrame, month: pd.Timestamp, years: int | None = None, exclude: pd.Timestamp | None = None):
    s = k[(k["month"].dt.month == month.month) & (k["month"] < month)]
    if exclude is not None:
        s = s[s["month"] != exclude]
    if years is not None:
        s = s[s["month"] >= month - pd.DateOffset(years=years)]
    return s


def _anchor_parts(k: pd.DataFrame, month: pd.Timestamp, exclude: pd.Timestamp | None = None) -> pd.DataFrame:
    """zone, period -> ihr (median implied heat rate) and cnorm (median congestion), same calendar month, last 5 years."""
    s = _same_month(k, month, NORM_YEARS, exclude)
    return s.assign(ihr=s["total"] / s["hh_month"]).groupby(["zone", "period"]).agg(
        ihr=("ihr", "median"), cnorm=("congestion", "median"))


def point_forecasts(a: pd.DataFrame, g: pd.DataFrame, models=MODELS, last_target: pd.Timestamp | None = None) -> pd.DataFrame:
    """Point forecasts (total, congestion) for every target month from FIRST_TARGET, horizon and model. m5_decay's
    phi/psi are fit afterwards (decay_fit); here it carries the anchor and the deviation inputs."""
    hh_m = g.assign(month=g["trade_date"].dt.to_period("M").dt.to_timestamp()).groupby("month")["hh"].mean()
    a = a.assign(hh_month=a["month"].map(hh_m))
    last_target = last_target or a["month"].max()
    rows = []
    for month in pd.date_range(FIRST_TARGET, last_target, freq="MS"):
        for h in HORIZONS:
            cut = cutoff(month, h)
            k = _known(a, cut)
            if k.empty:
                continue
            last = k["month"].max()
            idx = pd.MultiIndex.from_product([INTERNAL_ZONES, ["peak", "offpeak"]], names=["zone", "period"])
            f = pd.DataFrame(index=idx)
            lastk = k[k["month"] == last].set_index(["zone", "period"])
            if "m5_persist" in models:
                f["m5_persist_total"], f["m5_persist_congestion"] = lastk["total"], lastk["congestion"]
            if "m5_lastyear" in models:
                ly = k[k["month"] == month - pd.DateOffset(years=1)].set_index(["zone", "period"])
                f["m5_lastyear_total"], f["m5_lastyear_congestion"] = ly["total"], ly["congestion"]
            if "m5_norm" in models:
                nm = _same_month(k, month).groupby(["zone", "period"])[["total", "congestion"]].mean()
                f["m5_norm_total"], f["m5_norm_congestion"] = nm["total"], nm["congestion"]
            if "m5_anchor" in models or "m5_decay" in models:
                gc = gas_at(g, cut)
                ap = _anchor_parts(k, month)
                f["m5_anchor_total"], f["m5_anchor_congestion"] = ap["ihr"] * gc, ap["cnorm"]
                lp = _anchor_parts(k, last, exclude=last)                  # the last month's own anchor, without it
                f["dev_total"] = np.log(lastk["total"] / (lp["ihr"] * lastk["hh_month"]))
                f["dev_congestion"] = lastk["congestion"] - lp["cnorm"]
                f["gas_cut"] = gc
            rows.append(f.reset_index().assign(month=month, h=h, cutoff=cut, last_month=last))
    return pd.concat(rows, ignore_index=True)


def decay_fit(pf: pd.DataFrame, a: pd.DataFrame) -> pd.DataFrame:
    """m5_decay: phi_h (log total) and psi_h (congestion) by least squares through the origin on earlier target months
    (fully known at the cutoff), clipped to [0, 1]; then the decay forecasts."""
    y = a.set_index(["month", "zone", "period"])[["total", "congestion"]]
    d = pf.join(y, on=["month", "zone", "period"])
    d["yt"] = np.log(d["total"] / d["m5_anchor_total"])
    d["yc"] = d["congestion"] - d["m5_anchor_congestion"]
    phi, psi = np.full(len(d), np.nan), np.full(len(d), np.nan)
    for _h, g in d.groupby("h"):
        for cut, rows in g.groupby("cutoff"):
            prior = g[(g["month"] + pd.DateOffset(months=1) <= cut)]
            pt = prior.dropna(subset=["yt", "dev_total"])
            pc = prior.dropna(subset=["yc", "dev_congestion"])
            ft = float(np.clip((pt["yt"] * pt["dev_total"]).sum() / (pt["dev_total"] ** 2).sum(), 0, 1)) if len(pt) else 0.0
            fc = float(np.clip((pc["yc"] * pc["dev_congestion"]).sum() / (pc["dev_congestion"] ** 2).sum(), 0, 1)) if len(pc) else 0.0
            phi[rows.index], psi[rows.index] = ft, fc
    pf = pf.copy()
    pf["phi"], pf["psi"] = phi, psi
    pf["m5_decay_total"] = pf["m5_anchor_total"] * np.exp(pf["phi"] * pf["dev_total"].fillna(0.0))
    pf["m5_decay_congestion"] = pf["m5_anchor_congestion"] + pf["psi"] * pf["dev_congestion"].fillna(0.0)
    return pf


# ----------------------------------------------------------------------------- distributions

def long_forecasts(pf: pd.DataFrame, a: pd.DataFrame, model: str) -> pd.DataFrame:
    """One model's rows (month, h, zone, period, component) with point, y, mean and quantiles from its past errors."""
    y = a.set_index(["month", "zone", "period"])[list(COMPONENTS)]
    base = ["month", "h", "cutoff", "zone", "period"]
    out = []
    for comp in COMPONENTS:
        d = pf[base + [f"{model}_{comp}"]].rename(columns={f"{model}_{comp}": "point"})
        d = d.join(y[comp].rename("y"), on=["month", "zone", "period"]).assign(component=comp)
        if comp == "total":
            d["err"] = np.log(d["y"] / d["point"])
        else:
            d["err"] = d["y"] - d["point"]
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    Q = np.full((len(d), len(QUANTILES)), np.nan)
    mean = np.full(len(d), np.nan)
    qs = np.asarray(QUANTILES)
    for (comp, _h), g in d.groupby(["component", "h"]):
        known = g.dropna(subset=["err", "point"])
        for cut, rows in g.groupby("cutoff"):
            prior = known[known["month"] + pd.DateOffset(months=1) <= cut]
            if prior.empty:
                continue
            for zone, r in rows.groupby("zone"):
                e = prior.loc[prior["zone"] == zone, "err"].to_numpy()
                if len(e) < MIN_ERR:
                    e = prior["err"].to_numpy()
                if len(e) < MIN_ERR:
                    continue
                eq = np.quantile(e, qs)
                p = r["point"].to_numpy()[:, None]
                if comp == "total":
                    Q[r.index] = p * np.exp(eq)[None, :]
                    mean[r.index] = r["point"].to_numpy() * np.mean(np.exp(e))
                else:
                    Q[r.index] = p + eq[None, :]
                    mean[r.index] = r["point"].to_numpy() + e.mean()
    d[QCOLS] = Q
    d["mean"] = mean
    return d.drop(columns="err")


def score(d: pd.DataFrame) -> pd.DataFrame:
    s = d.dropna(subset=["y", "mean", *QCOLS]).copy()
    s["crps"] = crps_rows(s["y"].to_numpy(), s[QCOLS].to_numpy())
    s["se"] = (s["mean"] - s["y"]) ** 2
    s["in90"] = (s["y"] >= s["q05"]) & (s["y"] <= s["q95"])
    return s


def _scores_table(s: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for comp, g in s.groupby("component"):
        for zone, z in [*g.groupby("zone"), ("ALL", g)]:
            rows.append({"market": "da_month", "component": comp, "zone": str(zone), "n": float(len(z)),
                         "crps": z["crps"].mean(), "rmse": float(np.sqrt(z["se"].mean())),
                         "mae": float((z["mean"] - z["y"]).abs().mean()), "cov90": float(z["in90"].mean())})
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------- runs

def compute(models=MODELS) -> tuple[pd.DataFrame, pd.DataFrame]:
    a, g = actuals(), gas()
    pf = point_forecasts(a, g, models)
    if "m5_decay" in models:
        pf = decay_fit(pf, a)
    return pf, a


def run(model: str, window: str = "validation", log: bool = True, cache=None) -> str | None:
    if model not in MODELS:
        raise ValueError(f"{model} is not a declared M5 model: {MODELS}")
    t0 = time.time()
    pf, a = cache or compute()
    d = long_forecasts(pf, a, model)
    lo, hi = WINDOWS[window]
    scored = score(d[(d["month"] >= lo) & (d["month"] < hi)])
    name = model if window == "validation" else f"{model}_{window}"
    cfg = {"milestone": "M5", "window": window, "horizons": list(HORIZONS), "first_target": str(FIRST_TARGET.date()),
           "gas_days": GAS_DAYS, "gas_lag_days": GAS_LAG_DAYS, "norm_years": NORM_YEARS, "min_err": MIN_ERR,
           "targets": "DA total and congestion, monthly on/off-peak averages, internal zones"}
    run_id = registry.start_run(name, cfg, len(pf)) if log else None
    try:
        for month, g in scored.groupby("month"):
            if log:
                registry.save_fold(run_id, f"{month:%Y-%m}", g.drop(columns=["in90"]), _scores_table(g))
        if log:
            hist = d[d["month"] < lo].copy()
            hist[["month", "cutoff"]] = hist[["month", "cutoff"]].astype(str)
            registry.save_artifact(run_id, "all", "history", hist)
            if model == "m5_decay":
                registry.save_artifact(run_id, "all", "decay", pf[["month", "h", "cutoff", "phi", "psi"]]
                                       .drop_duplicates().astype({"month": str, "cutoff": str}))
            registry.finish_run(run_id)
    except Exception as e:
        if log:
            registry.finish_run(run_id, "failed", f"{type(e).__name__}: {e}"[:2000])
        raise
    s = _scores_table(scored)
    for _, r in s[s["zone"] == "ALL"].iterrows():
        print(f"  {name:<22} {r.component:<10} CRPS {r.crps:7.3f}  RMSE {r.rmse:7.3f}  cov90 {r.cov90:.2f}  n {int(r.n)}")
    print(f"  {name} -> {run_id or '(not logged)'} in {time.time() - t0:.0f}s")
    return run_id


# ----------------------------------------------------------------------------- live

LIVE_SCHEMA = f"""CREATE TABLE IF NOT EXISTS live_monthly (
    model VARCHAR, cutoff DATE, month DATE, h INTEGER, zone VARCHAR, period VARCHAR, component VARCHAR,
    point DOUBLE, mean DOUBLE, {", ".join(f"{q} DOUBLE" for q in QCOLS)}, git_commit VARCHAR, created_utc TIMESTAMPTZ)"""


def latest_vintage(today: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(cutoff, first target month) of the most recent monthly issue on or before `today`."""
    m1 = pd.Timestamp(today).to_period("M").to_timestamp() + pd.DateOffset(months=1)
    if cutoff(m1, 1) > pd.Timestamp(today):
        m1 -= pd.DateOffset(months=1)
    return cutoff(m1, 1), m1


def live(today: date, choice: dict[str, str]) -> pd.DataFrame:
    """Monthly forecasts of the latest vintage for the six target months, one model per component (`choice`)."""
    from datetime import datetime

    cut, m1 = latest_vintage(today)
    last = m1 + pd.DateOffset(months=5)
    a, g = actuals(), gas()
    a = a[a["month"] + pd.DateOffset(months=1) <= cut]                   # nothing after the cutoff
    models = tuple(sorted(set(choice.values())))
    pf = point_forecasts(a, g, models, last_target=last)
    if "m5_decay" in models:
        pf = decay_fit(pf, a)
    out = []
    for comp, model in choice.items():
        d = long_forecasts(pf, a, model)
        d = d[(d["component"] == comp) & (d["cutoff"] == cut) & (d["month"] >= m1)]
        out.append(d.assign(model=model))
    out = pd.concat(out, ignore_index=True)
    out = out[["model", "cutoff", "month", "h", "zone", "period", "component", "point", "mean", *QCOLS]].copy()
    out["git_commit"] = registry.git_commit()
    out["created_utc"] = datetime.now(UTC)
    out["cutoff"], out["month"] = out["cutoff"].dt.date, out["month"].dt.date
    with registry.connect() as con:
        con.execute(LIVE_SCHEMA)
        con.execute("DELETE FROM live_monthly WHERE cutoff = ?", [cut.date()])
        con.register("o", out)
        con.execute(f"INSERT INTO live_monthly SELECT model, cutoff, month, h, zone, period, component, point, mean, "
                    f"{', '.join(QCOLS)}, git_commit, created_utc FROM o")
    return out
