"""M2 tests: daily grid DST handling, LEAR inputs never look ahead, OOS quantiles use only the past."""
import numpy as np
import pandas as pd
import pytest

from lmpsignal import config, cv
from lmpsignal.models import daygrid as dg


def _panel_day(date, hours, value=lambda h: float(h)):
    return pd.DataFrame({"zone": "WEST", "delivery_date": pd.Timestamp(date), "hour_local": hours,
                         "x": [value(h) for h in hours]})


def test_grid_handles_dst_days():
    fall = _panel_day("2025-11-02", [0, 1, 1, *range(2, 24)])          # 25 hours, hour 1 twice
    fall.loc[2, "x"] = 3.0                                               # second hour-1 value
    spring = _panel_day("2026-03-08", [0, 1, *range(3, 24)])             # 23 hours, no hour 2
    g = dg.grid(pd.concat([fall, spring]), "x")
    assert g.loc[("WEST", pd.Timestamp("2025-11-02")), 1] == pytest.approx(2.0)   # averaged (1 + 3) / 2
    assert g.loc[("WEST", pd.Timestamp("2026-03-08")), 2] == pytest.approx(2.0)   # interpolated between 1 and 3
    assert g.shape[1] == 24


def test_lag_is_by_calendar_day_not_row():
    df = pd.concat([_panel_day("2024-01-01", range(24), lambda h: 1.0),
                    _panel_day("2024-01-03", range(24), lambda h: 3.0)])      # 2024-01-02 missing
    g = dg.grid(df, "x")
    idx = pd.MultiIndex.from_tuples([("WEST", pd.Timestamp("2024-01-03"))], names=["zone", "delivery_date"])
    lag1 = dg.lagged(g, 1, idx)
    assert lag1.isna().all().all()                                      # D-1 is missing, not the day before that
    assert (dg.lagged(g, 2, idx) == 1.0).all().all()


def test_lear_price_inputs_only_use_published_days():
    from lmpsignal.models.lear import Design

    days = pd.date_range("2024-01-01", "2024-02-29", freq="D")
    rows = []
    for d in days:
        for h in range(24):
            v = float(d.dayofyear)            # price = day-of-year, so a lag's value reveals which day it used
            rows.append({"zone": "WEST", "delivery_date": d, "hour_local": h, "dow": d.isoweekday(), "is_holiday": False,
                         "gas_hh": 3.0, "load_fcst_zone": 1000.0, "load_fcst_nyiso": 15000.0, "temp_fcst_zone": 5.0,
                         "temp_fcst_nyiso": 5.0, **{f"{m}_{c}": v for m in config.MARKETS for c in config.COMPONENTS}})
    D = Design(pd.DataFrame(rows))
    target = pd.DatetimeIndex([pd.Timestamp("2024-02-20")])
    X = D.features("rt", "total", "WEST", target, energy=False)
    doy = target[0].dayofyear
    for lag in (1, 2, 3, 7):
        assert (X[[c for c in X if c.startswith(f"da_d{lag}_h")]] == doy - lag).all().all()
    for lag in (2, 3):
        assert (X[[c for c in X if c.startswith(f"rt_d{lag}_h")]] == doy - lag).all().all()
    assert not any(c.startswith(("da_d0", "rt_d0", "rt_d1_")) for c in X)   # no same-day DA, no D-1 RT


def test_oos_quantiles_only_use_earlier_folds():
    from lmpsignal.runner import _oos_quantiles

    f = cv.folds()[5]
    hist = pd.DataFrame({"delivery_date": pd.to_datetime([f.train_end - pd.Timedelta(days=1), f.test_start]),
                         "market": "da", "component": "total", "zone": "WEST", "hour_local": 0,
                         "y": [10.0, 1000.0], "mean": [0.0, 0.0], "scored": True})
    pred = pd.DataFrame({"delivery_date": [pd.Timestamp(f.test_start)], "ts_utc": [pd.Timestamp(f.test_start, tz="UTC")],
                         "zone": "WEST", "hour_local": 0, "market": "da", "component": "total", "mean": [50.0]})
    out = _oos_quantiles(pred, [hist], f, 365)
    q = out.filter(regex=r"^q\d\d$").iloc[0]
    assert np.allclose(q, 60.0)          # only the pre-embargo residual (10) is used; the in-fold 1000 is not


def test_structural_congestion_features_never_see_unpublished_shadow_prices():
    from lmpsignal.structural.congestion import StructuralCongestion

    days = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    rng = np.random.default_rng(0)
    rows = [{"market": mk, "d": d, "hr": h, "key": k, "mu": float(rng.normal(10, 3))}
            for mk in ("da", "rt") for d in days for h in range(24) for k in ("A|BASE", "B|BASE") if rng.random() < 0.3]
    sp = pd.DataFrame(rows)
    M = StructuralCongestion(k=2)
    idx = pd.MultiIndex.from_product([days, range(24)], names=["delivery_date", "hour_local"])
    M.sys = pd.DataFrame({"load_fcst_nyiso": 1.0, "temp_fcst_nyiso": 1.0, "gas_hh": 1.0, "dow": 1, "month": 1}, index=idx)
    M.outages = pd.DataFrame({"n_outages": 1, "n_outages_345": 1}, index=days)
    target = pd.DatetimeIndex([pd.Timestamp("2024-03-15")])
    for market, unpublished in (("da", [0]), ("rt", [0, 1])):
        M.sp = sp
        base = M._features(market, ["A|BASE", "B|BASE"], target)
        shocked = sp.copy()
        for back in unpublished:                       # overwrite days that are NOT known at the 05:00 D-1 issue
            day = target[0] - pd.Timedelta(days=back)
            shocked.loc[(shocked["d"] == day) & (shocked["market"] == market), "mu"] = 1e6
        if market == "rt":                             # DA of day D itself is also unpublished at issue
            shocked.loc[(shocked["d"] == target[0]) & (shocked["market"] == "da"), "mu"] = 1e6
        M.sp = shocked
        pd.testing.assert_frame_equal(base, M._features(market, ["A|BASE", "B|BASE"], target))
