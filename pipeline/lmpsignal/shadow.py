"""M8: live-only shadow members (declared in docs/ROADMAP.md, "M8 declaration").

Chronos-2 (amazon/chronos-2), zero-shot. Per location and market the target is hourly total price on the UTC hour
grid; context = the 28 days known at the 05:00 ET D-1 issue (DA through D-1, RT through the hour ending 04:00 ET,
one hour before the issue); covariates = zone load forecast and temperature forecast from the panel (past and future rows).
Forecasts go to experiments.duckdb `live_shadow`; they never feed signal v1. No validation-period forecasts are made:
the model's pretraining overlaps those years, so only the live record is a clean test. Needs the `deep` extra.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import duckdb
import numpy as np
import pandas as pd

from lmpsignal import panel, registry
from lmpsignal.config import FEATURES_DB, LOCATIONS, QUANTILES
from lmpsignal.evaluate import QCOLS, crps_rows
from lmpsignal.live import issue_utc

MODEL_ID, NAME = "amazon/chronos-2", "chronos2"
CONTEXT_DAYS = 28
COVARIATES = ["load_fcst_zone", "temp_fcst_zone"]
MEAN_Q = [c for c, q in zip(QCOLS, QUANTILES) if 0.05 <= q <= 0.95]
SCHEMA = f"""CREATE TABLE IF NOT EXISTS live_shadow (
    model VARCHAR, issue_utc TIMESTAMPTZ, delivery_date DATE, ts_utc TIMESTAMPTZ, zone VARCHAR, hour_local INTEGER,
    market VARCHAR, mean DOUBLE, {", ".join(f"{q} DOUBLE" for q in QCOLS)}, git_commit VARCHAR, created_utc TIMESTAMPTZ)"""

_pipe = None


def _pipeline():
    global _pipe
    if _pipe is None:
        import torch
        from chronos import Chronos2Pipeline

        _pipe = Chronos2Pipeline.from_pretrained(MODEL_ID, device_map="cuda" if torch.cuda.is_available() else "cpu")
    return _pipe


def frames(p: pd.DataFrame, d: date, market: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Context (id, timestamp, target, covariates), future covariates, and D's rows (for mapping back)."""
    iss = issue_utc(d)
    day = p[p["delivery_date"] == pd.Timestamp(d)]
    d_start, d_end = day["ts_utc"].min(), day["ts_utc"].max()
    # first hour NOT in the context; RT conservatively stops at the hour ending 04:00 ET (the 04-05 hour may be unpublished)
    ctx_end = d_start if market == "da" else iss.floor("h") - pd.Timedelta(hours=1)
    grid_ctx = pd.date_range(ctx_end - pd.Timedelta(days=CONTEXT_DAYS), ctx_end, freq="h", inclusive="left")
    grid_fut = pd.date_range(ctx_end, d_end, freq="h")
    src = p.set_index(["zone", "ts_utc"])
    ctx, fut = [], []
    for z in LOCATIONS:
        s = src.xs(z, level="zone") if z in src.index.get_level_values("zone") else pd.DataFrame()
        if s.empty:
            continue
        s = s[~s.index.duplicated()]
        c = s.reindex(grid_ctx)
        ctx.append(pd.DataFrame({"id": z, "timestamp": grid_ctx.tz_localize(None), "target": c[f"{market}_total"].to_numpy(),
                                 **{v: c[v].to_numpy() for v in COVARIATES}}))
        f = s.reindex(grid_fut)
        fut.append(pd.DataFrame({"id": z, "timestamp": grid_fut.tz_localize(None), **{v: f[v].to_numpy() for v in COVARIATES}}))
    return pd.concat(ctx, ignore_index=True), pd.concat(fut, ignore_index=True), day


def forecast(d: date) -> pd.DataFrame:
    p = panel.load(start=d - timedelta(days=CONTEXT_DAYS + 3), end=d + timedelta(days=1))
    if p[p["delivery_date"] == pd.Timestamp(d)].empty:
        raise ValueError(f"panel has no rows for {d}: run `lmp panel --through {d}` first")
    pipe = _pipeline()
    out = []
    for m in ("da", "rt"):
        ctx, fut, day = frames(p, d, m)
        n = fut.groupby("id").size().iloc[0]
        pr = pipe.predict_df(ctx, future_df=fut, id_column="id", timestamp_column="timestamp", target="target",
                             prediction_length=int(n), quantile_levels=list(QUANTILES))
        qcols = {str(q): c for q, c in zip(QUANTILES, QCOLS)}
        pr = pr.rename(columns={**qcols, "id": "zone"})
        pr["ts_utc"] = pd.to_datetime(pr["timestamp"]).dt.tz_localize("UTC")
        pr[QCOLS] = np.sort(pr[QCOLS].to_numpy(), axis=1)
        pr["mean"] = pr[MEAN_Q].mean(axis=1)
        keep = day[["delivery_date", "ts_utc", "zone", "hour_local"]].merge(pr[["zone", "ts_utc", "mean", *QCOLS]],
                                                                           on=["zone", "ts_utc"], how="inner")
        out.append(keep.assign(market=m))
    o = pd.concat(out, ignore_index=True)
    o.insert(0, "issue_utc", issue_utc(d))
    o.insert(0, "model", NAME)
    o["git_commit"] = registry.git_commit()
    o["created_utc"] = datetime.now(UTC)
    o["delivery_date"] = o["delivery_date"].dt.date
    with registry.connect() as con:
        con.execute(SCHEMA)
        con.execute("DELETE FROM live_shadow WHERE model = ? AND delivery_date = ?", [NAME, d])
        con.register("o", o)
        con.execute(f"INSERT INTO live_shadow SELECT model, issue_utc, delivery_date, ts_utc, zone, hour_local, market, "
                    f"mean, {', '.join(QCOLS)}, git_commit, created_utc FROM o")
    return o


def score(signal: str = "combo3_eq_aci") -> pd.DataFrame:
    """Settled live days: CRPS, RMSE and 90% coverage of the shadow member vs signal v1 on the same rows."""
    with registry.connect(read_only=True) as con:
        if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'live_shadow'").fetchone()[0]:
            return pd.DataFrame()
        sh = con.execute(f"SELECT delivery_date, ts_utc, zone, market, mean, {', '.join(QCOLS)} FROM live_shadow "
                         "WHERE model = ?", [NAME]).df()
        v1 = con.execute(f"SELECT ts_utc, zone, market, mean, {', '.join(QCOLS)} FROM live_forecasts "
                         "WHERE signal = ? AND component = 'total'", [signal]).df()
    pc = duckdb.connect(str(FEATURES_DB), read_only=True)
    y = pc.execute("SELECT ts_utc, zone, da_total, rt_total FROM panel WHERE delivery_date >= ?",
                   [sh["delivery_date"].min()]).df() if len(sh) else pd.DataFrame()
    pc.close()
    if sh.empty or y.empty:
        return pd.DataFrame()
    y = y.melt(id_vars=["ts_utc", "zone"], var_name="market", value_name="y").dropna()
    y["market"] = y["market"].str.replace("_total", "")
    rows = []
    for name, f in ((NAME, sh), (signal, v1)):
        j = f.merge(y, on=["ts_utc", "zone", "market"]).merge(sh[["ts_utc", "zone", "market"]], on=["ts_utc", "zone", "market"])
        j["crps"] = crps_rows(j["y"].to_numpy(), j[QCOLS].to_numpy())
        for m, g in j.groupby("market"):
            rows.append({"model": name, "market": m, "days": g["ts_utc"].dt.date.nunique(), "n": len(g),
                         "crps": g["crps"].mean(), "rmse": float(np.sqrt(((g["mean"] - g["y"]) ** 2).mean())),
                         "cov90": float(((g["y"] >= g["q05"]) & (g["y"] <= g["q95"])).mean())})
    return pd.DataFrame(rows).sort_values(["market", "model"]) if rows else pd.DataFrame()
