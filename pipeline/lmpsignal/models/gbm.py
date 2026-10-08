"""Gradient-boosted trees (LightGBM; Ke et al. 2017): one pooled model per (market, component) across
zones and hours, trained on the as-of panel features plus zone and hour.

The energy component is system-wide, so it is trained on one zone's rows and broadcast to all zones.
"""
from __future__ import annotations

import lightgbm as lgb
import pandas as pd

from lmpsignal.config import COMPONENTS, MARKETS
from lmpsignal.models.base import Model, to_long
from lmpsignal.panel import FEATURE_SETS

ENERGY_ZONE = "CAPITL"
BASE_PARAMS = dict(learning_rate=0.05, num_leaves=63, min_child_samples=200, subsample=0.8, subsample_freq=1,
                   colsample_bytree=0.8, reg_lambda=1.0, max_bin=127, verbose=-1)


class GBM(Model):
    def __init__(self, objective: str = "l1", n_estimators: int = 500, window_days: int | None = 728,
                 n_jobs: int = 16, feature_set: str = "v1", **params):
        self.objective = objective
        self.n_estimators = n_estimators
        self.window_days = window_days
        self.n_jobs = n_jobs
        self.params = {**BASE_PARAMS, **params}
        self.name = f"gbm_{objective}" + ("" if feature_set == "v1" else f"_{feature_set}")
        self.models: dict[tuple[str, str], lgb.LGBMRegressor] = {}
        self.feature_set = feature_set
        self.features = list(FEATURE_SETS[feature_set])

    def config(self) -> dict:
        return {"model": "LightGBM", "objective": self.objective, "n_estimators": self.n_estimators,
                "train_window_days": self.window_days or "all", "params": self.params,
                "features": "panel FEATURES + zone(categorical)", "refit": "per fold (monthly)",
                **({"feature_set": self.feature_set, "feature_list": self.features} if self.feature_set != "v1" else {})}

    def _X(self, df: pd.DataFrame) -> pd.DataFrame:
        X = df[self.features].astype(float)
        X["zone"] = pd.Categorical(df["zone"], categories=self._zones)
        return X

    def fit(self, train: pd.DataFrame) -> GBM:
        if self.window_days:
            train = train[train["delivery_date"] > train["delivery_date"].max() - pd.Timedelta(days=self.window_days)]
        self._zones = sorted(train["zone"].unique())
        self.models = {}
        for m in MARKETS:
            for c in COMPONENTS:
                df = train[train["zone"] == ENERGY_ZONE] if c == "energy" else train
                y = df[f"{m}_{c}"]
                ok = y.notna().to_numpy()
                model = lgb.LGBMRegressor(objective=self.objective, n_estimators=self.n_estimators,
                                          n_jobs=self.n_jobs, **self.params)
                model.fit(self._X(df)[ok], y[ok])
                self.models[(m, c)] = model
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        X = self._X(test)
        means = {}
        for (m, c), model in self.models.items():
            if c == "energy":
                e = test[test["zone"] == ENERGY_ZONE]
                pe = pd.Series(model.predict(self._X(e)), index=e["ts_utc"].to_numpy())
                pe = pe[~pe.index.duplicated()]
                means[(m, c)] = pd.Series(pe.reindex(test["ts_utc"].to_numpy()).to_numpy(), index=test.index)
            else:
                means[(m, c)] = pd.Series(model.predict(X), index=test.index)
        return to_long(test, means)

