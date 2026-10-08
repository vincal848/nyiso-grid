"""Typed read-only loaders for the warehouse and the curated TCC tables (the edge of the pipeline).

Pure modules (structural model, TCC pricer) take DataFrames; the CLI/runner call loaders like these to get them.
"""
from __future__ import annotations

from collections.abc import Sequence

import duckdb
import pandas as pd

from nyiso.config import CURATED, DB_PATH
from nyiso.ingest.tcc import TCC_KEYS


def warehouse_df(sql: str, params: Sequence = (), **tables: pd.DataFrame) -> pd.DataFrame:
    """Run a read-only query on the warehouse (session time zone UTC). `tables` are DataFrames registered by name."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        con.execute("SET TimeZone = 'UTC'")
        for name, df in tables.items():
            con.register(name, df)
        return con.execute(sql, list(params)).df()
    finally:
        con.close()


def tcc_df(sql: str, params: Sequence = ()) -> pd.DataFrame:
    """Query the curated TCC tables (data/curated/tcc_*) directly, so no warehouse build is needed to read them."""
    con = duckdb.connect()
    try:
        for k in TCC_KEYS:
            con.execute(f"CREATE VIEW {k} AS SELECT * FROM read_parquet('{(CURATED / k / '**' / '*.parquet').as_posix()}')")
        return con.execute(sql, list(params)).df()
    finally:
        con.close()
