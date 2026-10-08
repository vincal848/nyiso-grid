"""Model interface. A model is fit on a training panel and predicts a test panel.

predict() returns long format: delivery_date, ts_utc, zone, market, component, mean, <QCOLS>.
Quantile columns may be NaN for point-only models.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal.config import COMPONENTS, MARKETS
from lmpsignal.evaluate import QCOLS

ID_COLS = ["delivery_date", "ts_utc", "zone"]


class Model:
    name = "base"

    def config(self) -> dict:
        return {}

    def fit(self, train: pd.DataFrame) -> Model:
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError


class EmpiricalQuantiles:
    """Probabilistic wrapper: quantiles = point forecast + empirical residual quantiles from the training
    window, per (market, component, zone, hour_local). The standard 'naive distribution' benchmark."""

    def __init__(self, lookback_days: int = 365):
        self.lookback_days = lookback_days
        self.table: pd.DataFrame | None = None

    MIN_OBS = 60   # below this many residuals per (zone, hour) cell, use the zone's pooled-hours quantiles

    def fit(self, train_long: pd.DataFrame) -> EmpiricalQuantiles:
        cutoff = train_long["delivery_date"].max() - pd.Timedelta(days=self.lookback_days)
        t = train_long[(train_long["delivery_date"] > cutoff) & train_long["y"].notna() & train_long["mean"].notna()]
        resid = t.assign(r=t["y"] - t["mean"])
        qs = [float(c[1:]) / 100 for c in QCOLS]
        keys = ["market", "component", "zone", "hour_local"]
        cell = resid.groupby(keys)["r"].quantile(qs).unstack().set_axis(QCOLS, axis=1)
        n = resid.groupby(keys)["r"].size()
        pooled = resid.groupby(keys[:-1])["r"].quantile(qs).unstack().set_axis(QCOLS, axis=1)
        cell = cell[n.reindex(cell.index) >= self.MIN_OBS].reset_index()
        self.table, self.pooled = cell, pooled.reset_index()
        return self

    def apply(self, pred_long: pd.DataFrame) -> pd.DataFrame:
        base = pred_long.drop(columns=[c for c in QCOLS if c in pred_long])
        m = base.merge(self.table, on=["market", "component", "zone", "hour_local"], how="left")
        miss = m[QCOLS[0]].isna()
        if miss.any():
            fb = base[miss.to_numpy()].merge(self.pooled, on=["market", "component", "zone"], how="left")
            m.loc[miss, QCOLS] = fb[QCOLS].to_numpy()
        for c in QCOLS:
            m[c] = m["mean"] + m[c]
        q = m[QCOLS].to_numpy()
        m[QCOLS] = np.sort(q, axis=1)   # enforce monotone quantiles
        return m


def to_long(test: pd.DataFrame, means: dict[tuple[str, str], pd.Series]) -> pd.DataFrame:
    """Assemble long predictions from {(market, component): Series aligned to test}."""
    parts = []
    for m in MARKETS:
        for c in COMPONENTS:
            if (m, c) not in means:
                continue
            parts.append(test[ID_COLS + ["hour_local"]].assign(market=m, component=c, mean=means[(m, c)].to_numpy()))
    out = pd.concat(parts, ignore_index=True)
    for q in QCOLS:
        out[q] = np.nan
    return out


def truth_long(panel: pd.DataFrame) -> pd.DataFrame:
    """Targets in long format with scoring masks."""
    parts = []
    for m in MARKETS:
        mask = panel[f"score_{m}"].to_numpy()
        for c in COMPONENTS:
            parts.append(panel[ID_COLS + ["hour_local"]].assign(market=m, component=c, y=panel[f"{m}_{c}"].to_numpy(),
                                                                scored=mask))
    return pd.concat(parts, ignore_index=True)
