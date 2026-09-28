"""Write curated Parquet: data/curated/{key}/year=YYYY/month=MM/part.parquet."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from nyiso.config import CURATED


def partition_path(key: str, year: int, month: int) -> Path:
    return CURATED / key / f"year={year}" / f"month={month:02d}" / "part.parquet"


def write_month(df: pd.DataFrame, key: str, year: int, month: int) -> Path:
    path = partition_path(key, year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_values([c for c in ("ts_utc", "ptid", "zone", "fuel", "facility", "interface")
                         if c in df.columns])
    table = pa.Table.from_pandas(df, preserve_index=False)
    tmp = path.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd", row_group_size=500_000)
    tmp.replace(path)
    return path
