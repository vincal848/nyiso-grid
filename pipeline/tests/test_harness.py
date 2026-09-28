"""M1 harness tests: CV calendar, holdout guard, as-of guarantees, metrics, naive baselines."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from lmpsignal import config, cv
from lmpsignal.evaluate import QCOLS, crps, diebold_mariano, pinball
from lmpsignal.panel import FEATURES, KEYS, MASKS, TARGETS


# ------------------------------------------------------------------ CV and holdout

def test_validation_folds_are_36_months_with_embargo():
    fs = cv.folds()
    assert len(fs) == 36
    assert fs[0].name == "2022-10" and fs[-1].name == "2025-09"
    for f in fs:
        assert f.train_end == f.test_start - timedelta(days=config.EMBARGO_DAYS)
        assert f.train_start == config.BURN_IN_START
        assert f.test_end <= config.HOLDOUT_START
    for a, b in zip(fs, fs[1:]):
        assert a.test_end == b.test_start            # contiguous, non-overlapping test blocks


def test_fixed_window_folds():
    f = cv.folds(window_days=365)[-1]
    assert (f.train_end - f.train_start).days == 365


def test_inner_folds_stay_inside_outer_training():
    outer = cv.folds()[10]
    for inner in cv.inner_folds(outer):
        assert inner.test_end <= outer.train_end
        assert inner.train_end < inner.test_start


def test_holdout_is_locked(monkeypatch):
    monkeypatch.delenv("LMP_UNLOCK_HOLDOUT", raising=False)
    with pytest.raises(config.HoldoutLocked):
        cv.holdout_fold()
    with pytest.raises(config.HoldoutLocked):
        cv.folds(end=date(2026, 1, 1))
    monkeypatch.setenv("LMP_UNLOCK_HOLDOUT", "I_AM_RUNNING_M7")
    assert cv.holdout_fold().test_start == config.HOLDOUT_START


# ------------------------------------------------------------------ panel

def test_feature_docs_cover_every_panel_column():
    duckdb = pytest.importorskip("duckdb")
    if not config.FEATURES_DB.exists():
        pytest.skip("panel not built")
    con = duckdb.connect(str(config.FEATURES_DB), read_only=True)
    cols = [r[0] for r in con.execute("DESCRIBE panel").fetchall()]
    undocumented = [c for c in cols if c not in FEATURES and c not in KEYS + TARGETS + MASKS and not c.startswith("_avail_")]
    assert undocumented == []


def test_panel_is_point_in_time_and_additive():
    duckdb = pytest.importorskip("duckdb")
    if not config.FEATURES_DB.exists():
        pytest.skip("panel not built")
    from lmpsignal.panel import check_asof

    con = duckdb.connect(str(config.FEATURES_DB), read_only=True)
    assert all(v == 0 for v in check_asof(con).values())
    # every audit column must actually be populated somewhere (a NULL audit proves nothing)
    for c in check_asof(con):
        assert con.execute(f"SELECT count({c}) FROM panel").fetchone()[0] > 0, c
    bad = con.execute("""SELECT count(*) FROM panel WHERE abs(da_energy + da_loss + da_congestion - da_total) > 0.011
                         OR abs(rt_energy + rt_loss + rt_congestion - rt_total) > 0.011""").fetchone()[0]
    assert bad == 0


# ------------------------------------------------------------------ metrics

def test_crps_of_point_forecast_equals_mae():
    rng = np.random.default_rng(0)
    y, f = rng.normal(50, 10, 2000), rng.normal(50, 10, 2000)
    Q = np.repeat(f[:, None], len(config.QUANTILES), axis=1)
    assert crps(y, Q) == pytest.approx(np.mean(np.abs(y - f)), rel=1e-9)


def test_calibrated_quantiles_beat_point_forecast():
    rng = np.random.default_rng(1)
    y = rng.normal(0, 1, 20000)
    from statistics import NormalDist

    q = np.array([NormalDist().inv_cdf(t) for t in config.QUANTILES])
    good = crps(y, np.repeat(q[None, :], len(y), axis=0))
    point = crps(y, np.zeros((len(y), len(config.QUANTILES))))
    assert good < point
    assert good == pytest.approx(0.5642, abs=0.02)      # CRPS of N(0,1) forecast for N(0,1) outcomes = 1/sqrt(pi)
    assert pinball(y, np.repeat(q[None, :], len(y), axis=0)).shape == (len(config.QUANTILES),)


def test_diebold_mariano_detects_better_model():
    rng = np.random.default_rng(2)
    days = pd.Series(np.repeat(np.arange(200), 24))
    y = rng.normal(0, 1, len(days))
    a = pd.Series(np.abs(y - (y + rng.normal(0, 0.5, len(y)))))
    b = pd.Series(np.abs(y - (y + rng.normal(0, 1.0, len(y)))))
    assert diebold_mariano(a, b, days)["p_a_better"] < 0.01
    assert diebold_mariano(b, a, days)["p_a_better"] > 0.99


def test_qcols_are_sorted_and_named():
    assert QCOLS[0] == "q01" and QCOLS[-1] == "q99" and "q50" in QCOLS


# ------------------------------------------------------------------ naive baselines

def test_naive_rules_use_the_right_lags():
    from lmpsignal.models.naive import Naive

    df = pd.DataFrame({
        "delivery_date": pd.to_datetime(["2024-06-04", "2024-06-08"]),   # Tuesday, Saturday
        "ts_utc": pd.to_datetime(["2024-06-04 16:00", "2024-06-08 16:00"], utc=True), "zone": "WEST",
        "hour_local": 12, "dow": [2, 6],
        **{f"lag_da_d1_{c}": [10.0, 11.0] for c in config.COMPONENTS},
        **{f"lag_da_d7_{c}": [70.0, 77.0] for c in config.COMPONENTS},
        **{f"lag_rt_d2_{c}": [20.0, np.nan] for c in config.COMPONENTS},
    })
    pick = lambda rule: Naive(rule)._point(df, "total").tolist()  # noqa: E731
    assert pick("persist_da_d1") == [10.0, 11.0]
    assert pick("weekly_da_d7") == [70.0, 77.0]
    assert pick("lago_naive") == [10.0, 77.0]          # Tue -> D-1, Sat -> D-7
    assert pick("persist_rt_d2") == [20.0, 11.0]       # missing RT falls back to D-1


def test_coverage_tests_behave():
    from lmpsignal.evaluate import christoffersen_ind, kupiec_pof

    rng = np.random.default_rng(0)
    assert kupiec_pof(rng.random(20000) < 0.10, 0.10)["p_value"] > 0.01
    assert kupiec_pof(rng.random(20000) < 0.13, 0.10)["p_value"] < 1e-6
    assert christoffersen_ind(np.repeat(rng.random(3000) < 0.1, 5)) < 1e-6      # clustered misses
    assert christoffersen_ind(rng.random(20000) < 0.1) > 0.01                 # independent misses
