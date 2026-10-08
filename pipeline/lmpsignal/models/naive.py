"""Naive benchmarks (rung 0). Each predicts every market/component from a lagged, already-published price.

persist_da_d1  DA of D-1, same hour           (the 'yesterday' benchmark)
weekly_da_d7   DA of D-7, same hour           (weekly seasonality)
lago_naive     D-1 for Tue-Fri, D-7 for Sat-Mon (Lago et al. 2021 standard naive)
persist_rt_d2  RT of D-2, same hour           (latest full RT day available at 05:00 on D-1)

Missing lags fall back to D-1 then D-7 so all baselines score the same rows.
Quantiles: point forecast + empirical residual quantiles from the training window.
"""
from __future__ import annotations

import pandas as pd

from lmpsignal.config import COMPONENTS, MARKETS
from lmpsignal.models.base import EmpiricalQuantiles, Model, to_long, truth_long


class Naive(Model):
    def __init__(self, rule: str, lookback_days: int = 365):
        self.rule = rule
        self.name = rule
        self.lookback_days = lookback_days
        self.eq = EmpiricalQuantiles(lookback_days)

    def config(self) -> dict:
        return {"rule": self.rule, "quantiles": "empirical_residual", "lookback_days": self.lookback_days}

    def _point(self, df: pd.DataFrame, c: str) -> pd.Series:
        d1, d7 = df[f"lag_da_d1_{c}"], df[f"lag_da_d7_{c}"]
        if self.rule == "persist_da_d1":
            s = d1
        elif self.rule == "weekly_da_d7":
            s = d7
        elif self.rule == "lago_naive":
            s = d1.where(df["dow"].between(2, 5), d7)
        elif self.rule == "persist_rt_d2":
            s = df[f"lag_rt_d2_{c}"]
        else:
            raise ValueError(self.rule)
        return s.fillna(d1).fillna(d7)

    def _long(self, df: pd.DataFrame) -> pd.DataFrame:
        return to_long(df, {(m, c): self._point(df, c) for m in MARKETS for c in COMPONENTS})

    def fit(self, train: pd.DataFrame) -> Naive:
        long = self._long(train).merge(truth_long(train)[["ts_utc", "zone", "market", "component", "y"]],
                                       on=["ts_utc", "zone", "market", "component"])
        self.eq.fit(long)
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        return self.eq.apply(self._long(test))


BASELINES = ["persist_da_d1", "weekly_da_d7", "lago_naive", "persist_rt_d2"]


class ZeroCongestion(Model):
    """Always-zero congestion forecast (both markets). With out-of-sample residual quantiles this is the
    climatological distribution of congestion: the benchmark a congestion model must beat on CRPS."""

    name = "zero_congestion"

    def config(self) -> dict:
        return {"rule": "congestion = 0", "components": ["congestion"]}

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        z = pd.Series(0.0, index=test.index)
        return to_long(test, {(m, "congestion"): z for m in MARKETS})
