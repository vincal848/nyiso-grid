"""Static reference data: generator nodes (with coordinates) and load points."""
from __future__ import annotations

import io

import pandas as pd

from nyiso.config import MIS_BASE, RAW
from nyiso.ingest.mis_client import http_get


def _fetch(path: str, refresh: bool) -> bytes:
    dest = RAW / "ref" / path.replace("/", "_")
    if dest.exists() and not refresh:
        return dest.read_bytes()
    content = http_get(f"{MIS_BASE}/{path}")
    if content is None:
        raise RuntimeError(f"MIS reference file not found: {path}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return content


def generators(refresh: bool = False) -> pd.DataFrame:
    """generator.csv -> ptid, name, zone, subzone, lat, lon, active, aggregation_ptid."""
    df = pd.read_csv(io.BytesIO(_fetch("generator/generator.csv", refresh)), dtype=str)
    df = df.rename(columns={
        "Generator Name": "name", "Generator PTID": "ptid", "Aggregation PTID": "aggregation_ptid",
        "Subzone": "subzone", "Zone": "zone", "Latitude": "lat", "Longitude": "lon", "Active": "active",
    })
    df["ptid"] = pd.to_numeric(df["ptid"]).astype("Int64")
    df["aggregation_ptid"] = pd.to_numeric(df["aggregation_ptid"], errors="coerce").astype("Int64")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["active"] = df["active"].str.upper().eq("Y")
    for c in ("name", "zone", "subzone"):
        df[c] = df[c].str.strip()
    return df[["ptid", "name", "zone", "subzone", "lat", "lon", "active", "aggregation_ptid"]]


def loads(refresh: bool = False) -> pd.DataFrame:
    """load.csv -> ptid, name, zone, subzone (no coordinates published)."""
    df = pd.read_csv(io.BytesIO(_fetch("load/load.csv", refresh)), dtype=str)
    df = df.rename(columns={"Load Name": "name", "PTID": "ptid", "Subzone": "subzone", "Zone": "zone"})
    df["ptid"] = pd.to_numeric(df["ptid"]).astype("Int64")
    for c in ("name", "zone", "subzone"):
        df[c] = df[c].str.strip()
    return df
