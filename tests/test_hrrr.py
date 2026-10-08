"""HRRR zone aggregation: units, delivery-day window, availability before the 05:00 ET issue."""
from datetime import date

import numpy as np
import pandas as pd

from nyiso.ingest import hrrr


def _fake_run(run, cells):
    n_h, n_c = 48, len(cells)
    hours = np.arange(1, n_h + 1)
    z = {"forecast_hours": hours, "iy": cells["iy"].to_numpy(), "ix": cells["ix"].to_numpy()}
    z["tmp2m"] = np.full((n_h, n_c), 300.0, dtype=np.float16)          # 26.85 °C
    z["dpt2m"] = np.full((n_h, n_c), 290.0, dtype=np.float16)
    z["u80"] = np.full((n_h, n_c), 3.0, dtype=np.float16)
    z["v80"] = np.full((n_h, n_c), 4.0, dtype=np.float16)              # speed 5
    z["tcdc"] = np.full((n_h, n_c), 50.0, dtype=np.float16)
    z["cape"] = np.tile(np.linspace(0, 1000, n_c, dtype=np.float32), (n_h, 1)).astype(np.float16)
    refc = np.zeros((n_h, n_c), dtype=np.float16)
    refc[:, : n_c // 4] = 45                                            # a quarter of cells >= 40 dBZ
    z["refc"] = refc
    z["ltng"] = np.full((n_h, n_c), np.nan, dtype=np.float16)           # field missing for this run
    return z


def test_zone_aggregates_units_and_delivery_window(monkeypatch):
    cells = pd.DataFrame({"zone": ["WEST"] * 8 + ["N.Y.C."] * 4, "iy": np.arange(12), "ix": np.arange(12)})
    monkeypatch.setattr(hrrr, "zone_cells", lambda: cells)
    monkeypatch.setattr(hrrr, "run_cells", _fake_run)
    df = hrrr.weather_hrrr(date(2024, 7, 16), date(2024, 7, 16), workers=1)
    for zone, g in df.groupby("zone"):
        assert len(g) == 24                                             # exactly the local hours of 2024-07-16
        local = g["ts_utc"].dt.tz_convert("America/New_York")
        assert (local.dt.date == date(2024, 7, 16)).all()
    assert np.allclose(df["temp_c"], 26.85, atol=0.2)
    assert np.allclose(df["wind80_ms"], 5.0, atol=0.01)
    share = df.groupby("zone")["refl40_share"].first()
    assert np.isclose(share["WEST"], 3 / 8) and share["N.Y.C."] == 0     # the stormy quarter of cells is in WEST
    assert df["lightning_density"].isna().all()                         # missing field stays missing, not zero
    west = df[df["zone"] == "WEST"]["cape_p90"].iloc[0]
    assert 500 < west < 1000


def test_available_before_issue_on_both_dst_offsets(monkeypatch):
    cells = pd.DataFrame({"zone": ["WEST"] * 4, "iy": np.arange(4), "ix": np.arange(4)})
    monkeypatch.setattr(hrrr, "zone_cells", lambda: cells)
    monkeypatch.setattr(hrrr, "run_cells", _fake_run)
    for d in (date(2024, 7, 16), date(2024, 1, 16), date(2024, 11, 3), date(2024, 3, 10)):
        df = hrrr.weather_hrrr(d, d, workers=1)
        issue = (pd.Timestamp(d) - pd.Timedelta(days=1) + pd.Timedelta(hours=5)).tz_localize("America/New_York")
        assert (df["available_utc"] <= issue.tz_convert("UTC")).all(), d
        assert len(df) == {date(2024, 11, 3): 25, date(2024, 3, 10): 23}.get(d, 24)
