"""M5 monthly products: issue rule, live vintage, decay fit, error-based quantiles."""
from datetime import date

import numpy as np
import pandas as pd
from lmpsignal import monthly as mo
from lmpsignal.config import INTERNAL_ZONES


def test_cutoff_moves_back_one_month_per_horizon():
    m = pd.Timestamp("2024-07-01")
    assert mo.cutoff(m, 1) == pd.Timestamp("2024-06-24")
    assert mo.cutoff(m, 6) == pd.Timestamp("2024-01-25")
    # all six target months of one vintage share the cutoff
    assert {mo.cutoff(m + pd.DateOffset(months=h - 1), h) for h in mo.HORIZONS} == {pd.Timestamp("2024-06-24")}


def test_latest_vintage():
    assert mo.latest_vintage(date(2026, 10, 5)) == (pd.Timestamp("2026-09-24"), pd.Timestamp("2026-10-01"))
    assert mo.latest_vintage(date(2026, 10, 25)) == (pd.Timestamp("2026-10-25"), pd.Timestamp("2026-11-01"))


def test_known_months_end_before_cutoff():
    a = pd.DataFrame({"month": pd.to_datetime(["2024-04-01", "2024-05-01", "2024-06-01"])})
    assert list(mo._known(a, pd.Timestamp("2024-06-24"))["month"].dt.month) == [4, 5]


def _synthetic(phi: float):
    """Monthly prices = anchor * exp(phi^lag * last deviation) with known structure."""
    rng = np.random.default_rng(1)
    months = pd.date_range("2015-01-01", "2020-12-01", freq="MS")
    rows = []
    for z in INTERNAL_ZONES[:2]:
        for p in ("peak", "offpeak"):
            dev = 0.0
            for m in months:
                dev = phi * dev + rng.normal(0, 0.2)
                rows.append({"month": m, "zone": z, "period": p, "total": 40 * np.exp(dev), "congestion": 5 + 10 * dev})
    a = pd.DataFrame(rows)
    g = pd.DataFrame({"trade_date": pd.date_range("2014-12-01", "2021-01-31", freq="D"), "hh": 3.0})
    return a, g


def test_decay_fit_finds_persistence_in_deviations():
    a, g = _synthetic(phi=0.8)
    pf = mo.decay_fit(mo.point_forecasts(a, g, ("m5_anchor", "m5_decay"), last_target=pd.Timestamp("2020-12-01")), a)
    late = pf[pf["month"] >= "2020-01-01"]
    h1 = late[late["h"] == 1]["phi"].mean()
    h6 = late[late["h"] == 6]["phi"].mean()
    assert 0.3 < h1 <= 1.0 and h6 < h1          # deviations decay with the horizon
    assert late["psi"].between(0, 1).all()


def test_quantiles_come_from_past_errors_only():
    a, g = _synthetic(phi=0.0)
    pf = mo.point_forecasts(a, g, ("m5_persist",), last_target=pd.Timestamp("2020-12-01"))
    d = mo.long_forecasts(pf, a, "m5_persist")
    early = d[(d["month"] < "2016-06-01") & (d["h"] == 6)]
    assert early["q50"].isna().all()                              # not enough past errors yet
    late = d[(d["month"] >= "2020-01-01") & d["q50"].notna()]
    assert (late["q05"] <= late["q50"]).all() and (late["q50"] <= late["q95"]).all()
