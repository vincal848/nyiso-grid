"""DART pricer: clearing is exact; a planted edge is priced and earns after costs; in an efficient world (RT = DA + noise) and with
the forecast's RT shift shuffled across rows nothing is found; risk limits only scale down; the shuffled-outcome null fails."""
import numpy as np
import pandas as pd
from lmpsignal import dart_pricer as dp
from lmpsignal import dart_rules as dr
from lmpsignal.evaluate import QCOLS
from scipy.stats import norm

QS = np.asarray([0.01, *[round(0.05 * i, 2) for i in range(1, 20)], 0.99])
S_DA, S_E, N = 8.0, 10.0, 3000
RHO = S_DA / np.hypot(S_DA, S_E)                       # corr(DA, RT) when RT = DA + independent noise


def _world(planted: bool, seed: int = 0, shuffle_forecast: bool = False) -> pd.DataFrame:
    """One zone, N hours. Truth: DA = 40 + 8 z, RT = DA + delta + e. The forecaster knows delta iff `planted` (its RT quantiles
    centre on 40 + delta); with `shuffle_forecast` that shift is attached to the wrong rows."""
    r = np.random.default_rng(seed)
    delta = r.normal(0, 6, N)
    y_da = 40 + S_DA * r.standard_normal(N)
    y_rt = y_da + delta + S_E * r.standard_normal(N)
    shift = (r.permutation(delta) if shuffle_forecast else delta) if planted else np.zeros(N)
    w = pd.DataFrame({"delivery_date": pd.Timestamp("2024-01-01") + pd.to_timedelta(np.arange(N) // 24, "D"),
                      "ts_utc": pd.date_range("2024-01-01", periods=N, freq="h", tz="UTC"), "zone": "WEST",
                      "hour_local": np.arange(N) % 24, "y_da": y_da, "y_rt": y_rt})
    z = norm.ppf(QS)
    w[[f"da_{c}" for c in QCOLS]] = 40 + S_DA * z
    w[[f"rt_{c}" for c in QCOLS]] = (40 + shift)[:, None] + np.hypot(S_DA, S_E) * z
    return w


def _total(w: pd.DataFrame, kind: str, seed: int = 1) -> float:
    p = dp.price_rows(w, {"WEST": RHO}, kind, 300, np.random.default_rng(seed))
    p = dp.apply_limits(p, dp.NO_LIMITS)
    return float(dp.realize(p, p["y_da"].to_numpy(), p["y_rt"].to_numpy())["pnl"].sum())


def test_clearing_is_exact():
    p = pd.DataFrame({"side": [1, 1, -1, -1, 0], "bid_price": [50.0, 50.0, 50.0, 50.0, np.nan], "x": 2.0})
    out = dp.realize(p, np.array([49.0, 51.0, 49.0, 51.0, 60.0]), np.array([45.0, 45.0, 55.0, 55.0, 0.0]), cost=0.5)
    assert out["x_eff"].tolist() == [0.0, 2.0, 2.0, 0.0, 0.0]                  # INC clears iff DA >= bid, DEC iff DA <= bid
    assert np.allclose(out["pnl"], [0.0, 2 * (6 - 0.5), 2 * (6 - 0.5), 0.0, 0.0])


def test_fixed_bids_always_clear():
    da, rt = np.full((2, 50), 60.0), np.full((2, 50), 40.0)
    out = dp.price(da, rt, "taker")
    assert out["side"].tolist() == [1, 1] and np.isinf(out["bid_price"]).all() and (out["p_clear"] == 1).all()


def test_planted_edge_earns_and_efficient_world_does_not():
    for kind in ("taker", "bidcurve"):
        planted, none = _total(_world(True), kind), _total(_world(False), kind)
        assert planted > 500 and none <= 0.05 * planted, (kind, planted, none)   # the cost makes "nothing to find" negative
        assert _total(_world(True, shuffle_forecast=True), kind) <= 0.05 * planted     # shuffled scenario assignment: no edge


def test_shuffled_outcome_null_fails_for_a_real_edge_only():
    def check(w):
        p = dp.apply_limits(dp.price_rows(w, {"WEST": RHO}, "bidcurve", 300, np.random.default_rng(1)), dp.NO_LIMITS)
        real = dp.realize(p, p["y_da"].to_numpy(), p["y_rt"].to_numpy())["pnl"].sum()
        return real, np.quantile(dp.shuffled_totals(p, 40), 0.95)
    real, null95 = check(_world(True))
    assert real > null95
    real, null95 = check(_world(False))
    assert real <= null95


def test_limits_only_scale_down():
    p = pd.DataFrame({"delivery_date": pd.to_datetime(["2024-01-01"] * 3 + ["2024-01-02"]), "x_pre": [2.0, 1.0, 0.5, 1.0],
                      "loss99": 100.0, "p_clear": 0.5, "da_q99": 100.0})
    out = dp.apply_limits(p, dp.Limits(mw_cap=1.0, daily_loss=150.0, collateral=1e9))
    d1 = out[out["delivery_date"] == "2024-01-01"]
    assert np.isclose((d1["x"] * d1["loss99"]).sum(), 150.0) and (out["x"] <= 1.0).all()   # day 1 scaled to the limit
    assert out.loc[3, "x"] == 1.0                                                          # day 2 is under every limit
    off = dp.apply_limits(p, dp.NO_LIMITS)
    assert (off["limit_scale"] == 1.0).all() and off["x"].tolist() == [1.0, 1.0, 0.5, 1.0]  # cap still applies


def test_naive_last_spread_uses_the_spread_two_days_back():
    ts = pd.date_range("2024-01-01", periods=72, freq="h", tz="UTC")
    w = pd.DataFrame({"ts_utc": ts, "zone": "WEST", "y_da": 50.0, "y_rt": np.r_[np.full(24, 60.0), np.full(24, 40.0), np.full(24, 0.0)]})
    x = dp.naive_last_spread(w)
    assert x.iloc[:48].eq(0).all() and x.iloc[48:].eq(-1).all()                 # day 1 spread was -10: DEC on day 3


def test_paper_pnl_uses_settled_hours_only():
    ts = pd.date_range("2024-01-01", periods=2, freq="h", tz="UTC")
    x = pd.DataFrame({"delivery_date": pd.Timestamp("2024-01-01"), "ts_utc": ts, "zone": "WEST", "x_mw": [1.0, -1.0]})
    out = pd.DataFrame({"ts_utc": ts, "zone": "WEST", "y_da": [50.0, 50.0], "y_rt": [45.0, np.nan]})
    g = dr.paper_pnl(x, out)
    assert np.isclose(g["pnl"].iloc[0], 5 - dr.COST) and g["mwh"].iloc[0] == 1.0
