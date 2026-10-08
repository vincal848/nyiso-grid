"""Forward-test statistics: the test rejects rarely on signal-free days and finds a planted drift; power rises with n."""
import numpy as np
import pandas as pd
from lmpsignal import dart_forward as f


def _days(n: int, drift: float, seed: int) -> np.ndarray:
    r = np.random.default_rng(seed)
    return drift + r.standard_t(3, n) * 100.0


def test_null_rejects_about_five_percent():
    rej = [f.bootstrap_p(_days(120, 0.0, s), n_boot=400, seed=s) < 0.05 for s in range(200)]
    assert 0.01 <= np.mean(rej) <= 0.12                      # nominal 5%, heavy-tailed days, small sample


def test_planted_drift_is_found_and_power_rises_with_n():
    assert np.mean([f.bootstrap_p(_days(365, 25.0, s), n_boot=400, seed=s) < 0.05 for s in range(40)]) > 0.7
    c = f.power_curve(_days(1000, 25.0, 0), [30, 120, 480], n_sim=400)
    assert c["power"].is_monotonic_increasing and c["power"].iloc[-1] > 0.7
    assert f.required_n(c) <= 480
    flat = f.power_curve(_days(1000, 0.0, 1), [120, 480], n_sim=400)
    assert flat["power"].max() < 0.15                       # signal-free: power stays at the size


def _positions(days, created_hours_before=6):
    ts = [pd.Timestamp(d, tz="America/New_York").tz_convert("UTC") + pd.Timedelta(hours=h) for d in days for h in range(24)]
    n = len(ts) // len(days)
    rows = pd.DataFrame({"delivery_date": np.repeat(pd.to_datetime(days), 24), "ts_utc": ts, "zone": "WEST",
                         "created_utc": [t - pd.Timedelta(hours=24 + created_hours_before) for t in ts]})
    return pd.concat([rows.assign(zone=f"Z{i}") for i in range(11)], ignore_index=True), n


def test_counted_days_exclude_early_late_filled_and_unsettled():
    days = ["2026-10-08", "2026-10-09", "2026-10-10", "2026-10-11"]
    x, _ = _positions(days)
    out = x[["ts_utc", "zone"]].drop_duplicates().assign(y_da=50.0, y_rt=45.0)
    out.loc[out["ts_utc"] >= pd.Timestamp("2026-10-11", tz="America/New_York").tz_convert("UTC"), "y_rt"] = np.nan   # not settled
    late = x["delivery_date"] == "2026-10-10"
    x.loc[late, "created_utc"] = x.loc[late, "ts_utc"]                                                         # filled after the day began
    got = f.counted(x, out, pd.Timestamp("2026-10-09"))
    assert sorted(got["delivery_date"].unique()) == [pd.Timestamp("2026-10-09")]       # 10-08 before start, 10-10 late, 10-11 unsettled


def test_evaluate_waits_then_scores_once_and_flags_gaps():
    idx = pd.date_range("2026-10-09", periods=400, freq="D")
    daily = pd.Series(_days(400, 0.0, 3), index=idx)
    start, today = idx[0], idx[-1]
    w = f.evaluate(daily.iloc[:100], start, idx[99])
    assert w["status"] == "waiting" and w["n_days"] == 100 and "p_value" not in w          # no early look
    s = f.evaluate(daily, start, today)
    assert s["status"] == "scored" and s["n_days"] == 365 and 0 <= s["p_value"] <= 1
    gappy = daily.iloc[::2].iloc[:365]                                                       # every other day: 50% coverage
    gappy = pd.Series(np.tile(gappy.to_numpy(), 2)[:365], index=pd.date_range("2026-10-09", periods=365, freq="2D"))
    assert f.evaluate(gappy, start, today)["status"] == "invalid"
    planted = f.evaluate(pd.Series(_days(400, 120.0, 4), index=idx), start, today)
    assert planted["status"] == "scored" and planted["p_value"] < 0.05 and planted["verdict"].startswith("forward pass")
