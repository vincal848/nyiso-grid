"""Load correction: training never reaches the scored block; the correction is applied multiplicatively."""
import numpy as np
import pandas as pd
from lmpsignal import cv, loadfix
from lmpsignal.config import EMBARGO_DAYS


class _Spy:
    name = "spy"

    def __init__(self):
        self.seen = []

    def config(self):
        return {}

    def fit(self, d):
        self.seen.append(d["delivery_date"].max())
        return self

    def predict(self, d):
        return np.full(len(d), 0.10)

    def importance(self):
        return None


def _frame(days):
    rows = []
    for d in days:
        for h in range(24):
            for z in ("WEST", "N.Y.C."):
                rows.append({"delivery_date": d, "ts_utc": pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=h), "zone": z,
                             "hour_local": h, "load_fcst_zone": 1000.0, "load_actual": 1050.0, "isolf_d1": 1020.0,
                             "hrrr_temp_zone": 20.0, "r": 0.05, "d_temp": 0.0, "d_cdh": 0.0, "d_hdh": 0.0})
    return pd.DataFrame(rows)


def test_training_rows_end_before_the_embargo_and_correction_is_multiplicative(monkeypatch):
    days = pd.date_range("2021-10-01", "2023-01-31", freq="D")
    spy = _Spy()
    monkeypatch.setattr(loadfix, "frame", lambda p: _frame(days))
    monkeypatch.setitem(loadfix.MODELS, "spy", lambda: spy)
    folds = cv.folds()[:3]
    loadfix.run("spy", pd.DataFrame(), folds=folds, log=False)
    for f, last in zip(folds, spy.seen):
        assert last < pd.Timestamp(f.test_start) - pd.Timedelta(days=EMBARGO_DAYS - 1)
    # 10% correction on a 1000 MW forecast -> 1100 MW
    t = _frame(days[:1]).assign(r_hat=0.10)
    t["pred"] = t["load_fcst_zone"] * (1 + t["r_hat"])
    assert np.allclose(t["pred"], 1100.0)
    s = loadfix._scores(t.assign(isolf_d2=t["load_fcst_zone"]))
    assert np.isclose(s.loc[s["zone"] == "ALL", "mape"].iloc[0], 50 / 1050)
    assert "NYISO" not in set(s["zone"])                                 # total needs all 11 zones


def test_oos_months_are_predicted_from_data_ending_before_the_embargo():
    from datetime import timedelta

    folds = loadfix.oos_folds("2022-01", end="2023-01-01")
    assert [f.name for f in folds][:2] == ["2022-01", "2022-02"] and folds[-1].name == "2022-12"
    for f in folds:
        assert f.train_end <= f.test_start - timedelta(days=EMBARGO_DAYS)


def test_feature_sets_stay_frozen_when_columns_are_added():
    from lmpsignal.panel import FEATURE_SETS

    v1, v2, v3 = (set(FEATURE_SETS[k]) for k in ("v1", "v2", "v3"))
    assert not any(c.startswith(("hrrr_", "load_fix", "load_surprise")) or c == "temp_fcst_zone_isolf" for c in v1)
    assert v1 < v2 < v3
    assert not any(c.startswith(("load_fix", "load_surprise")) for c in v2)
    assert len(FEATURE_SETS["v1"]) == 36                     # the M2-M3 panel; changing it invalidates old configs
