"""End-to-end layer: live fold rule, forecast rows for future days, node mapping, DART positions."""
from datetime import date

import numpy as np
import pandas as pd
from lmpsignal import cv, nodes
from lmpsignal import dart_rules as dart
from lmpsignal.cv import month_fold
from lmpsignal.panel import future_grid


def test_live_month_fold_is_the_validation_rule():
    for f in cv.folds()[:12]:
        assert month_fold(f.test_start + pd.Timedelta(days=10).to_pytimedelta()) == f
    g = month_fold(date(2026, 10, 5))
    assert (g.test_start, g.test_end, g.train_end) == (date(2026, 10, 1), date(2026, 11, 1), date(2026, 9, 24))


def test_future_rows_follow_local_days_including_dst():
    g = future_grid(date(2026, 11, 1))
    day = g[g["ts_local"].dt.date == date(2026, 11, 1)]
    assert day.groupby("zone").size().eq(25).all()          # fall-back day
    g = future_grid(date(2027, 3, 14))
    day = g[g["ts_local"].dt.date == date(2027, 3, 14)]
    assert day.groupby("zone").size().eq(23).all()          # spring-forward day


def test_node_forecast_is_energy_plus_mapped_loss_and_congestion():
    ts = pd.Timestamp("2026-10-05 15:00", tz="UTC")
    zf = pd.DataFrame({"delivery_date": pd.Timestamp("2026-10-05"), "ts_utc": ts, "zone": "WEST", "market": "da",
                       "component": ["energy", "loss", "congestion", "total"], "mean": [40.0, 2.0, 5.0, 47.0]})
    b = pd.DataFrame({"ptid": [1, 2], "zone": "WEST", "a_loss": [0.5, 0.0], "b_loss": [1.0, 1.0],
                      "a_cong": [1.0, 0.0], "b_cong": [2.0, 1.0], "n_obs": 5000})
    out = nodes.node_forecast(zf, b, "da").set_index("ptid")
    assert np.isclose(out.loc[1, "total"], 40 + (0.5 + 2.0) + (1.0 + 2 * 5.0))
    assert np.isclose(out.loc[2, "total"], 47.0)              # a = 0, b = 1 reproduces the zone


def test_dart_positions_size_by_spread_over_uncertainty_and_net_costs():
    ts = pd.Timestamp("2026-10-05 15:00", tz="UTC")
    w = pd.DataFrame({"delivery_date": pd.Timestamp("2026-10-05"), "ts_utc": ts, "zone": ["WEST", "N.Y.C.", "CAPITL"],
                      "hour_local": 11, "mean_da": [50.0, 50.0, 50.0], "mean_rt": [40.0, 49.8, 70.0],
                      "q05_da": 40.0, "q95_da": 60.0, "q05_rt": 30.0, "q95_rt": 50.0,
                      "y_da": [52.0, 50.0, 55.0], "y_rt": [45.0, 51.0, 80.0]})
    lags = pd.DataFrame({"ts_utc": ts, "zone": ["WEST", "N.Y.C.", "CAPITL"], "lag_da_d1_total": 1.0, "lag_rt_d2_total": 0.0})
    out = dart.positions(w, lags).set_index("zone")
    sig = np.sqrt(2 * (20 / 3.29) ** 2)
    assert np.isclose(out.loc["WEST", "x_signal"], min(10 / sig, 1))                 # INC, partly sized
    assert out.loc["N.Y.C.", "x_signal"] == 0                                         # |spread| <= cost: no trade
    assert out.loc["CAPITL", "x_signal"] == -1                                        # strong DEC, capped
    assert np.isclose(out.loc["CAPITL", "pnl_signal"], -1 * (55 - 80) - dart.COST)


def test_spike_mix_moves_mean_and_upper_tail_by_the_spike_probability():
    from lmpsignal import postprocess
    from lmpsignal.config import QUANTILES
    from lmpsignal.evaluate import QCOLS

    ts = pd.Timestamp("2024-07-01 20:00", tz="UTC")
    k = {"delivery_date": pd.Timestamp("2024-07-01"), "ts_utc": ts, "zone": "N.Y.C.", "hour_local": 16,
         "market": "rt", "component": "total", "y": 50.0, "scored": True, "ref_mean": np.nan}
    qs = np.asarray(QUANTILES)
    base = pd.DataFrame([{**k, "mean": 50.0, **dict(zip(QCOLS, 40 + 20 * qs))}])
    spike = pd.DataFrame([{**k, "mean": 300.0, "p_spike": 0.1, **dict(zip(QCOLS, 200 + 200 * qs))}])
    out = postprocess.spike_mix(base, spike)
    assert np.isclose(out["mean"].iloc[0], 0.9 * 50 + 0.1 * 300)
    assert out["q50"].iloc[0] < 60 and out["q95"].iloc[0] > 200        # median stays in the base, top 5% in the spike
    zero = postprocess.spike_mix(base, spike.assign(p_spike=0.0))
    assert np.allclose(zero[QCOLS].to_numpy(), base[QCOLS].to_numpy(), atol=0.5)


def test_cli_and_scripts_import():
    """Catch syntax errors in modules the unit tests do not otherwise import."""
    import importlib
    import runpy  # noqa: F401
    from pathlib import Path

    importlib.import_module("lmpsignal.cli")
    root = Path(__file__).resolve().parents[2]
    compile((root / "scripts" / "daily.py").read_text(encoding="utf-8"), "daily.py", "exec")


def test_median_combination_ignores_one_blown_up_member():
    from lmpsignal import cv, postprocess

    f = cv.folds()[0]
    k = {"delivery_date": pd.Timestamp(f.test_start), "ts_utc": pd.Timestamp(f.test_start, tz="UTC"), "zone": "WEST",
         "hour_local": 0, "market": "da", "component": "total", "y": 50.0, "scored": True, "ref_mean": np.nan}
    parents = {n: pd.DataFrame([{**k, "mean": v}]) for n, v in (("a", 48.0), ("b", 900.0), ("c", 52.0))}
    out, _ = postprocess.combine(parents, [f], "median")
    assert out["mean"].iloc[0] == 52.0


def test_dart_v2_position_uses_correlation_and_cost_band():
    s, sig, x = dart.v2_position([50.0, 50.0, 50.3], [45.0, 45.0, 50.0], [10.0, 10.0, 10.0], [10.0, 10.0, 10.0],
                                 [0.0, 0.9, 0.0])
    assert np.allclose(s, [5.0, 5.0, 0.3])
    assert np.isclose(sig[0], np.sqrt(200)) and np.isclose(sig[1], np.sqrt(20))   # correlated errors shrink the scale
    assert np.isclose(x[0], 5 / np.sqrt(200)) and x[1] == 1.0                     # ... so the position grows, capped at 1
    assert x[2] == 0.0                                                            # inside the cost band: no trade


def test_dart_v2_rho_uses_only_the_prior_year():
    days = pd.date_range("2024-01-01", "2025-12-31", freq="D")
    r = np.random.default_rng(0).normal(size=len(days))
    resid = pd.DataFrame({"delivery_date": days, "zone": "WEST", "r_da": r,
                          "r_rt": np.where(days < "2025-01-01", r, -r)})                # sign flips in 2025
    assert np.isclose(dart.rho_by_zone(resid, pd.Timestamp("2025-01-01"))["WEST"], 1.0)
    assert np.isclose(dart.rho_by_zone(resid, pd.Timestamp("2026-01-01"))["WEST"], -1.0)
    assert dart.rho_by_zone(resid, pd.Timestamp("2023-06-01")).empty


def test_lear_parallel_retries_then_runs_in_process(monkeypatch):
    from concurrent.futures.process import BrokenProcessPool

    from lmpsignal.models import lear

    calls = {"n": 0}

    class Broken:
        def __init__(self, *a, **k):
            pass

        def __call__(self, gen):
            calls["n"] += 1
            raise BrokenProcessPool("worker died at start-up")

    monkeypatch.setattr(lear, "Parallel", Broken)
    assert lear._parallel(lambda a, b: a + b, [(1, 2), (3, 4)], n_jobs=2) == [3, 7]
    assert calls["n"] == 3                                          # two retries, then in-process
