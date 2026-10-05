"""Non-MIS sources: EIA gas prices, NOAA GHCNh weather observations, Open-Meteo forecast vintages.

Every table carries `available_utc`: the earliest time the value could have been known. The
forecasting pipeline's as-of joins filter on it, so information rules live with the data.

Licensing: NOAA and EIA data are public domain. Open-Meteo's free API is for NON-COMMERCIAL use;
`weather_fcst` is research/backtesting only until a licensed forecast source replaces it.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from nyiso.config import RAW, TZ, WEATHER_STATIONS
from nyiso.ingest.mis_client import http_get


@dataclass(frozen=True)
class ExternalDataset:
    key: str
    description: str
    time_col: str          # column used to partition by month


EXTERNAL = {d.key: d for d in [
    ExternalDataset("gas_henry_hub", "Henry Hub natural gas spot price, daily (EIA)", "trade_date"),
    ExternalDataset("weather_obs", "Hourly weather observations at NY stations (NOAA GHCNh)", "ts_utc"),
    ExternalDataset("weather_fcst", "Hourly GFS temperature forecasts by lead time, 0-7 days (Open-Meteo "
                    "previous-runs API; research use only)", "ts_utc"),
    ExternalDataset("weather_hrrr", "NOAA HRRR 06z day-ahead forecasts aggregated to NYISO zones (public domain)",
                    "ts_utc"),
    ExternalDataset("outage_schedule", "NYISO forward transmission outage schedule (P-14B), archived daily snapshots",
                    "snapshot_utc"),
]}


def _cached(path, url: str, refresh: bool) -> bytes | None:
    if path.exists() and not refresh:
        return path.read_bytes()
    content = http_get(url)
    if content is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return content


def _et_to_utc(local: pd.Series) -> pd.Series:
    return local.dt.tz_localize(TZ, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")


# ----------------------------------------------------------------------------- EIA

def gas_henry_hub(refresh: bool = True) -> pd.DataFrame:
    """Henry Hub spot for trade date T (gas for next-day flow). Assumed known by 00:00 ET on T+1.

    Caveat for live use: EIA posts this series weekly; a live pipeline needs a same-day source.
    """
    raw = _cached(RAW / "eia" / "RNGWHHDd.xls", "https://www.eia.gov/dnav/ng/hist_xls/RNGWHHDd.xls", refresh)
    df = pd.read_excel(io.BytesIO(raw), sheet_name="Data 1", skiprows=2)
    df.columns = ["trade_date", "price_usd_mmbtu"]
    df = df.dropna()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    df["price_usd_mmbtu"] = df["price_usd_mmbtu"].astype(float)
    df["available_utc"] = _et_to_utc(df["trade_date"] + pd.Timedelta(days=1))
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------- NOAA GHCNh

_GHCNH = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{y}/psv/GHCNh_{id}_{y}.psv"
_OBS_COLS = {"DATE": "obs_utc", "temperature": "temp_c", "dew_point_temperature": "dewpoint_c",
             "wind_speed": "wind_ms"}


def weather_obs(years: list[int], refresh_current: bool = True) -> pd.DataFrame:
    """Hourly station observations. Reports within +-30 min of the hour are averaged into that hour
    (METARs are issued at ~HH:51). Values outside physical ranges are dropped.
    available_utc = hour + 30 min (the last report in the window has been issued)."""
    frames = []
    this_year = date.today().year
    for code, (gid, *_rest) in WEATHER_STATIONS.items():
        for y in years:
            raw = _cached(RAW / "noaa_ghcnh" / f"{gid}_{y}.psv", _GHCNH.format(y=y, id=gid),
                          refresh=refresh_current and y == this_year)
            if raw is None:
                continue
            df = pd.read_csv(io.BytesIO(raw), sep="|", usecols=list(_OBS_COLS), dtype=str, low_memory=False)
            df = df.rename(columns=_OBS_COLS)
            df["obs_utc"] = pd.to_datetime(df["obs_utc"], utc=True, errors="coerce")
            for c in ("temp_c", "dewpoint_c", "wind_ms"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df.loc[~df["temp_c"].between(-45, 45), "temp_c"] = None
            df.loc[~df["dewpoint_c"].between(-60, 35), "dewpoint_c"] = None
            df.loc[~df["wind_ms"].between(0, 60), "wind_ms"] = None
            df = df.dropna(subset=["obs_utc"])
            df = df[df[["temp_c", "dewpoint_c", "wind_ms"]].notna().any(axis=1)]
            df["ts_utc"] = df["obs_utc"].dt.round("h")
            df["station"] = code
            frames.append(df)
    obs = pd.concat(frames, ignore_index=True)
    out = (obs.groupby(["ts_utc", "station"], as_index=False)
              .agg(temp_c=("temp_c", "mean"), dewpoint_c=("dewpoint_c", "mean"), wind_ms=("wind_ms", "mean"),
                   n_reports=("obs_utc", "size")))
    out = out[out["ts_utc"] <= pd.Timestamp.now(tz="UTC")]
    out["available_utc"] = out["ts_utc"] + pd.Timedelta(minutes=30)
    return out


# ----------------------------------------------------------------------------- Open-Meteo

_PREV = ("https://previous-runs-api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
         "&hourly={vars}&models=gfs_seamless&start_date={s}&end_date={e}&timezone=UTC")
LEADS = range(0, 8)
MODEL_LATENCY = timedelta(hours=6)


def weather_fcst(start: date, end: date, refresh_current: bool = True) -> pd.DataFrame:
    """GFS 2 m temperature as forecast `lead_days` x 24 h before the valid hour (Open-Meteo
    definition of `_previous_dayN`). GFS is pinned for the whole history (the only model archived
    before 2024), so the feature does not change source mid-sample.

    available_utc = valid time - lead_days x 24 h + 6 h model latency (conservative). For lead 0
    ('current run'), available = valid time + 6 h, i.e. treat it as a near-analysis, not a forecast.
    """
    vars_ = ",".join(["temperature_2m"] + [f"temperature_2m_previous_day{n}" for n in LEADS if n])
    frames = []
    for code, (_gid, _name, lat, lon, _zones) in WEATHER_STATIONS.items():
        for y in range(start.year, end.year + 1):
            s, e = max(start, date(y, 1, 1)), min(end, date(y, 12, 31))
            current = e >= date.today() - timedelta(days=7)
            raw = _cached(RAW / "openmeteo_prev" / f"{code}_{y}.json",
                          _PREV.format(lat=lat, lon=lon, vars=vars_, s=s, e=e), refresh=refresh_current and current)
            if raw is None:
                continue
            h = json.loads(raw)["hourly"]
            wide = pd.DataFrame(h)
            wide["ts_utc"] = pd.to_datetime(wide.pop("time"), utc=True)
            long = wide.melt(id_vars="ts_utc", var_name="var", value_name="temp_c").dropna(subset=["temp_c"])
            long["lead_days"] = long["var"].str.extract(r"previous_day(\d)$")[0].fillna(0).astype(int)
            long["station"] = code
            frames.append(long.drop(columns="var"))
    fc = pd.concat(frames, ignore_index=True)
    lead = pd.to_timedelta(fc["lead_days"] * 24, unit="h")
    fc["available_utc"] = fc["ts_utc"] - lead + MODEL_LATENCY
    return fc[["ts_utc", "station", "lead_days", "temp_c", "available_utc"]]


# ----------------------------------------------------------------------------- NYISO forward outage schedule (P-14B)

_OUTAGE_SCHEDULE = "https://mis.nyiso.com/public/csv/os/outage-schedule.csv"


def outage_schedule_snapshot() -> None:
    """Save the current P-14B outage schedule to the raw cache. NYISO publishes only the current file (no archive),
    so history exists only from the first snapshot on; scripts/daily.py takes one every morning."""
    now = datetime.now(timezone.utc)
    content = http_get(_OUTAGE_SCHEDULE)
    if content is None:
        return
    path = RAW / "outage_schedule" / f"{now:%Y%m%dT%H%M}Z.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def outage_schedule() -> pd.DataFrame:
    """All archived P-14B snapshots: one row per (snapshot, outage record). available_utc = snapshot time."""
    frames = []
    for f in sorted((RAW / "outage_schedule").glob("*Z.csv")):
        snap = pd.Timestamp(datetime.strptime(f.stem, "%Y%m%dT%H%MZ"), tz="UTC")
        raw = pd.read_csv(f, dtype=str, skipinitialspace=True)
        raw.columns = [c.strip() for c in raw.columns]
        df = pd.DataFrame({
            "snapshot_utc": snap,
            "ptid": pd.to_numeric(raw["PTID"], errors="coerce").astype("Int64"),
            "outage_id": raw["Outage ID"].str.strip(),
            "equipment": raw["Equipment Name"].str.strip(),
            "equipment_type": raw["Equipment Type"].str.strip(),
            "sched_out_utc": _et_to_utc(pd.to_datetime(raw["Date Out"] + " " + raw["Time Out"], format="%m/%d/%Y %H:%M",
                                                       errors="coerce")),
            "sched_in_utc": _et_to_utc(pd.to_datetime(raw["Date In"] + " " + raw["Time In"], format="%m/%d/%Y %H:%M",
                                                      errors="coerce")),
            "called_in": raw["Called In"].str.strip(),
            "status": raw["Status"].str.strip(),
            "status_date_utc": _et_to_utc(pd.to_datetime(raw["Status Date"], format="%m-%d-%Y %H:%M", errors="coerce")),
            "message": raw.get("Message", pd.Series(dtype=str)).str.strip(),
        })
        df["available_utc"] = snap
        frames.append(df)
    cols = ["snapshot_utc", "ptid", "outage_id", "equipment", "equipment_type", "sched_out_utc", "sched_in_utc",
            "called_in", "status", "status_date_utc", "message", "available_utc"]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)
