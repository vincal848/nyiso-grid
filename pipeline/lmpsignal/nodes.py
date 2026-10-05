"""Node-level forecasts from the signal's zone forecasts (end-to-end layer; the signal itself is not refit).

In NYISO the energy component of LBMP is the same at every bus; nodes differ by losses and congestion. So a node's
forecast is the signal's energy forecast for its zone plus its own loss and congestion mapped from the zone's:
    loss_node = a_l + b_l * loss_zone,   congestion_node = a_c + b_c * congestion_zone      (congestion = -MCC)
with (a, b) from OLS of the node's hourly series on its zone's, per market, over the 365 days ending 7 days before
the forecast month (the validation refit rule). Nodes with fewer than MIN_OBS hours in the window fall back to the
zone forecast (a = 0, b = 1). Point forecasts only in v1 (no node quantiles).

Configuration declared once (2026-10-05) and scored once on the validation folds (`lmp nodes --evaluate`), not
tuned. Known limit: a zone-level congestion forecast cannot express congestion that moves nodes within a zone in
opposite directions; the structural model's node shift factors are the route to that (docs/RESEARCH_LOG.md).
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

from nyiso.config import DB_PATH
from lmpsignal import cv, registry
from lmpsignal.config import EXPERIMENTS_DIR

WINDOW_DAYS = 365
MIN_OBS = 1000
NODE_VIEW = {"da": "da_lbmp_node", "rt": "rt_lbmp_node_hourly"}
LIVE_SCHEMA = """CREATE TABLE IF NOT EXISTS live_node_forecasts (signal VARCHAR, delivery_date DATE, ts_utc TIMESTAMPTZ,
    ptid BIGINT, zone VARCHAR, market VARCHAR, energy DOUBLE, loss DOUBLE, congestion DOUBLE, total DOUBLE,
    created_utc TIMESTAMPTZ)"""


def _wh() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    return con


def betas(market: str, train_end: date, con: duckdb.DuckDBPyConnection | None = None) -> pd.DataFrame:
    """Per priced node: zone, and (a, b, n) for loss and congestion, from the WINDOW_DAYS before train_end."""
    own = con is None
    con = con or _wh()
    lo = train_end - timedelta(days=WINDOW_DAYS)
    df = con.execute(f"""
        SELECT n.ptid, nd.zone,
               regr_intercept(n.mlc, z.{market}_mlc) AS a_loss, regr_slope(n.mlc, z.{market}_mlc) AS b_loss,
               regr_intercept(-n.mcc, -z.{market}_mcc) AS a_cong, regr_slope(-n.mcc, -z.{market}_mcc) AS b_cong,
               regr_count(n.mlc, z.{market}_mlc) AS n_obs
        FROM {NODE_VIEW[market]} n
        JOIN nodes nd ON nd.ptid = n.ptid
        JOIN lbmp_zone_hourly z ON z.zone = nd.zone AND z.ts_utc = n.ts_utc
        WHERE n.ts_local >= ? AND n.ts_local < ?
        GROUP BY ALL""", [str(lo), str(train_end)]).df()
    if own:
        con.close()
    weak = df["n_obs"] < MIN_OBS
    df.loc[weak, ["a_loss", "a_cong"]] = 0.0
    df.loc[weak, ["b_loss", "b_cong"]] = 1.0
    return df.fillna({"a_loss": 0.0, "a_cong": 0.0, "b_loss": 1.0, "b_cong": 1.0})


def node_forecast(zone_fc: pd.DataFrame, b: pd.DataFrame, market: str) -> pd.DataFrame:
    """zone_fc: rows (delivery_date, ts_utc, zone, market, component, mean) -> node rows with components and total."""
    z = zone_fc[zone_fc["market"] == market].pivot_table(index=["delivery_date", "ts_utc", "zone"], columns="component",
                                                         values="mean").reset_index()
    out = z.merge(b, on="zone", how="inner")
    out["loss"] = out["a_loss"] + out["b_loss"] * out["loss"]
    out["congestion"] = out["a_cong"] + out["b_cong"] * out["congestion"]
    out["total"] = out["energy"] + out["loss"] + out["congestion"]
    out["market"] = market
    return out[["delivery_date", "ts_utc", "ptid", "zone", "market", "energy", "loss", "congestion", "total"]]


# ----------------------------------------------------------------------------- one-off validation score

def evaluate(run_id: str, folds: list[cv.Fold] | None = None) -> pd.DataFrame:
    """Score node forecasts built from a stored zone-forecast run against actual node prices, with two
    benchmarks: the zone forecast used as-is at every node, and the node's own DA price of D-1 (same hour)."""
    folds = folds or cv.folds()
    con = _wh()
    path = (EXPERIMENTS_DIR / run_id).as_posix()
    acc = []
    for f in folds:
        zf = duckdb.sql(f"""SELECT delivery_date, ts_utc, zone, market, component, mean
                            FROM read_parquet('{path}/fold={f.name}.parquet')""").df()
        for m in ("da", "rt"):
            b = betas(m, f.train_end, con)
            nf = node_forecast(zf, b, m)
            plain = node_forecast(zf, b.assign(a_loss=0.0, a_cong=0.0, b_loss=1.0, b_cong=1.0), m)
            act = con.execute(f"""
                SELECT n.ts_utc, n.ptid, n.lbmp AS y, d1.lbmp AS persist
                FROM {NODE_VIEW[m]} n
                LEFT JOIN da_lbmp_node d1 ON d1.ptid = n.ptid AND d1.ts_utc = n.ts_utc - INTERVAL 1 DAY
                WHERE n.ts_local >= ? AND n.ts_local < ?""", [str(f.test_start), str(f.test_end)]).df()
            j = (nf[["ts_utc", "ptid", "zone", "total"]].merge(plain[["ts_utc", "ptid", "total"]], on=["ts_utc", "ptid"],
                                                               suffixes=("", "_zone"))
                 .merge(act, on=["ts_utc", "ptid"]).dropna(subset=["y", "total", "total_zone", "persist"]))
            for col, name in (("total", "node_map"), ("total_zone", "zone_as_node"), ("persist", "persist_da_d1")):
                e = j[col] - j["y"]
                acc.append({"fold": f.name, "market": m, "model": name, "n": len(j),
                            "sae": float(np.abs(e).sum()), "sse": float((e ** 2).sum())})
    con.close()
    a = pd.DataFrame(acc).groupby(["market", "model"])[["n", "sae", "sse"]].sum().reset_index()
    a["mae"] = a["sae"] / a["n"]
    a["rmse"] = np.sqrt(a["sse"] / a["n"])
    return a[["market", "model", "n", "mae", "rmse"]]


# ----------------------------------------------------------------------------- live

def live(d: date, signal: str) -> pd.DataFrame:
    from datetime import datetime, timezone

    from lmpsignal.live import month_fold

    with registry.connect(read_only=True) as con:
        zf = con.execute("""SELECT delivery_date, ts_utc, zone, market, component, mean FROM live_forecasts
                            WHERE signal = ? AND delivery_date = ?""", [signal, d]).df()
    if zf.empty:
        raise ValueError(f"no live forecast for {d}: run `lmp forecast --date {d}` first")
    wh = _wh()
    out = pd.concat([node_forecast(zf, betas(m, month_fold(d).train_end, wh), m) for m in ("da", "rt")], ignore_index=True)
    wh.close()
    out.insert(0, "signal", signal)
    out["created_utc"] = datetime.now(timezone.utc)
    with registry.connect() as con:
        con.execute(LIVE_SCHEMA)
        con.execute("DELETE FROM live_node_forecasts WHERE signal = ? AND delivery_date = ?", [signal, d])
        con.register("o", out)
        con.execute("INSERT INTO live_node_forecasts SELECT signal, delivery_date, ts_utc, ptid, zone, market, energy, "
                    "loss, congestion, total, created_utc FROM o")
    return out
