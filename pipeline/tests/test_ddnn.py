"""M6 DDNN: JSU quantile function and NLL agree with sampling; skipped without the optional torch extra."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from lmpsignal.models.ddnn import _jsu_nll, jsu_quantiles  # noqa: E402


def test_jsu_quantiles_match_samples_and_nll_is_a_density():
    xi, lam, gam, dlt = 0.3, 1.2, -0.4, 1.5
    z = np.random.default_rng(0).normal(size=400_000)
    x = xi + lam * np.sinh((z - gam) / dlt)
    qs = np.array([0.05, 0.5, 0.95])
    q = jsu_quantiles(np.array([xi, lam, gam, dlt]), qs)
    assert np.allclose(q, np.quantile(x, qs), atol=0.02)
    grid = torch.linspace(-30, 30, 200_001, dtype=torch.float64)
    p = torch.exp(-_jsu_nll(grid, *(torch.tensor(v, dtype=torch.float64) for v in (xi, lam, gam, dlt))))
    assert abs(float(torch.trapezoid(p, grid)) - 1.0) < 1e-3
