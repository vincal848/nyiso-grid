"""Fetch non-MIS sources and write them to curated Parquet (same layout as MIS datasets)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from nyiso.config import DEFAULT_START
from nyiso.ingest import external
from nyiso.store.writer import write_month


def _write_by_month(df: pd.DataFrame, key: str, time_col: str) -> int:
    t = df[time_col]
    local = t.dt.tz_convert("America/New_York") if getattr(t.dt, "tz", None) is not None else t
    n = 0
    for (y, m), part in df.groupby([local.dt.year, local.dt.month]):
        write_month(part.reset_index(drop=True), key, int(y), int(m))
        n += 1
    return n


def run(sources: list[str] | None = None, start: str = DEFAULT_START, end: date | None = None) -> dict[str, tuple[int, int]]:
    sy, sm = map(int, start.split("-"))
    start_d, end_d = date(sy, sm, 1), end or date.today()
    todo = sources or list(external.EXTERNAL)
    out = {}
    for key in todo:
        if key == "gas_henry_hub":
            df = external.gas_henry_hub()
            df = df[df["trade_date"] >= pd.Timestamp(start_d)]
        elif key == "weather_obs":
            df = external.weather_obs(list(range(start_d.year, end_d.year + 1)))
            df = df[df["ts_utc"] >= pd.Timestamp(start_d, tz="America/New_York")]
        elif key == "weather_fcst":
            df = external.weather_fcst(start_d, end_d)
        elif key == "weather_hrrr":
            from nyiso.ingest import hrrr

            df = hrrr.weather_hrrr(start_d, end_d)
        else:
            raise ValueError(f"unknown external source {key}")
        parts = _write_by_month(df, key, external.EXTERNAL[key].time_col)
        out[key] = (len(df), parts)
    return out
