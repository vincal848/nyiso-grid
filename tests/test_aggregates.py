"""Time-weighted aggregation on toy RTD data (irregular intervals, hour splits, gaps)."""
from pathlib import Path

import duckdb
import pytest

from nyiso.store.timeweight import twa_sql

SQL = (Path(__file__).parents[1] / "src" / "nyiso" / "store" / "aggregates.sql").read_text()
MACROS = "\n".join(line for line in SQL.splitlines() if line.startswith("CREATE OR REPLACE MACRO"))


def con():
    c = duckdb.connect()
    c.execute("SET TimeZone = 'UTC'")
    c.execute(MACROS)
    return c


def end_stamped(c, rows):
    """rows = [(published end stamp 'HH:MM:SS', value)] -> curated table (ts_utc = stamp - 5 min)."""
    c.execute("CREATE OR REPLACE TABLE src (ts_utc TIMESTAMPTZ, ptid INT, lbmp DOUBLE)")
    for stamp, v in rows:
        c.execute("INSERT INTO src VALUES (TIMESTAMPTZ '2025-06-01 00:00:00+00' + CAST(? AS INTERVAL) - INTERVAL 5 MINUTE, 1, ?)",
                  [stamp, v])


def twa(c, bucket="5 MINUTE", stamped="end", value="lbmp"):
    sql = twa_sql("src", "ptid", [value], bucket=bucket, stamped=stamped)
    return c.execute(f"SELECT strftime(ts_utc, '%H:%M'), round({value}, 6), covered_s FROM ({sql}) ORDER BY 1").fetchall()


def test_short_rtd_intervals_are_time_weighted():
    c = con()
    # 07:00 regular; then a delayed run ends 07:02:30 (150 s) and the next ends 07:05 (150 s)
    end_stamped(c, [("06:55:00", 0), ("07:00:00", 10), ("07:02:30", 100), ("07:05:00", 40)])
    got = dict((t, (v, s)) for t, v, s in twa(c))
    assert got["07:00"] == (70.0, 300)          # (100*150 + 40*150) / 300 — a plain mean of snapped stamps gives 40
    assert got["06:55"] == (10.0, 300)


def test_interval_spanning_hour_is_split():
    c = con()
    end_stamped(c, [("06:55:00", 0), ("06:58:00", 10), ("07:02:30", 100), ("07:05:00", 40)])
    got = dict((t, (v, s)) for t, v, s in twa(c, bucket="1 HOUR"))
    # 06:00 hour: 06:50-06:55 @0 (nominal first), 06:55-06:58 @10, 06:58-07:00 @100 (120 s of the 270 s interval)
    assert got["06:00"][1] == 300 + 180 + 120
    assert got["06:00"][0] == pytest.approx((0 * 300 + 10 * 180 + 100 * 120) / 600)
    # 07:00 hour: 07:00-07:02:30 @100, 07:02:30-07:05 @40
    assert got["07:00"] == (70.0, 300)


def test_gap_longer_than_15_minutes_uses_nominal_interval():
    c = con()
    end_stamped(c, [("06:00:00", 5), ("07:00:00", 50)])  # an hour of missing data, not a 60-min interval
    got = dict((t, (v, s)) for t, v, s in twa(c))
    assert got["06:55"] == (50.0, 300)
    assert "06:05" not in got


def test_start_stamped_series_uses_next_stamp():
    c = con()
    c.execute("CREATE TABLE src (ts_utc TIMESTAMPTZ, ptid INT, load_mw DOUBLE)")
    c.execute("""INSERT INTO src VALUES
        (TIMESTAMPTZ '2025-06-01 07:00:00+00', 1, 100),
        (TIMESTAMPTZ '2025-06-01 07:01:00+00', 1, 200),
        (TIMESTAMPTZ '2025-06-01 07:05:00+00', 1, 300)""")
    got = dict((t, (v, s)) for t, v, s in twa(c, stamped="start", value="load_mw"))
    assert got["07:00"] == (pytest.approx((100 * 60 + 200 * 240) / 300), 300)


def test_regular_intervals_reduce_to_plain_mean():
    c = con()
    end_stamped(c, [(f"{7 + m // 60:02d}:{m % 60:02d}:00", float(i)) for i, m in enumerate(range(5, 61, 5))])
    (_, v, s), = twa(c, bucket="1 HOUR")
    assert (v, s) == (5.5, 3600)


def test_twavg_macro():
    c = con()
    assert c.execute("SELECT twavg(v, w) FROM (VALUES (10.0, 100), (40.0, 200)) t(v, w)").fetchone()[0] == 30.0


def test_to_local_handles_dst():
    c = con()
    got = c.execute("SELECT strftime(to_local(TIMESTAMPTZ '2025-11-02 06:30:00+00'), '%H:%M')").fetchone()[0]
    assert got == "01:30"  # 01:30 EST (second occurrence)
