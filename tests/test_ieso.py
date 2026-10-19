"""IESO intertie reports: hour-ending Eastern STANDARD time (no DST), components, RT interval means."""
from pathlib import Path

import pandas as pd
import pytest

from nyiso.ingest import external as e

FX = Path(__file__).parent / "fixtures"


def test_da_intertie_lmp_hours_and_components():
    df = e.parse_ieso_intertie_lmp((FX / "ieso_da_intertie_lmp_20261018.xml").read_bytes(), "DA")
    ny = df[df["intertie"] == "NY.ROSETON_NYSI"].sort_values("ts_utc")
    # Hour 1 of 2026-10-18 starts 00:00 EST = 05:00 UTC, even though New York is on daylight time that day.
    assert list(ny["ts_utc"]) == list(pd.date_range("2026-10-18 05:00", periods=3, freq="h", tz="UTC"))
    assert ny["lmp"].tolist() == [46.72, 45.39, 36.62]
    assert ny["loss"].iloc[0] == -0.95 and ny["nisl"].iloc[0] == 10.27
    assert (df["market"] == "DA").all()
    assert (df["available_utc"] == pd.Timestamp("2026-10-17 17:31:14", tz="UTC")).all()   # CreatedAt 12:31 EST


def test_rt_intertie_lmp_is_the_mean_of_twelve_intervals():
    df = e.parse_ieso_intertie_lmp((FX / "ieso_rt_intertie_lmp_2026101720.xml").read_bytes(), "RT")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ts_utc"] == pd.Timestamp("2026-10-18 00:00", tz="UTC")                   # hour 20 EST of 10-17
    assert row["lmp"] == pytest.approx((3 * 50.75 + 5 * 48.37 + 48.31 + 47.8 + 40.53 + 32.21) / 12)
    assert pd.isna(row["congestion"])                                                     # component absent in the file
    assert row["available_utc"] == pd.Timestamp("2026-10-18 01:00", tz="UTC")             # hour end, after CreatedAt


def test_intertie_flow_is_continuous_across_spring_forward():
    df = e.parse_ieso_intertie_flow((FX / "ieso_intertie_flow_2024.csv").read_text())
    assert df["intertie"].nunique() == 15
    ny = df[df["intertie"] == "NEW-YORK"].sort_values("ts_utc")
    spring = ny[ny["ts_utc"] < "2024-03-11"]
    # 2024-03-10 is the DST change in New York; IESO hours stay one hour apart.
    assert list(spring["ts_utc"]) == list(pd.date_range("2024-03-10 05:00", periods=4, freq="h", tz="UTC"))
    assert spring[["import_mw", "export_mw", "flow_mw"]].iloc[0].tolist() == [0, 908, 1158]
    assert (ny["available_utc"] > ny["ts_utc"] + pd.Timedelta(hours=1)).all()
