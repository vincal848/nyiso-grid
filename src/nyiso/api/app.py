"""Read-only FastAPI over the DuckDB catalog. Serves the static dashboard from web/."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nyiso.config import DATA, DB_PATH, EXTERNAL_ZONES, FUELS, REF, TZ, WEB
from nyiso.store.timeweight import twa_sql
from nyiso.store.writer import partition_path

app = FastAPI(title="NYISO Grid")
_tz = ZoneInfo(TZ)


@app.middleware("http")
async def no_cache_static(request, call_next):
    # local dev tool: always serve the current web/ files
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@lru_cache(maxsize=1)
def _con() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        raise RuntimeError("data/nyiso.duckdb not found — run `nyiso build` first")
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    return con


def q(sql: str, params: list | None = None) -> list[dict]:
    cur = _con().cursor()
    cur.execute("SET TimeZone = 'UTC'")
    res = cur.execute(sql, params or [])
    cols = [d[0] for d in res.description]
    return [dict(zip(cols, row)) for row in res.fetchall()]


def _clean(v):
    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 2)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v


def js(obj) -> JSONResponse:
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        return _clean(o)
    return JSONResponse(walk(obj))


def day_bounds(d: date) -> tuple[datetime, datetime]:
    """Local calendar day -> [start, end) in UTC (naive, matching DuckDB TIMESTAMPTZ in UTC session)."""
    s = datetime.combine(d, time(0), _tz).astimezone(ZoneInfo("UTC"))
    e = datetime.combine(d + timedelta(days=1), time(0), _tz).astimezone(ZoneInfo("UTC"))
    return s, e


def parse_day(s: str | None) -> date:
    if s:
        return date.fromisoformat(s)
    return date.fromisoformat(str(meta_dates()["max"]))


@lru_cache(maxsize=1)
def meta_dates() -> dict:
    row = q("SELECT min(day) AS min, max(day) AS max FROM daily_summary WHERE avg_load_mw IS NOT NULL")[0]
    return row


# ------------------------------------------------------------------ API

@app.get("/api/meta")
def meta():
    d = meta_dates()
    cov = []
    cov_path = DATA / "coverage.parquet"
    if cov_path.exists():
        cov = q(f"""SELECT dataset, count(*) AS days, avg(coverage) AS coverage,
                          count(*) FILTER (WHERE coverage < 0.99) AS bad_days
                   FROM '{cov_path.as_posix()}' GROUP BY 1 ORDER BY 1""")
    return js({"min_date": d["min"], "max_date": d["max"], "fuels": FUELS, "coverage": cov})


@app.get("/api/summary")
def summary(date_: str | None = Query(None, alias="date")):
    d = parse_day(date_)
    s, e = day_bounds(d)
    series = q("""SELECT ts_utc, ts_local, load_mw, net_load_mw, rt_lbmp FROM system_5m
                  WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc""", [s, e])
    daily = q("SELECT * FROM daily_summary WHERE day = ?", [d])
    return js({"date": d, "daily": daily[0] if daily else None, "series": series})


@app.get("/api/fuelmix")
def fuelmix(date_: str | None = Query(None, alias="date")):
    d = parse_day(date_)
    s, e = day_bounds(d)
    rows = q("""SELECT ts_utc, fuel, gen_mw FROM fuel_mix_5m
                WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc""", [s, e])
    btm = q("""SELECT ts_utc, mw FROM btm_solar WHERE zone = 'SYSTEM'
               AND ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc""", [s, e])
    times = sorted({r["ts_utc"] for r in rows})
    idx = {t: i for i, t in enumerate(times)}
    series = {f: [None] * len(times) for f in FUELS}
    for r in rows:
        series.setdefault(r["fuel"], [None] * len(times))[idx[r["ts_utc"]]] = r["gen_mw"]
    # BTM solar is hourly: hold each hourly value across its 5-min intervals
    btm_by_hour = {b["ts_utc"].replace(minute=0, second=0): b["mw"] for b in btm}
    series["BTM Solar"] = [btm_by_hour.get(t.replace(minute=0, second=0)) for t in times]
    return js({"date": d, "times": times, "series": series})


@app.get("/api/prices/zones")
def prices_zones(date_: str | None = Query(None, alias="date")):
    d = parse_day(date_)
    s, e = day_bounds(d)
    hourly = q("""SELECT ts_utc, zone, da_lbmp, rt_lbmp, da_rt_spread, da_mcc, rt_mcc
                  FROM lbmp_zone_hourly WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc, zone""", [s, e])
    rt5 = q("""SELECT ts_utc, zone, lbmp FROM rt_lbmp_zone_5m
               WHERE ts_utc >= ? AND ts_utc < ? ORDER BY 1, 2""", [s, e])
    return js({"date": d, "hourly": hourly, "rt5": rt5, "external": EXTERNAL_ZONES})


@app.get("/api/prices/nodes")
def prices_nodes(date_: str | None = Query(None, alias="date"), market: str = "rt5"):
    """Dense matrix for the map scrubber: times x nodes."""
    d = parse_day(date_)
    s, e = day_bounds(d)
    # Read the day's monthly partition directly (much faster than the all-history view).
    part = lambda key: partition_path(key, d.year, d.month).as_posix()  # noqa: E731
    # 5-min nodal RT: time-weighted onto the 5-min grid; 15-min lookback so the first
    # interval of the day knows its true start.
    rt5_twa = twa_sql("'{src}'", "ptid", ["lbmp"],
                      where="WHERE ts_utc >= ?::TIMESTAMPTZ - INTERVAL 15 MINUTE AND ts_utc < ?")
    sources = {
        "rt5": ("rt_lbmp_node", f"SELECT ts_utc AS t, ptid, lbmp AS v FROM ({rt5_twa}) WHERE ts_utc >= ? AND ts_utc < ?",
                2),
        "rt": ("rt_lbmp_node_hourly", "SELECT ts_utc AS t, ptid, lbmp AS v FROM '{src}' WHERE ts_utc >= ? AND ts_utc < ?", 1),
        "da": ("da_lbmp_node", "SELECT ts_utc AS t, ptid, lbmp AS v FROM '{src}' WHERE ts_utc >= ? AND ts_utc < ?", 1),
    }
    if market not in sources:
        raise HTTPException(400, f"market must be one of {list(sources)}")

    def fetch(m: str) -> list:
        key, sql, n_windows = sources[m]
        if not partition_path(key, d.year, d.month).exists():
            return []
        cur = _con().cursor()
        cur.execute("SET TimeZone = 'UTC'")
        return cur.execute(sql.replace("{src}", part(key)), [s, e] * n_windows).fetchall()

    used = market
    rows = fetch(market)
    if not rows and market == "rt5":  # NYISO gap in 5-min nodal archive -> hourly integrated RT
        used = "rt"
        rows = fetch("rt")
    times = sorted({r[0] for r in rows})
    ptids = sorted({int(r[1]) for r in rows})
    ti = {t: i for i, t in enumerate(times)}
    pi = {p: i for i, p in enumerate(ptids)}
    matrix = [[None] * len(ptids) for _ in times]
    for t, p, v in rows:
        matrix[ti[t]][pi[int(p)]] = None if v is None or math.isnan(v) else round(v, 2)
    return JSONResponse({"date": d.isoformat(), "market": used, "requested": market,
                         "times": [t.isoformat() for t in times], "ptids": ptids, "values": matrix})


@app.get("/api/constraints")
def constraints(date_: str | None = Query(None, alias="date")):
    d = parse_day(date_)
    s, e = day_bounds(d)
    rows = q("""SELECT market, facility, contingency, intervals, hours_binding, sum_cost, max_abs_cost, avg_cost
                FROM constraints_daily WHERE day = ? ORDER BY abs(sum_cost) DESC""", [d])
    flows = q("""SELECT ts_utc, interface, flow_mw, pos_limit_mw, neg_limit_mw FROM interface_flows_hourly
                 WHERE ts_utc >= ? AND ts_utc < ? ORDER BY interface, ts_utc""", [s, e])
    return js({"date": d, "constraints": rows, "flows": flows})


@app.get("/api/trends")
def trends(start: str | None = None, end: str | None = None):
    m = meta_dates()
    end_d = date.fromisoformat(end) if end else m["max"]
    start_d = date.fromisoformat(start) if start else end_d - timedelta(days=365)
    daily = q("SELECT * FROM daily_summary WHERE day BETWEEN ? AND ? ORDER BY day", [start_d, end_d])
    fuel = q("SELECT day, fuel, avg_mw FROM fuel_mix_daily WHERE day BETWEEN ? AND ? ORDER BY day",
             [start_d, end_d])
    zones = q("""SELECT day, zone, avg_da_lbmp, avg_rt_lbmp FROM lbmp_zone_daily
                 WHERE day BETWEEN ? AND ? ORDER BY day""", [start_d, end_d])
    return js({"start": start_d, "end": end_d, "daily": daily, "fuel": fuel, "zones": zones})


@app.get("/api/geo/zones")
def geo_zones():
    return JSONResponse(json.loads((REF / "zones.geojson").read_text()))


@app.get("/api/geo/nodes")
def geo_nodes():
    rows = q("""SELECT ptid, name, zone, subzone, lat, lon FROM nodes
                WHERE lat IS NOT NULL AND lon IS NOT NULL AND has_prices""")
    return js(rows)


# ------------------------------------------------------------------ forecasting signal (read-only data files)
# The pipeline (pipeline/lmpsignal) writes data/structure.duckdb, data/experiments.duckdb and
# data/experiments/<run>/*.parquet. The API reads those files directly and never imports pipeline code,
# so the ingest -> store -> api -> web layering is unchanged.

STRUCTURE_DB = DATA / "structure.duckdb"
EXPERIMENTS_DB = DATA / "experiments.duckdb"
QCOLS = ["q01", "q05", "q10", "q15", "q20", "q25", "q30", "q35", "q40", "q45", "q50", "q55", "q60", "q65", "q70",
         "q75", "q80", "q85", "q90", "q95", "q99"]


def _sq(sql: str, params: list | None = None) -> list[dict]:
    if not STRUCTURE_DB.exists():
        raise HTTPException(404, "data/structure.duckdb not built yet (run `lmp graphs`)")
    con = duckdb.connect(str(STRUCTURE_DB), read_only=True)
    try:
        res = con.execute(sql, params or [])
        cols = [d[0] for d in res.description]
        return [dict(zip(cols, r)) for r in res.fetchall()]
    finally:
        con.close()


def _fold(market: str, fold: str | None) -> str:
    if fold and fold != "latest":
        return fold
    return _sq("SELECT max(fold) AS f FROM constraint_catalog WHERE market = ?", [market])[0]["f"]


@app.get("/api/signal/folds")
def signal_folds():
    rows = _sq("SELECT DISTINCT fold FROM constraint_catalog ORDER BY fold")
    src = _sq("SELECT run_id, built_utc FROM source")
    return js({"folds": [r["fold"] for r in rows], "source": src[0] if src else None})


@app.get("/api/signal/constraints")
def signal_constraints(market: str = "da", fold: str | None = None):
    f = _fold(market, fold)
    rows = _sq("""SELECT c.rank, c.key, c.sum_abs_shadow, c.bind_rate,
                         (SELECT arg_max(zone, abs(a)) FROM zone_shift_factors z
                           WHERE z.fold = c.fold AND z.market = c.market AND z.key = c.key) AS most_sensitive_zone
                  FROM constraint_catalog c WHERE c.market = ? AND c.fold = ? ORDER BY c.rank""", [market, f])
    return js({"fold": f, "market": market, "constraints": rows})


@app.get("/api/signal/node_factors")
def signal_node_factors(key: str, market: str = "da", fold: str | None = None):
    f = _fold(market, fold)
    nodes = _sq("""SELECT n.ptid, m.name, m.zone, m.lat, m.lon, n.a, fit.r2_in_window
                   FROM node_shift_factors n JOIN node_meta m USING (ptid)
                   LEFT JOIN node_fit fit ON fit.ptid = n.ptid AND fit.market = n.market AND fit.fold = n.fold
                   WHERE n.market = ? AND n.fold = ? AND n.key = ? AND m.lat IS NOT NULL""", [market, f, key])
    zones = _sq("SELECT zone, a FROM zone_shift_factors WHERE market = ? AND fold = ? AND key = ?", [market, f, key])
    return js({"fold": f, "market": market, "key": key, "nodes": nodes, "zones": zones})


@app.get("/api/signal/cobinding")
def signal_cobinding(market: str = "da", fold: str | None = None, top: int = 80):
    f = _fold(market, fold)
    edges = _sq("""SELECT key_a, key_b, hours_both, jaccard FROM cobinding WHERE market = ? AND fold = ?
                   ORDER BY jaccard DESC LIMIT ?""", [market, f, top])
    nodes = _sq("SELECT key, rank, bind_rate FROM constraint_catalog WHERE market = ? AND fold = ?", [market, f])
    return js({"fold": f, "edges": edges, "nodes": nodes})


@app.get("/api/signal/drift")
def signal_drift():
    return js(_sq("SELECT * FROM drift ORDER BY market, fold"))


@app.get("/api/signal/models")
def signal_models():
    if not EXPERIMENTS_DB.exists():
        return js([])
    con = duckdb.connect(str(EXPERIMENTS_DB), read_only=True)
    try:
        rows = con.execute("""SELECT model, arg_max(run_id, created_utc) AS run_id FROM runs
                              WHERE status = 'done' GROUP BY model ORDER BY model""").fetchall()
    finally:
        con.close()
    return js([{"model": m, "run_id": r} for m, r in rows])


@app.get("/api/signal/forecast")
def signal_forecast(run_id: str, zone: str, date_: str = Query(..., alias="date"), market: str = "da",
                    component: str = "total"):
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(400, "bad run id")
    path = DATA / "experiments" / run_id
    if not path.exists():
        raise HTTPException(404, "unknown run")
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    res = con.execute(f"""SELECT ts_utc, hour_local, y, mean, {', '.join(QCOLS)}
                          FROM read_parquet('{path.as_posix()}/fold=*.parquet')
                          WHERE zone = ? AND market = ? AND component = ? AND CAST(delivery_date AS DATE) = ?
                          ORDER BY ts_utc""", [zone, market, component, date_])
    cols = [d[0] for d in res.description]
    rows = [dict(zip(cols, r)) for r in res.fetchall()]
    return js({"run_id": run_id, "zone": zone, "market": market, "component": component, "date": date_, "rows": rows})


# ------------------------------------------------------------------ live signal (lmp forecast / lmp nodes)

def _lq(sql: str, params: list | None = None, table: str = "live_forecasts") -> list[dict]:
    """Read-only query over experiments.duckdb (live tables) with the warehouse attached as `wh`; [] if `table` is absent."""
    if not EXPERIMENTS_DB.exists():
        return []
    con = duckdb.connect(str(EXPERIMENTS_DB), read_only=True)
    try:
        con.execute("SET TimeZone = 'UTC'")
        if not con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = ?", [table]).fetchone()[0]:
            return []
        con.execute(f"ATTACH '{DB_PATH.as_posix()}' AS wh (READ_ONLY)")
        res = con.execute(sql, params or [])
        cols = [d[0] for d in res.description]
        return [dict(zip(cols, r)) for r in res.fetchall()]
    finally:
        con.close()


@app.get("/api/live/dates")
def live_dates():
    rows = _lq("SELECT DISTINCT delivery_date, signal, max(created_utc) AS created FROM live_forecasts "
               "GROUP BY ALL ORDER BY delivery_date DESC")
    return js(rows)


@app.get("/api/live/forecast")
def live_forecast(zone: str = "N.Y.C.", date_: str | None = Query(None, alias="date"), component: str = "total"):
    d = date_ or (_lq("SELECT max(delivery_date) AS d FROM live_forecasts") or [{"d": None}])[0]["d"]
    if d is None:
        return js({"date": None, "rows": []})
    rows = _lq("""SELECT f.market, f.ts_utc, f.hour_local, f.mean, f.q05, f.q25, f.q50, f.q75, f.q95,
                         CASE f.market WHEN 'da' THEN z.da_lbmp ELSE z.rt_lbmp END AS actual_total,
                         CASE f.market WHEN 'da' THEN -z.da_mcc ELSE -z.rt_mcc END AS actual_congestion,
                         f.issue_utc, f.git_commit
                  FROM live_forecasts f
                  LEFT JOIN wh.lbmp_zone_hourly z ON z.zone = f.zone AND z.ts_utc = f.ts_utc
                  WHERE f.zone = ? AND f.delivery_date = ? AND f.component = ? ORDER BY f.market, f.ts_utc""",
               [zone, str(d), component])
    for r in rows:
        r["actual"] = r.pop("actual_congestion") if component == "congestion" else r.pop("actual_total")
        r.pop("actual_congestion", None), r.pop("actual_total", None)
    return js({"date": str(d), "zone": zone, "component": component, "rows": rows})


@app.get("/api/live/track")
def live_track(days: int = 60):
    """Daily track record of the live total-price forecast over the internal and external zones."""
    rows = _lq("""SELECT f.delivery_date, f.market, count(*) AS n,
                         avg(abs(f.mean - CASE f.market WHEN 'da' THEN z.da_lbmp ELSE z.rt_lbmp END)) AS mae,
                         avg(CASE WHEN (CASE f.market WHEN 'da' THEN z.da_lbmp ELSE z.rt_lbmp END) BETWEEN f.q05 AND f.q95
                                  THEN 1 ELSE 0 END) AS cov90
                  FROM live_forecasts f
                  JOIN wh.lbmp_zone_hourly z ON z.zone = f.zone AND z.ts_utc = f.ts_utc
                  WHERE f.component = 'total' AND (CASE f.market WHEN 'da' THEN z.da_lbmp ELSE z.rt_lbmp END) IS NOT NULL
                    AND f.delivery_date >= current_date - CAST(? AS INTEGER)
                  GROUP BY ALL ORDER BY f.delivery_date, f.market""", [days])
    return js(rows)


@app.get("/api/live/nodes")
def live_nodes(date_: str | None = Query(None, alias="date"), market: str = "da"):
    """Node forecast of total price, averaged over the delivery day, with coordinates for the map."""
    d = date_ or (_lq("SELECT max(delivery_date) AS d FROM live_forecasts") or [{"d": None}])[0]["d"]
    if d is None:
        return js({"date": None, "nodes": []})
    rows = _lq("""SELECT n.ptid, m.name, n.zone, m.lat, m.lon, avg(n.total) AS total, avg(n.congestion) AS congestion
                  FROM live_node_forecasts n JOIN wh.nodes m USING (ptid)
                  WHERE n.delivery_date = ? AND n.market = ? AND m.lat IS NOT NULL
                  GROUP BY ALL""", [str(d), market])
    return js({"date": str(d), "market": market, "nodes": rows})


@app.get("/api/live/dart")
def live_dart(date_: str | None = Query(None, alias="date")):
    """Per zone for one delivery day: peak RT spike probability, DART v2 paper position and (once settled) P&L."""
    d = date_ or (_lq("SELECT max(delivery_date) AS d FROM live_dart", table="live_dart") or [{"d": None}])[0]["d"]
    if d is None:
        return js({"date": None, "zones": []})
    rows = _lq("""SELECT x.zone, max(x.p_spike) AS p_spike_max, arg_max(x.hour_local, x.p_spike) AS p_spike_hour,
                         sum(x.x_mw) AS net_mwh, sum(abs(x.x_mw)) AS gross_mwh, avg(x.spread_fcst) AS spread_fcst,
                         avg(z.da_lbmp - z.rt_lbmp) AS spread_actual,
                         sum(CASE WHEN z.rt_lbmp IS NOT NULL AND z.da_lbmp IS NOT NULL
                                  THEN x.x_mw * (z.da_lbmp - z.rt_lbmp) - 0.5 * abs(x.x_mw) END) AS pnl,
                         count(z.rt_lbmp) AS settled_hours, count(*) AS hours
                  FROM live_dart x LEFT JOIN wh.lbmp_zone_hourly z ON z.zone = x.zone AND z.ts_utc = x.ts_utc
                  WHERE x.rule = 'v2' AND x.delivery_date = ? GROUP BY ALL ORDER BY x.zone""", [str(d)], table="live_dart")
    return js({"date": str(d), "zones": rows})


@app.get("/api/live/paper")
def live_paper():
    """Daily paper P&L of the live DART v2 positions over fully settled days ($, 1 MW limit per zone-hour, $0.50/MWh cost)."""
    rows = _lq("""WITH r AS (
                    SELECT x.delivery_date, abs(x.x_mw) AS mwh,
                           x.x_mw * (z.da_lbmp - z.rt_lbmp) - 0.5 * abs(x.x_mw) AS pnl
                    FROM live_dart x LEFT JOIN wh.lbmp_zone_hourly z ON z.zone = x.zone AND z.ts_utc = x.ts_utc
                    WHERE x.rule = 'v2')
                  SELECT delivery_date, sum(mwh) AS mwh, sum(pnl) AS pnl FROM r
                  GROUP BY delivery_date HAVING count(pnl) = count(*) ORDER BY delivery_date""", table="live_dart")
    run = 0.0
    for r in rows:
        run += r["pnl"] or 0.0
        r["cum_pnl"] = run
    return js(rows)


@app.get("/api/live/monthly")
def live_monthly(zone: str = "N.Y.C."):
    """Latest M5 vintage for one zone: monthly DA total and congestion, on/off-peak, with 90% intervals and actuals."""
    rows = _lq("""WITH v AS (SELECT max(cutoff) AS c FROM live_monthly)
                  SELECT f.cutoff, f.month, f.h, f.period, f.component, f.model, f.mean, f.q05, f.q50, f.q95
                  FROM live_monthly f, v WHERE f.cutoff = v.c AND f.zone = ?
                  ORDER BY f.month, f.component, f.period""", [zone], table="live_monthly")
    return js({"zone": zone, "rows": rows})


# ------------------------------------------------------------------ static

@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
