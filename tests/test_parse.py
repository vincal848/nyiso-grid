"""Parser tests on real MIS files from the 2025-11-02 fall-back day (25 hours)."""
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nyiso.datasets import DATASETS
from nyiso.ingest.parse import dedupe, parse_csv

FIX = Path(__file__).parent / "fixtures"
DAY_START = pd.Timestamp("2025-11-02 04:00", tz="UTC")  # 00:00 EDT
DAY_END = pd.Timestamp("2025-11-03 05:00", tz="UTC")    # 00:00 EST next day


def load(name: str, key: str) -> pd.DataFrame:
    ds = DATASETS[key]
    return dedupe(parse_csv((FIX / name).read_bytes(), ds, file_date=date(2025, 11, 2)), ds)


def assert_regular(ts: pd.Series, minutes: int, n: int):
    ts = ts.sort_values().reset_index(drop=True)
    assert len(ts) == n
    assert ts.is_unique
    assert (ts.diff().dropna() == pd.Timedelta(minutes=minutes)).all()
    assert ts.iloc[0] == DAY_START
    assert ts.iloc[-1] == DAY_END - pd.Timedelta(minutes=minutes)


def test_dam_hourly_fallback_day_has_25_hours():
    df = load("damlbmp_zone_20251102.csv", "da_lbmp_zone")
    for _, g in df.groupby("zone"):
        assert_regular(g["ts_utc"], 60, 25)
    assert set(df["zone"]) == {"CAPITL", "WEST"}
    assert df["lbmp"].dtype == "float64"


def test_rt_interval_ending_shifted_to_start():
    df = load("realtime_zone_20251102.csv", "rt_lbmp_zone")
    assert_regular(df["ts_utc"], 5, 300)
    # first row in the file is stamped 00:05 EDT -> interval start 00:00 EDT
    first = df.sort_values("ts_utc").iloc[0]
    assert first["ts_local"] == pd.Timestamp("2025-11-02 00:00")


def test_pal_uses_time_zone_column():
    df = load("pal_20251102.csv", "load")
    assert_regular(df["ts_utc"], 5, 300)
    assert df["load_mw"].notna().all()


def test_fuel_mix_per_fuel_regular():
    df = load("rtfuelmix_20251102.csv", "fuel_mix")
    for _, g in df.groupby("fuel"):
        assert_regular(g["ts_utc"], 5, 300)


def test_isolf_wide_to_long():
    df = load("isolf_20251102.csv", "load_forecast")
    assert "NYISO" in set(df["zone"])
    assert len(df["zone"].unique()) == 12
    for _, g in df.groupby("zone"):
        ts = g["ts_utc"].sort_values()
        assert ts.is_unique
        assert (ts.diff().dropna() == pd.Timedelta(hours=1)).all()


def test_offgrid_stamps_in_repeated_hour_are_est():
    """2021-11-07: '01:02:48' and '01:08:12' appear once, after the clock falls back -> EST.

    End-to-end check: time-weighted hourly values must reproduce NYISO's integrated
    RT LBMP for both 1 AM hours (CAPITL: 124.31 EDT, 77.54 EST).
    """
    import duckdb

    from nyiso.store.timeweight import twa_sql

    ds = DATASETS["rt_lbmp_zone"]
    df = dedupe(parse_csv((FIX / "realtime_zone_20211107.csv").read_bytes(), ds), ds)
    assert df["ts_utc"].is_unique
    local = df.set_index("ts_utc")["ts_local"]
    assert local[pd.Timestamp("2021-11-07 05:57:48", tz="UTC")] == pd.Timestamp("2021-11-07 01:57:48")  # EST hour, end 01:02:48 EST

    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.register("src", df[["ts_utc", "ptid", "lbmp"]])
    hourly = dict(c.execute(f"""
        SELECT strftime(ts_utc, '%H'), round(lbmp, 2) FROM ({twa_sql('src', 'ptid', ['lbmp'], bucket='1 HOUR')})
    """).fetchall())
    assert hourly["05"] == 124.31  # 01:00-02:00 EDT
    assert hourly["06"] == 77.54   # 01:00-02:00 EST


@pytest.mark.parametrize("stamp,tz,expected_utc", [
    ("03/08/2026 01:00", "EST", "2026-03-08 06:00"),
    ("03/08/2026 03:00", "EDT", "2026-03-08 07:00"),
])
def test_spring_forward(stamp, tz, expected_utc):
    csv = f'"Time Stamp","Time Zone","Zone Name","MW Value"\n"{stamp}","{tz}","CAPITL",1\n'
    df = parse_csv(csv, DATASETS["btm_solar"])
    assert df["ts_utc"].iloc[0] == pd.Timestamp(expected_utc, tz="UTC")


def test_snapshot_compaction_splits_on_gaps_and_changes():
    """Outage schedule snapshots -> validity runs; a changed return time is a new record."""
    from nyiso.ingest.parse import compact_snapshots

    ds = DATASETS["sched_outages"]
    t0 = pd.Timestamp("2026-08-24 14:00", tz="UTC")
    rows = []
    for i in range(6):                      # 14:00-14:25, return time A
        rows.append((t0 + pd.Timedelta(minutes=5 * i), "A"))
    for i in range(6, 9):                   # 14:30-14:40, return time rolled forward to B
        rows.append((t0 + pd.Timedelta(minutes=5 * i), "B"))
    rows.append((t0 + pd.Timedelta(minutes=90), "B"))  # reappears after a 50-min publishing gap
    df = pd.DataFrame({
        "ts_utc": [r[0] for r in rows], "ptid": 1, "equipment": "LINE_1",
        "sched_out_utc": t0, "sched_in_utc": [pd.Timestamp(f"2026-08-25 {'10' if r[1] == 'A' else '12'}:00", tz="UTC") for r in rows],
    })
    out = compact_snapshots(df, ds).sort_values("first_seen_utc").reset_index(drop=True)
    assert list(out["snapshots"]) == [6, 3, 1]
    assert out.loc[0, "last_seen_utc"] == t0 + pd.Timedelta(minutes=25)
    assert out.loc[2, "first_seen_utc"] == t0 + pd.Timedelta(minutes=90)


def test_old_lbmp_header_spelling_is_aliased():
    """MIS LBMP files before 2016-07 truncate the congestion header to '($/MWH'."""
    old = ('"Time Stamp","Name","PTID","LBMP ($/MWHr)","Marginal Cost Losses ($/MWHr)","Marginal Cost Congestion ($/MWH"\n'
           '"03/01/2016 00:00","CAPITL",61757,14.16,0.47,-7.20\n')
    df = parse_csv(old, DATASETS["da_lbmp_zone"], file_date=date(2016, 3, 1))
    assert df["mcc"].iloc[0] == -7.20 and df["lbmp"].iloc[0] == 14.16
