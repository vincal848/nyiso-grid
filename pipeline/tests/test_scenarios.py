"""M4 scenario generator and EVT splice: marginals invert, known dependence is recovered, independence finds none,
heavy tails are found, light tails are left alone."""
from datetime import date

import numpy as np
import pandas as pd
from lmpsignal import cv, scenarios
from lmpsignal.evaluate import QCOLS, crps_rows
from scipy.stats import kstest, norm, t

QS = scenarios.QS
DAYS, TEST0 = 450, 410
START = pd.Timestamp("2023-01-01")
FOLD = cv.Fold("syn", date(2023, 1, 1), (START + pd.Timedelta(days=TEST0 - 7)).date(),
               (START + pd.Timedelta(days=TEST0)).date(), (START + pd.Timedelta(days=DAYS)).date())


def _rows(q_scale: float, n: int) -> np.ndarray:
    return np.tile(norm.ppf(QS) * q_scale, (n, 1))


def _frame(rho: float, seed: int = 0, rt_t_df: float | None = None) -> pd.DataFrame:
    """One zone, 24 hours x DAYS; DA ~ N(0,1), RT ~ N(0,2) (or Student t if rt_t_df) with Gaussian-copula dependence."""
    rng = np.random.default_rng(seed)
    n = DAYS * 24
    z1 = rng.standard_normal(n)
    z2 = rho * z1 + np.sqrt(1 - rho**2) * rng.standard_normal(n)
    y_rt = 2 * z2 if rt_t_df is None else 2 * t.ppf(norm.cdf(z2), rt_t_df)
    w = pd.DataFrame({"delivery_date": np.repeat(START + pd.to_timedelta(np.arange(DAYS), "D"), 24),
                      "ts_utc": pd.date_range(START, periods=n, freq="h", tz="UTC"), "zone": "WEST",
                      "hour_local": np.tile(np.arange(24), DAYS), "y_da": z1, "y_rt": y_rt})
    for m, s in (("da", 1.0), ("rt", 2.0)):
        w[[f"{m}_{c}" for c in QCOLS]] = _rows(s, n)
    return w


def test_ppf_inverts_pit_including_tails():
    Q = _rows(1.0, 5)
    y = np.array([-4.0, -2.0, 0.3, 2.0, 5.0])
    u = scenarios.pit(y, Q)
    assert np.all((u > 0) & (u < 1)) and np.all(np.diff(u) > 0)
    assert np.allclose(scenarios.ppf(u[:, None], Q)[:, 0], y, atol=1e-6)


def test_pit_of_true_draws_is_uniform():
    y = np.random.default_rng(1).standard_normal(5000)
    assert kstest(scenarios.pit(y, _rows(1.0, 5000)), "uniform").pvalue > 0.01


def _spread_crps(w, method):
    df, diag = scenarios.spread_forecast(w, [FOLD], method, k=200)
    return crps_rows(df["y"].to_numpy(), df[QCOLS].to_numpy()).mean(), diag


def test_known_dependence_is_recovered_and_helps():
    w = _frame(rho=0.6)
    c_ind, _ = _spread_crps(w, "indep")
    for method in ("gauss", "emp"):
        c, diag = _spread_crps(w, method)
        assert abs(diag["rho_fit"].iloc[0] - 0.6) < 0.05
        assert abs(diag["spearman_samples"].iloc[0] - diag["spearman_realized"].iloc[0]) < 0.06
        assert c < 0.98 * c_ind


def test_independent_data_finds_no_dependence_and_no_gain():
    w = _frame(rho=0.0, seed=3)
    c_ind, _ = _spread_crps(w, "indep")
    for method in ("gauss", "emp"):
        c, diag = _spread_crps(w, method)
        assert abs(diag["rho_fit"].iloc[0]) < 0.05 and abs(diag["spearman_samples"].iloc[0]) < 0.05
        assert abs(c / c_ind - 1) < 0.01


def _rt_rows(heavy: bool) -> pd.DataFrame:
    w = _frame(0.0, seed=5, rt_t_df=2.5 if heavy else None)
    d = w[["delivery_date", "zone", "y_rt"]].rename(columns={"y_rt": "y"}).assign(scored=True)
    d[QCOLS] = w[[f"rt_{c}" for c in QCOLS]].to_numpy()
    return d


def _tail_stats(d, out):
    te = (d["delivery_date"] >= pd.Timestamp(FOLD.test_start)).to_numpy()
    y = d.loc[te, "y"].to_numpy()
    return [float((y > o.loc[te, "q99"].to_numpy()).mean()) for o in (d, out)] + \
           [crps_rows(y, o.loc[te, QCOLS].to_numpy()).mean() for o in (d, out)]


def test_gpd_splice_finds_heavy_tail():
    d = _rt_rows(heavy=True)
    miss0, miss1, _, _ = _tail_stats(d, scenarios.splice_frame(d, [FOLD]))
    assert miss0 > 0.02 and abs(miss1 - 0.01) < abs(miss0 - 0.01) / 2       # Gaussian q99 misses; splice fixes most


def test_gpd_splice_leaves_light_tail_alone():
    d = _rt_rows(heavy=False)
    miss0, miss1, c0, c1 = _tail_stats(d, scenarios.splice_frame(d, [FOLD]))
    assert abs(miss1 - miss0) < 0.005 and abs(c1 / c0 - 1) < 0.01
