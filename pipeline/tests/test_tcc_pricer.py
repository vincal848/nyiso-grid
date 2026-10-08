"""TCC pricer: payoff, information cutoff, and the evaluation code on planted-signal and signal-free synthetic data."""
import numpy as np
import pandas as pd
from lmpsignal.tcc import evaluate as ev
from lmpsignal.tcc import pricer


def _world(seed=0):
    """480 days of hourly data: two constraints (summer-heavy A, flat B); POI 1 has no congestion, POI 2 = 0.5 A - 0.2 B."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-10-01", periods=480 * 24, freq="h", tz="UTC")
    grid = pricer.hour_grid(idx)
    summer = grid["d"].dt.month.isin([6, 7, 8]).to_numpy()
    mu_a = np.where(rng.random(len(idx)) < np.where(summer, 0.8, 0.1), rng.uniform(50, 100, len(idx)), 0.0)
    mu_b = np.where(rng.random(len(idx)) < 0.3, rng.uniform(50, 100, len(idx)), 0.0)
    cong = pd.DataFrame({1: 0.0, 2: 0.5 * mu_a - 0.2 * mu_b}, index=idx)
    sp = pd.concat([pd.DataFrame({"market": "da", "d": grid["d"].to_numpy(), "hr": grid["hr"].to_numpy(),
                                  "key": k, "mu": mu}) for k, mu in (("A|X", mu_a), ("B|X", mu_b))])
    return sp[sp["mu"] != 0], cong, grid, mu_a, mu_b


def test_structural_recovers_expected_payoff_and_seasonality():
    sp, cong, grid, mu_a, mu_b = _world()
    summer = pricer.Period(pd.Timestamp("2023-12-01"), pd.Timestamp("2024-06-01"), pd.Timestamp("2024-08-31"))
    f = pricer.structural(sp, cong, grid, summer, np.array([1]), np.array([2])).iloc[0]
    win = (grid["d"] >= summer.cutoff - pd.Timedelta(days=365)) & (grid["d"] < summer.cutoff)
    trailing = (0.5 * mu_a[win] - 0.2 * mu_b[win]).mean() * summer.n_hours
    assert abs(f["struct_trailing"] - trailing) < 0.02 * abs(trailing)
    assert f["struct_seasonal"] > 1.5 * f["struct_trailing"]          # summer months are where A binds
    assert f["struct_blend"] == (f["struct_trailing"] + f["struct_seasonal"]) / 2


def test_forecasts_ignore_everything_on_or_after_the_cutoff():
    sp, cong, grid, *_ = _world()
    p = pricer.Period(pd.Timestamp("2023-11-20"), pd.Timestamp("2023-12-01"), pd.Timestamp("2023-12-31"))
    poi, pow_ = np.array([1]), np.array([2])

    def forecasts(sp_, cong_):
        return (pricer.structural(sp_, cong_, grid, p, poi, pow_).to_numpy(),
                pricer.climatology(cong_, grid, p, poi, pow_), pricer.persistence(cong_, grid, p, poi, pow_))

    base = forecasts(sp, cong)
    late = grid["d"] >= p.cutoff
    shocked_cong = cong.copy()
    shocked_cong.loc[late.to_numpy(), 2] = 1e6
    shocked_sp = sp.copy()
    shocked_sp.loc[shocked_sp["d"] >= p.cutoff, "mu"] = 1e6
    for a, b in zip(base, forecasts(shocked_sp, shocked_cong), strict=True):
        np.testing.assert_array_equal(a, b)


def test_realized_payoff_is_sink_minus_source_and_needs_coverage():
    _, cong, grid, *_ = _world()
    p = pricer.Period(pd.Timestamp("2024-01-01"), pd.Timestamp("2023-03-10"), pd.Timestamp("2023-03-12"))
    y = pricer.realized(cong, grid, p, np.array([1, 2]), np.array([2, 1]))
    assert y[0] == -y[1] and y[0] == cong.loc[(grid["d"] >= p.start) & (grid["d"] <= p.end), 2].sum()
    cong.loc[(grid["d"] == p.start).to_numpy(), 2] = np.nan                     # a day of missing prices: > 1% of hours
    assert np.isnan(pricer.realized(cong, grid, p, np.array([1]), np.array([2]))[0])


def _obs(beta: float, seed: int, n_auc=40, n_path=60) -> pd.DataFrame:
    """Clearing price c; realized y = c + beta*z + noise; the pricer sees z with noise: f = c + z + noise."""
    rng = np.random.default_rng(seed)
    a = np.repeat(np.arange(n_auc), n_path)
    c = rng.normal(0, 200, len(a))
    z = rng.normal(0, 100, len(a))
    return pd.DataFrame({"auction": a, "path": np.tile(np.arange(n_path), n_auc), "months": 6.0, "c": c,
                         "y": c + beta * z + rng.normal(0, 150, len(a)), "f": c + z + rng.normal(0, 60, len(a)),
                         "persistence": c + rng.normal(0, 200, len(a))})


def test_evaluation_finds_a_planted_edge():
    s = ev.summarize(_obs(beta=1.0, seed=1), "f", ("c", "persistence"), B=400)
    assert s["slope"]["t"] > 5 and 0.5 < s["slope"]["slope"] < 1.5
    assert s["pnl_path_boot"]["mean"] > 0 and s["pnl_path_boot"]["p"] < 0.01 and s["pnl_auction_boot"]["p"] < 0.01
    assert s["placebo"]["p"] < 0.01 and s["placebo"]["null_mean"] < s["placebo"]["observed"]
    assert s["dm"]["c"]["p_a_better"] < 0.01                                 # f is closer to y than c


def test_evaluation_finds_nothing_in_signal_free_data():
    """beta = 0: y does not depend on the pricer's signal. Rejections at 5% must be rare, and the shuffled-label
    null must not look different from the real forecast."""
    rej = []
    for seed in range(30):
        s = ev.summarize(_obs(beta=0.0, seed=seed), "f", ("c",), B=300)
        rej.append((s["pnl_path_boot"]["p"] < 0.05, s["placebo"]["p"] < 0.05, s["slope"]["t"] > 1.96))
    assert np.mean(rej, axis=0).max() <= 0.2
