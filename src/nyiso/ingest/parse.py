"""Parse one NYISO daily CSV into a tidy, typed DataFrame keyed on UTC interval start.

Timestamp rules (verified against MIS files):
- Published times are Eastern Prevailing Time.
- On the fall-back day the repeated hour appears twice, in chronological (file) order.
  Files with a "Time Zone" column say EDT/EST explicitly. Otherwise, per entity, every
  row after local time steps backward (or repeats) is EST. Note "first occurrence = EDT"
  is NOT enough: off-grid RTD stamps in the EST hour (e.g. 01:02:48) occur only once.
- RT LBMP and fuel mix stamps mark interval END; everything else marks START.
"""
from __future__ import annotations

import io
from datetime import date

import numpy as np
import pandas as pd

from nyiso.config import TZ
from nyiso.datasets import Dataset


def _parse_local(raw: pd.Series) -> pd.Series:
    fmt = "%m/%d/%Y %H:%M:%S" if len(str(raw.iloc[0])) > 16 else "%m/%d/%Y %H:%M"
    return pd.to_datetime(raw, format=fmt)


def _localize(local: pd.Series, df: pd.DataFrame, ds: Dataset, tz_values: pd.Series | None) -> pd.Series:
    if tz_values is not None:
        is_dst = (tz_values.str.strip().str.upper() == "EDT").to_numpy()
    else:
        keys = list(ds.entity)
        prev = df.groupby(keys, sort=False)["_local"].shift()
        stepped_back = (df["_local"] <= prev).fillna(False)
        is_dst = (~stepped_back.groupby([df[k] for k in keys], sort=False).cummax()).to_numpy()
    return local.dt.tz_localize(TZ, ambiguous=is_dst, nonexistent="shift_forward")


# Header spellings in older MIS archives -> the current name (LBMP files before 2016-07 truncate this header).
HEADER_ALIASES = {"Marginal Cost Congestion ($/MWH": "Marginal Cost Congestion ($/MWHr)"}


def parse_csv(content: bytes | str, ds: Dataset, file_date: date | None = None) -> pd.DataFrame:
    """Parse a single daily CSV for dataset `ds`."""
    buf = io.StringIO(content.decode("utf-8-sig") if isinstance(content, bytes) else content)
    raw = pd.read_csv(buf, dtype=str, skipinitialspace=True)
    raw.columns = [HEADER_ALIASES.get(c.strip(), c.strip()) for c in raw.columns]
    if raw.empty:
        return pd.DataFrame()

    if ds.wide:
        return _parse_wide(raw, ds, file_date)

    df = raw[list(ds.columns)].rename(columns=ds.columns)
    for c in df.columns:
        df[c] = df[c].str.strip()
    df["_local"] = _parse_local(raw[ds.ts_col])
    tz_values = raw[ds.tz_col] if ds.tz_col else None
    ts = _localize(df["_local"], df, ds, tz_values).dt.tz_convert("UTC")
    if ds.ts_convention == "end":
        ts = ts - pd.Timedelta(minutes=ds.interval_min)

    out = df.drop(columns="_local")
    out.insert(0, "ts_utc", ts)
    out.insert(1, "ts_local", ts.dt.tz_convert(TZ).dt.tz_localize(None))
    for c in ds.datetime_cols:
        out[f"{c}_utc"] = _local_col_to_utc(out.pop(c))
    return _coerce(out)


def _local_col_to_utc(raw: pd.Series) -> pd.Series:
    """Extra local datetime columns (e.g. outage start/end). No EDT/EST marker is published for
    these, so an ambiguous fall-back time is read as EDT (at most a 1-hour error, once a year)."""
    local = pd.to_datetime(raw, format="mixed", errors="coerce")
    return local.dt.tz_localize(TZ, ambiguous=np.ones(len(local), dtype=bool),
                                nonexistent="shift_forward").dt.tz_convert("UTC")


def _parse_wide(raw: pd.DataFrame, ds: Dataset, file_date: date | None) -> pd.DataFrame:
    """isolf: one row per hour, one column per zone (+ NYISO total). Keep the issue date."""
    raw = raw.copy()
    raw["_local"] = _parse_local(raw[ds.ts_col])
    long = raw.drop(columns=ds.ts_col).melt(id_vars="_local", var_name="zone", value_name="load_forecast_mw")
    long["zone"] = long["zone"].str.upper()
    ts = _localize(long["_local"], long, ds, None).dt.tz_convert("UTC")
    out = pd.DataFrame({
        "ts_utc": ts,
        "ts_local": ts.dt.tz_convert(TZ).dt.tz_localize(None),
        "zone": long["zone"],
        "load_forecast_mw": long["load_forecast_mw"],
    })
    out["issue_date"] = pd.Timestamp(file_date) if file_date else pd.NaT
    # isolf repeats the fall-back hour with identical values; the dedup below handles it
    return _coerce(out)


_FLOAT_COLS = {"lbmp", "mlc", "mcc", "load_mw", "load_forecast_mw", "gen_mw", "mw",
               "shadow_price", "flow_mw", "pos_limit_mw", "neg_limit_mw",
               "spin_10", "nonsync_10", "or_30", "reg_cap", "reg_move"}
_INT_COLS = {"ptid", "facility_ptid"}


def _coerce(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        if c in _FLOAT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
        elif c in _INT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return df


def dedupe(df: pd.DataFrame, ds: Dataset) -> pd.DataFrame:
    """Drop exact key duplicates (keeps last, i.e. the latest-published value)."""
    if ds.snapshot_keys:
        keys = ["ts_utc", *ds.snapshot_keys]
    else:
        keys = ["ts_utc", *ds.curated_entity] + (["issue_date"] if ds.wide else [])
    return df.drop_duplicates(subset=keys, keep="last").reset_index(drop=True)


def compact_snapshots(df: pd.DataFrame, ds: Dataset) -> pd.DataFrame:
    """Collapse repeated snapshots (e.g. the outage schedule re-published every 5 minutes) into
    validity intervals: one row per contiguous run of a record, with the first and last snapshot
    that contained it. A record is 'known as of t' iff first_seen_utc <= t <= last_seen_utc.
    A gap longer than ds.snapshot_gap_min starts a new run (record dropped, then re-added)."""
    keys = list(ds.snapshot_keys)
    df = df.sort_values([*keys, "ts_utc"])
    gap = df.groupby(keys, dropna=False, sort=False)["ts_utc"].diff() > pd.Timedelta(minutes=ds.snapshot_gap_min)
    df["_run"] = gap.groupby([df[k] for k in keys], dropna=False, sort=False).cumsum()
    out = (df.groupby([*keys, "_run"], dropna=False, sort=False)
             .agg(first_seen_utc=("ts_utc", "min"), last_seen_utc=("ts_utc", "max"), snapshots=("ts_utc", "size"))
             .reset_index().drop(columns="_run"))
    return out


def file_date_from_name(name: str) -> date:
    return date(int(name[:4]), int(name[4:6]), int(name[6:8]))
