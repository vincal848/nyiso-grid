"""Post-processing: clipping equals VST-space clipping, weights/intervals use only the past, ACI restores coverage."""
import numpy as np
import pandas as pd
import pytest
from lmpsignal import cv
from lmpsignal import postprocess as pp
from lmpsignal.evaluate import QCOLS
from lmpsignal.models.lear import _ivst, _vst


def test_price_clip_equals_vst_clip():
    y_train = np.array([-50.0, 0.0, 3.0, 40.0, 900.0])
    med, mad = 3.0, 5.0
    z = _vst(y_train, med, mad)
    z_pred = np.array([-40.0, 1.0, 25.0])                   # extrapolates both ways in VST space
    via_vst = _ivst(np.clip(z_pred, z.min(), z.max()), med, mad)
    via_price = np.clip(_ivst(z_pred, med, mad), y_train.min(), y_train.max())
    assert np.allclose(via_vst, via_price)


def _long(days, zones=("WEST",), hours=(0,), market="da", comp="total"):
    rows = [(d, pd.Timestamp(d, tz="UTC") + pd.Timedelta(hours=h), z, h, market, comp)
            for d in days for z in zones for h in hours]
    return pd.DataFrame(rows, columns=pp.KEYS)


def test_combine_inv_mae_uses_only_earlier_folds():
    f = cv.folds()[3]
    days = pd.date_range(f.train_end - pd.Timedelta(days=60), f.test_end - pd.Timedelta(days=1), freq="D")
    base = _long(days).assign(y=0.0, scored=True, ref_mean=0.0)
    in_test = (base["delivery_date"] >= pd.Timestamp(f.test_start)).to_numpy()
    a = base.assign(mean=np.where(in_test, 100.0, 1.0))     # A: good in the past, terrible in the scored month
    b = base.assign(mean=np.where(in_test, 0.0, 10.0))      # B: worse in the past, perfect in the scored month
    _, log = pp.combine({"A": a, "B": b}, [f], weights="inv_mae")
    w = log[0]
    assert w["w_A"] == pytest.approx(10 / 11) and w["w_B"] == pytest.approx(1 / 11)   # from past MAE 1 vs 10 only


def test_aci_ignores_outcomes_newer_than_lag():
    days = pd.date_range("2023-01-01", periods=200, freq="D")
    df = _long(days).assign(mean=0.0, scored=True, ref_mean=0.0)
    rng = np.random.default_rng(0)
    df["y"] = rng.normal(0, 1, len(df))
    base = pp.calibrate_aci(df.copy(), min_obs=30)
    shocked = df.copy()
    shocked.loc[shocked["delivery_date"] >= days[150], "y"] = 1e6   # enormous outcomes from day 150 on
    out = pp.calibrate_aci(shocked, min_obs=30)
    j = out.index[out["delivery_date"] == days[151]][0]           # day 151 may only see outcomes up to day 149
    assert np.allclose(out.loc[j, QCOLS].to_numpy(float), base.loc[base["delivery_date"] == days[151], QCOLS].to_numpy(float)[0])


def test_aci_restores_coverage_under_volatility_shift():
    days = pd.date_range("2023-01-01", periods=900, freq="D")
    df = _long(days).assign(mean=0.0, scored=True, ref_mean=0.0)
    rng = np.random.default_rng(1)
    scale = np.where(np.arange(len(df)) < 450, 1.0, 3.0)           # volatility triples halfway through
    df["y"] = rng.normal(0, 1, len(df)) * scale
    out = pp.calibrate_aci(df, gamma=0.02)
    late = out[out["delivery_date"] >= days[600]]
    cov90 = np.mean((late["y"] >= late["q05"]) & (late["y"] <= late["q95"]))
    assert cov90 > 0.85                                            # static quantiles from the calm half would cover far less


def test_assemble_takes_each_component_from_its_parent_and_sums_total():
    days = pd.date_range("2024-01-01", periods=3, freq="D")
    def run(vals):
        parts = []
        for comp, v in vals.items():
            parts.append(_long(days, comp=comp).assign(mean=v, y=1.0, scored=True, ref_mean=0.0))
        return pd.concat(parts, ignore_index=True)
    a = run({"energy": 10.0, "loss": 1.0, "congestion": 5.0, "total": 16.0})
    b = run({"energy": 99.0, "loss": 9.0, "congestion": -2.0, "total": 106.0})
    out = pp.assemble({"A": a, "B": b}, {"energy": "A", "loss": "A", "congestion": "B"})
    got = out.groupby("component")["mean"].first().to_dict()
    assert got == {"energy": 10.0, "loss": 1.0, "congestion": -2.0, "total": 9.0}
