"""Download TCC auction results (ingest/tcc.py) and write them to curated Parquet, partitioned by posted month.

Tables: tcc_rounds (one row per round), tcc_nodal_prices (round x period x POI), tcc_awards (round x period x award).
"""
from __future__ import annotations

import pandas as pd

from nyiso.dictionary import TABLES
from nyiso.ingest import tcc
from nyiso.store.writer import write_month


def build(rounds: pd.DataFrame, reports: dict[tuple[int, str], str]) -> dict[str, pd.DataFrame]:
    """Parse downloaded CSV text ({(round_id, report): text}) into the three tables. Rounds without both reports
    (no published result) are left out of all three."""
    nodal, awards, meta = [], [], []
    for r in rounds.itertuples():
        if (r.round_id, "nodal_prices") not in reports or (r.round_id, "awards_summary") not in reports:
            continue
        for name, acc in (("nodal_prices", nodal), ("awards_summary", awards)):
            df, posted, status = tcc.parse_report(reports[(r.round_id, name)])
            acc.append(df.assign(round_id=r.round_id, posted_date=pd.Timestamp(posted)))
        meta.append({**r._asdict(), "posted_date": pd.Timestamp(posted), "status": status})
    tables = {"tcc_rounds": pd.DataFrame(meta), "tcc_nodal_prices": pd.concat(nodal, ignore_index=True),
              "tcc_awards": pd.concat(awards, ignore_index=True)}
    return {k: df[list(TABLES[k].columns)] for k, df in tables.items()}


def write(tables: dict[str, pd.DataFrame]) -> None:
    for key, df in tables.items():
        for (y, m), part in df.groupby([df["posted_date"].dt.year, df["posted_date"].dt.month]):
            write_month(part.reset_index(drop=True), key, int(y), int(m))


def run(first_season_year: int = 2014, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Fetch every priced round whose season year is >= first_season_year (the warehouse's zone prices start 2015-01)
    and write the curated tables. Network calls are cached raw; finalized rounds are fetched once."""
    rounds = tcc.fetch_rounds()
    rounds = rounds[(rounds["season_year"] >= first_season_year) & (rounds["kind"] != "fixed_price")]
    reports = {}
    for rid in rounds["round_id"]:
        for name in tcc.REPORTS:
            reports[(int(rid), name)] = tcc.fetch_report(int(rid), name, refresh=refresh)
    tables = build(rounds, reports)
    write(tables)
    return tables
