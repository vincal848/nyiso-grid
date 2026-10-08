"""NOAA HRRR forecasts aggregated to NYISO zones (external source `weather_hrrr`).

Source: the University of Utah's Zarr copy of the HRRR archive on AWS Open Data (s3://hrrrzarr, public domain,
HRRR v4 for the whole sample). Each variable of each run is stored in 48-hour x 150 x 150-cell chunks; the four
chunks covering New York are downloaded and only the cells inside NYISO zones are kept. Raw cache: one compressed
file per run, data/raw/hrrr/runs/YYYYMMDD.npz (cell values as published, float16, with the cell indices), because
the full chunks would be ~100 GB for five years while the cells used are ~16% of them. Delete a file to re-fetch.

Run used: 06z on D-1. Its 48-hour forecasts cover all of delivery day D (f22-f47 local midnight to midnight).
available_utc = run time + 2 h: the 06z run is complete by ~07:50 UTC, before the 05:00 ET issue (09:00 UTC in
summer, 10:00 UTC in winter).

Per zone and forecast hour (cells inside the approximate zone polygons of data/ref/zones.geojson):
means of 2 m temperature and dew point, 80 m wind speed and total cloud cover; for convection, the 90th
percentile of surface CAPE, the share of cells with composite reflectivity >= 40 dBZ and the mean forecast
lightning flash density. Shortwave radiation is not used: the Zarr archive stores it for some runs only.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from nyiso.config import RAW, REF

BUCKET = "https://hrrrzarr.s3.amazonaws.com"
RUN_HOUR_UTC = 6
LATENCY = timedelta(hours=2)
CHUNK = 150
NY, NX = 1059, 1799

# curated column: (level, variable)
VARS = {
    "tmp2m": ("2m_above_ground", "TMP"),
    "dpt2m": ("2m_above_ground", "DPT"),
    "u80": ("80m_above_ground", "UGRD"),
    "v80": ("80m_above_ground", "VGRD"),
    "tcdc": ("entire_atmosphere", "TCDC"),
    "cape": ("surface", "CAPE"),
    "refc": ("entire_atmosphere", "REFC"),
    "ltng": ("entire_atmosphere", "LTNG"),
}
COLUMNS = ["temp_c", "dewpoint_c", "wind80_ms", "cloud_pct", "cape_p90", "refl40_share", "lightning_density"]

_client: httpx.Client | None = None


def _http() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0), limits=httpx.Limits(max_connections=32))
    return _client


def _get(url: str, retries: int = 4) -> bytes | None:
    import time

    for attempt in range(retries):
        try:
            r = _http().get(url)
            if r.status_code in (403, 404):
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPError:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def _cached(path, url: str) -> bytes | None:
    if path.exists():
        return path.read_bytes()
    content = _get(url)
    if content is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(content)
        tmp.replace(path)
    return content


def _decode(raw: bytes, meta: dict) -> np.ndarray:
    from numcodecs import Blosc

    arr = np.frombuffer(Blosc().decode(raw), dtype=np.dtype(meta["dtype"])).reshape(meta["chunks"])
    arr = arr.astype(np.float32)
    if meta.get("fill_value") is not None:
        arr[arr == meta["fill_value"]] = np.nan
    return arr


# ----------------------------------------------------------------------------- grid and zone masks

def grid_latlon() -> tuple[np.ndarray, np.ndarray]:
    out = []
    for name in ("latitude", "longitude"):
        base = f"grid/HRRR_chunk_index.zarr/{name}"
        meta = json.loads(_cached(RAW / "hrrr" / "grid" / name / ".zarray", f"{BUCKET}/{base}/.zarray"))
        cy, cx = meta["chunks"]
        full = np.full((NY, NX), np.nan)
        for i in range(-(-NY // cy)):
            for j in range(-(-NX // cx)):
                raw = _cached(RAW / "hrrr" / "grid" / name / f"{i}.{j}", f"{BUCKET}/{base}/{i}.{j}")
                block = _decode(raw, {**meta, "fill_value": None}).astype(np.float64)
                ys, xs = slice(i * cy, min((i + 1) * cy, NY)), slice(j * cx, min((j + 1) * cx, NX))
                full[ys, xs] = block[: ys.stop - ys.start, : xs.stop - xs.start]
        out.append(full)
    return out[0], out[1]


def zone_cells() -> pd.DataFrame:
    """One row per HRRR cell inside an (approximate) NYISO zone polygon: zone, iy, ix."""
    import shapely
    from shapely.geometry import shape

    lat, lon = grid_latlon()
    zones = json.loads((REF / "zones.geojson").read_text())["features"]
    rows = []
    for f in zones:
        geom = shape(f["geometry"])
        minx, miny, maxx, maxy = geom.bounds
        box = (lon >= minx) & (lon <= maxx) & (lat >= miny) & (lat <= maxy)
        iy, ix = np.nonzero(box)
        inside = shapely.contains_xy(geom, lon[iy, ix], lat[iy, ix])
        rows.append(pd.DataFrame({"zone": f["properties"]["zone"], "iy": iy[inside], "ix": ix[inside]}))
    return pd.concat(rows, ignore_index=True)


# ----------------------------------------------------------------------------- one run

def _array_url(run: date, level: str, var: str) -> str:
    d = f"{run:%Y%m%d}"
    return f"{BUCKET}/sfc/{d}/{d}_{RUN_HOUR_UTC:02d}z_fcst.zarr/{level}/{var}/{level}/{var}"


def _download_cells(run: date, cells: pd.DataFrame) -> dict[str, np.ndarray] | None:
    """{forecast_hours, iy, ix, <var>: (hours, cells)} for the 06z run, or None if the run is missing."""
    base = f"{BUCKET}/sfc/{run:%Y%m%d}/{run:%Y%m%d}_{RUN_HOUR_UTC:02d}z_fcst.zarr/2m_above_ground/TMP/forecast_period"
    meta_raw = _get(f"{base}/.zarray")
    if meta_raw is None:
        return None
    hours = _decode(_get(f"{base}/0"), {**json.loads(meta_raw), "fill_value": None}).astype(int)
    iy, ix = cells["iy"].to_numpy(), cells["ix"].to_numpy()
    cy, cx = iy // CHUNK, ix // CHUNK
    out = {"forecast_hours": hours, "iy": iy, "ix": ix}
    for col, (level, var) in VARS.items():
        url = _array_url(run, level, var)
        vals = np.full((len(hours), len(cells)), np.nan, dtype=np.float32)
        meta_raw = _get(f"{url}/.zarray")
        if meta_raw is not None:
            meta = json.loads(meta_raw)
            for a, b in sorted(set(zip(cy, cx))):
                raw = _get(f"{url}/0.{a}.{b}")
                if raw is None:
                    continue
                sel = (cy == a) & (cx == b)
                vals[:, sel] = _decode(raw, meta)[: len(hours), iy[sel] % CHUNK, ix[sel] % CHUNK]
        out[col] = vals.astype(np.float16)
    return out


def run_cells(run: date, cells: pd.DataFrame) -> dict[str, np.ndarray] | None:
    """Cached cell values for one run; re-downloads if the cell set changed (e.g. new zone polygons)."""
    path = RAW / "hrrr" / "runs" / f"{run:%Y%m%d}.npz"
    if path.exists():
        z = dict(np.load(path))
        if np.array_equal(z["iy"], cells["iy"].to_numpy()) and np.array_equal(z["ix"], cells["ix"].to_numpy()):
            return z
    z = _download_cells(run, cells)
    if z is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".part.npz")
    np.savez_compressed(tmp, **z)
    tmp.replace(path)
    return z


def run_zone_table(run: date, cells: pd.DataFrame) -> pd.DataFrame:
    """Zone x forecast-hour aggregates for the 06z run of `run` (empty if the run is missing)."""
    z = run_cells(run, cells)
    if z is None:
        return pd.DataFrame()
    hours = z["forecast_hours"]
    values = {col: z[col].astype(np.float32) for col in VARS}

    derived = {
        "temp_c": values["tmp2m"] - 273.15,
        "dewpoint_c": values["dpt2m"] - 273.15,
        "wind80_ms": np.hypot(values["u80"], values["v80"]),
        "cloud_pct": values["tcdc"],
        "cape": values["cape"],
        "refl40": (values["refc"] >= 40).astype(np.float32),
        "lightning": values["ltng"],
    }
    run_utc = datetime(run.year, run.month, run.day, RUN_HOUR_UTC, tzinfo=UTC)
    import warnings

    warnings.filterwarnings("ignore", message="Mean of empty slice")       # a field missing for a run -> NaN
    warnings.filterwarnings("ignore", message="All-NaN slice encountered")
    frames = []
    for zone, idx in cells.groupby("zone").indices.items():
        f = pd.DataFrame({"lead_h": hours})
        for c in ("temp_c", "dewpoint_c", "wind80_ms", "cloud_pct"):
            f[c] = np.nanmean(derived[c][:, idx], axis=1)
        f["cape_p90"] = np.nanpercentile(derived["cape"][:, idx], 90, axis=1)
        f["refl40_share"] = derived["refl40"][:, idx].mean(axis=1)
        f["lightning_density"] = np.nanmean(derived["lightning"][:, idx], axis=1)
        f["zone"] = zone
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    df["run_utc"] = pd.Timestamp(run_utc)
    df["ts_utc"] = df["run_utc"] + pd.to_timedelta(df["lead_h"], unit="h")
    df["available_utc"] = df["run_utc"] + LATENCY
    return df[["ts_utc", "zone", "run_utc", "lead_h", *COLUMNS, "available_utc"]]


def weather_hrrr(start: date, end: date, workers: int = 24) -> pd.DataFrame:
    """06z runs dated start-1 .. end-1, i.e. forecasts for delivery days start .. end (local). Keeps only the
    hours that fall on the delivery day (run date + 1, America/New_York)."""
    cells = zone_cells()
    runs = [start - timedelta(days=1) + timedelta(days=i) for i in range((end - start).days + 1)]
    with ThreadPoolExecutor(workers) as pool:
        tables = list(pool.map(lambda r: run_zone_table(r, cells), runs))
    keep = []
    for run, t in zip(runs, tables):
        if t.empty:
            continue
        local_day = t["ts_utc"].dt.tz_convert("America/New_York").dt.date
        keep.append(t[local_day == run + timedelta(days=1)])
    return pd.concat(keep, ignore_index=True) if keep else pd.DataFrame(columns=["ts_utc", "zone", "run_utc", "lead_h",
                                                                                *COLUMNS, "available_utc"])
