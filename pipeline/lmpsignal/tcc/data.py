"""Edge of the TCC pricer: read auctions, hourly nodal congestion and shadow prices into DataFrames."""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal.loaders import tcc_df, warehouse_df
from lmpsignal.tcc.pricer import hour_grid


def auction_paths() -> pd.DataFrame:
    """One row per awarded path in each auction period, with its clearing price. A path can have several award lines
    (bid and offer, split lines) at one price; MW sums them."""
    d = tcc_df("""SELECT a.round_id, a.period_id, a.poi, a.pow, any_value(a.mcp) AS c, sum(a.tccs_awarded) AS mw,
                         any_value(a.posted_date) AS posted, any_value(a.period_start) AS start,
                         any_value(a.period_end) AS "end", any_value(a.period_months) AS months,
                         any_value(r.kind) AS kind, any_value(r.term_months) AS term_months,
                         count(DISTINCT a.mcp) AS n_prices
                  FROM tcc_awards a JOIN tcc_rounds r USING (round_id)
                  GROUP BY a.round_id, a.period_id, a.poi, a.pow""")
    assert (d["n_prices"] == 1).all(), "a path has two clearing prices in one auction period"
    return d.drop(columns="n_prices")


def poi_ptids() -> tuple[set[int], set[int]]:
    """(zone and external-proxy ptids, generator-node ptids) that have DA prices in the warehouse."""
    z = warehouse_df("SELECT DISTINCT ptid FROM da_lbmp_zone")["ptid"]
    n = warehouse_df("SELECT DISTINCT ptid FROM da_lbmp_node")["ptid"]
    return set(z.astype(int)), set(n.astype(int)) - set(z.astype(int))


def poi_congestion(start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly DA congestion component (-MCC, $/MWh) for every zone and generator node, delivery hours in
    [start, end): (frame indexed by UTC hour start with a column per PTID, its local (d, hr) grid)."""
    parts = []
    for year in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        lo, hi = max(pd.Timestamp(start), pd.Timestamp(year, 1, 1)), min(pd.Timestamp(end), pd.Timestamp(year + 1, 1, 1))
        if lo >= hi:
            continue
        long = warehouse_df("""SELECT ts_utc, ptid, avg(-mcc) AS cong FROM (
                                   SELECT ts_utc, ts_local, ptid, mcc FROM da_lbmp_zone
                                   UNION ALL SELECT ts_utc, ts_local, ptid, mcc FROM da_lbmp_node)
                               WHERE ts_local >= ? AND ts_local < ? GROUP BY ALL""", [str(lo.date()), str(hi.date())])
        parts.append(long.pivot(index="ts_utc", columns="ptid", values="cong"))
    cong = pd.concat(parts).sort_index()
    cong.columns = cong.columns.astype(np.int64)
    return cong, hour_grid(cong.index)
