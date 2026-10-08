"""Forward-test statistics: the test rejects rarely on signal-free days and finds a planted drift; power rises with n."""
import numpy as np
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
