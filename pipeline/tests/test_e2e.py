"""End-to-end layer: live fold rule, forecast rows for future days, node mapping, DART positions."""
from datetime import date

import numpy as np
import pandas as pd

from lmpsignal import cv, dart, nodes
from lmpsignal.live import month_fold
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
