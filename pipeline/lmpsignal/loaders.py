"""Typed read-only loaders for the warehouse and the experiments registry (the edge of the pipeline).

Pure modules (structural model, TCC pricer) take DataFrames; the CLI/runner call loaders like these to get them.
"""
from __future__ import annotations

from collections.abc import Sequence

import duckdb
import pandas as pd

from lmpsignal import registry
from nyiso.config import DB_PATH


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


def experiments_df(sql: str, params: Sequence = ()) -> pd.DataFrame:
    """Run a read-only query on the experiments registry (retries while another process holds the lock)."""
    with registry.connect(read_only=True) as con:
        return con.execute(sql, list(params)).df()
