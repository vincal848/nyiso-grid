"""Overfitting diagnostics: reproduce the papers' numbers and sanity-check behaviour."""
import math

import numpy as np
import pandas as pd
import pytest

from lmpsignal import overfit as of


def test_dsr_reproduces_bailey_lopez_de_prado_2014_example():
    """DSR paper, 'A numerical example': N=100, V[SR]=1/2 (annualized), T=1250 daily obs, skew=-3,
    kurt=10, selected SR=2.5 annualized -> DSR ~= 0.90; with N=46 -> 0.9505. SR non-annualized (250/yr)."""
    sr = 2.5 / math.sqrt(250)
    var_sr = 0.5 / 250
    assert of.dsr(sr, 1250, -3, 10, var_sr, 100) == pytest.approx(0.90, abs=0.005)
    assert of.dsr(sr, 1250, -3, 10, var_sr, 46) == pytest.approx(0.9505, abs=0.001)


def test_psr_basics():
    assert of.psr(0.0, 500, 0, 3) == pytest.approx(0.5)
    assert of.psr(0.1, 500, 0, 3) > of.psr(0.1, 100, 0, 3)        # longer track record -> more confidence
    assert of.psr(0.1, 500, -2, 10) < of.psr(0.1, 500, 0, 3)       # negative skew / fat tails -> less


def test_min_track_record_consistent_with_psr():
    sr, skew, kurt = 0.08, -0.5, 6
    n = of.min_track_record(sr, skew, kurt, confidence=0.95)
    assert of.psr(sr, math.ceil(n) + 1, skew, kurt) >= 0.95 - 1e-9
    assert of.psr(sr, math.floor(n) - 1, skew, kurt) < 0.95


def test_expected_max_sr_grows_with_trials():
    assert of.expected_max_sr(0.01, 1) == 0.0
    assert of.expected_max_sr(0.01, 10) < of.expected_max_sr(0.01, 1000)


def test_implied_trials_between_one_and_m():
    rng = np.random.default_rng(0)
    base = rng.normal(size=500)
    df = pd.DataFrame({f"t{i}": base + rng.normal(scale=0.5, size=500) for i in range(5)})
    n_hat, rho = of.implied_independent_trials(df)
    assert 1 < n_hat < 5 and 0 < rho < 1


def test_pbo_near_half_for_pure_noise_and_near_zero_for_real_edge():
    # Under pure noise PBO is 0.5 in expectation; a single realization varies a lot (IS/OOS halves are
    # complements of one finite sample), so average over realizations.
    v = [of.pbo_cscv(pd.DataFrame(np.random.default_rng(s).normal(size=(800, 20))), S=10)["pbo"] for s in range(30)]
    assert 0.4 < np.mean(v) < 0.6
    noise = pd.DataFrame(np.random.default_rng(1).normal(size=(1600, 20)))
    r = of.pbo_cscv(noise, S=16)
    assert r["combinations"] == math.comb(16, 8)
    edge = noise.copy()
    edge[0] += 0.3                                                   # one trial is genuinely better
    assert of.pbo_cscv(edge, S=16)["pbo"] < 0.05


def test_spa_detects_a_real_improvement_and_not_noise():
    rng = np.random.default_rng(2)
    T = 800
    noise = pd.DataFrame(rng.normal(size=(T, 6)))
    assert of.spa_test(noise, B=500)["p_spa_consistent"] > 0.1
    better = noise.copy()
    better[3] += 0.25
    res = of.spa_test(better, B=500)
    assert res["p_spa_consistent"] < 0.01
    assert res["p_spa_lower"] <= res["p_spa_consistent"] <= res["p_spa_upper"] + 1e-12


def test_multiple_testing_adjustments():
    p = pd.Series({"a": 0.001, "b": 0.01, "c": 0.04, "d": 0.3})
    h, b = of.holm(p), of.bhy(p)
    assert (h >= p).all() and (b >= p).all()
    assert h["a"] == pytest.approx(0.004)
    assert h.is_monotonic_increasing                                 # order preserved for sorted input
