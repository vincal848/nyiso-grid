"""M8 shadow member: the context never contains information after the issue time."""
from datetime import date

import numpy as np
import pandas as pd
from lmpsignal import shadow
from lmpsignal.live import issue_utc


def _panel(d: date) -> pd.DataFrame:
    ts = pd.date_range(pd.Timestamp(d - pd.Timedelta(days=35).to_pytimedelta()).tz_localize("America/New_York"),
                       pd.Timestamp(d).tz_localize("America/New_York") + pd.Timedelta(hours=23), freq="h").tz_convert("UTC")
    loc = ts.tz_convert("America/New_York")
    rows = []
    for z in ("WEST", "N.Y.C."):
        rows.append(pd.DataFrame({"ts_utc": ts, "zone": z, "delivery_date": loc.tz_localize(None).normalize(),
                                  "hour_local": loc.hour, "da_total": np.arange(len(ts), dtype=float),
                                  "rt_total": np.arange(len(ts), dtype=float), "load_fcst_zone": 1.0,
                                  "temp_fcst_zone": 2.0}))
    return pd.concat(rows, ignore_index=True)


def test_context_ends_before_issue_information():
    d = date(2026, 7, 15)
    p = _panel(d)
    d_start = p.loc[p["delivery_date"] == pd.Timestamp(d), "ts_utc"].min()
    ctx, fut, day = shadow.frames(p, d, "da")
    last = pd.Timestamp(ctx["timestamp"].max()).tz_localize("UTC")
    assert last == d_start - pd.Timedelta(hours=1)                         # DA: all of D-1, nothing of D
    assert fut.groupby("id").size().eq(24).all() and len(day) == 48
    ctx, fut, _ = shadow.frames(p, d, "rt")
    last = pd.Timestamp(ctx["timestamp"].max()).tz_localize("UTC")
    assert last + pd.Timedelta(hours=1) <= issue_utc(d) - pd.Timedelta(hours=1)   # RT: hour ending 04:00 ET at the latest
    assert ctx.groupby("id").size().eq(shadow.CONTEXT_DAYS * 24).all()
