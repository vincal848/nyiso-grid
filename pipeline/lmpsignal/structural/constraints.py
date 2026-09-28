"""Constraint-level data for the structural congestion model.

Hourly shadow-price table per market, keyed by (local delivery date, local hour, constraint key):
  DA: da_constraints is hourly already (sum over duplicate rows).
  RT: rt_constraints lists binding RTD intervals only; the hourly value is sum(shadow price) * 5/60,
      i.e. the time-average over the hour assuming nominal 5-minute intervals (approximation; RT
      constraint rows are not time-weighted).
Constraint key = facility + ' | ' + contingency (constraint renames are not yet mapped: known gap).

Scheduled-outage counts known at issue time come from sched_outages validity runs:
a record counts for delivery day D if it was in the published schedule at the issue time
(first_seen_utc <= issue < last_seen_utc + 5 min) and its outage window overlaps D.
"""
from __future__ import annotations

import duckdb
import pandas as pd

from nyiso.config import DB_PATH
from lmpsignal.config import ISSUE_HOUR_ET


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    return con


def shadow_prices(start: str, end: str) -> pd.DataFrame:
    """Long table: market, d (local date), hr (local hour), key, mu. Only binding (non-zero) rows."""
    con = _con()
    df = con.execute(f"""
        SELECT 'da' AS market, CAST(ts_local AS DATE) AS d, hour(ts_local) AS hr,
               facility || ' | ' || contingency AS key, avg(shadow_price) AS mu
        FROM (SELECT ts_local, facility, contingency, sum(shadow_price) AS shadow_price
              FROM da_constraints WHERE ts_local >= ? AND ts_local < ? GROUP BY ALL)
        GROUP BY ALL
        UNION ALL
        SELECT 'rt', CAST(ts_local AS DATE), hour(ts_local), facility || ' | ' || contingency,
               sum(shadow_price) * 5.0 / 60.0 / count(DISTINCT CAST(ts_local AS DATE))
        FROM rt_constraints WHERE ts_local >= ? AND ts_local < ? GROUP BY ALL
    """, [start, end, start, end]).df()
    con.close()
    df["d"] = pd.to_datetime(df["d"])
    return df[df["mu"] != 0]


def outage_counts(days: pd.DatetimeIndex) -> pd.DataFrame:
    """Per delivery day D: scheduled outage records known at the D-1 05:00 ET issue that overlap D
    (all, and 345 kV equipment)."""
    con = _con()
    con.register("days_df", pd.DataFrame({"d": days}))
    df = con.execute(f"""
        WITH dd AS (
            SELECT CAST(d AS DATE) AS d,
                   timezone('America/New_York', CAST(CAST(d AS DATE) - INTERVAL 1 DAY AS TIMESTAMP)
                            + INTERVAL {ISSUE_HOUR_ET} HOUR) AS issue_utc,
                   timezone('America/New_York', CAST(CAST(d AS DATE) AS TIMESTAMP)) AS d0,
                   timezone('America/New_York', CAST(CAST(d AS DATE) + INTERVAL 1 DAY AS TIMESTAMP)) AS d1
            FROM days_df)
        SELECT dd.d,
               count(DISTINCT o.ptid || o.equipment) AS n_outages,
               count(DISTINCT o.ptid || o.equipment) FILTER (WHERE o.equipment LIKE '%345%') AS n_outages_345
        FROM dd LEFT JOIN sched_outages o
          ON o.first_seen_utc <= dd.issue_utc AND dd.issue_utc < o.last_seen_utc + INTERVAL 5 MINUTE
         AND o.sched_out_utc < dd.d1 AND o.sched_in_utc > dd.d0
        GROUP BY dd.d ORDER BY dd.d
    """).df()
    con.close()
    df["d"] = pd.to_datetime(df["d"])
    return df


def node_congestion(market: str, start, end) -> pd.DataFrame:
    """Hourly nodal congestion component (-MCC) for delivery days [start, end): index (d, hr), columns ptid.
    DA from da_lbmp_node, RT from NYISO's integrated hourly rt_lbmp_node_hourly."""
    view = "da_lbmp_node" if market == "da" else "rt_lbmp_node_hourly"
    con = _con()
    df = con.execute(f"""SELECT CAST(ts_local AS DATE) AS d, hour(ts_local) AS hr, ptid, avg(-mcc) AS cong
                         FROM {view} WHERE ts_local >= ? AND ts_local < ? GROUP BY ALL""",
                     [str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())]).df()
    con.close()
    df["d"] = pd.to_datetime(df["d"])
    return df.pivot_table(index=["d", "hr"], columns="ptid", values="cong")
