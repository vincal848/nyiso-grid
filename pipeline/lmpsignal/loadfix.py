"""Weather-to-load correction: forecast the error of NYISO's load forecast with fresher weather.

At the 05:00 ET D-1 issue the latest usable ISOLF file is the one dated D-2 (posted ~08:00 ET on D-2), so the
panel's load_fcst_zone is ~45 h old at the start of D. The 06z HRRR run of D-1 is available before the issue.
These models predict the relative error of the D-2 ISOLF forecast,
    r = (actual load - load_fcst_zone) / load_fcst_zone,
from how the weather outlook changed since that file was made (HRRR now vs. GFS as of 08:30 ET D-2), the weather
level itself (heating/cooling degree-hours, humidity, cloud, wind, daily temperature range for thermal inertia) and
calendar/behavior (hour x day type). Corrected forecast = load_fcst_zone x (1 + r_hat).

Models (both refit per fold on all earlier data, the usual 36 rolling-origin folds with embargo):
  loadfix_lin : classical, per-zone linear regression (ridge) on weather-change terms interacted with time of day,
                in the spirit of Tao's "Vanilla" benchmark.
  loadfix_gbm : LightGBM pooled over zones (zone categorical), same inputs plus levels and calendar.
Benchmarks scored alongside: ISOLF D-2 (what is used now) and ISOLF D-1 (posted ~08:00 ET on D-1, three hours
after the issue: not usable, but it shows what one day of fresher information is worth), each raw and debiased.
ISOLF runs systematically below the `load` (P-58B) actuals, by up to ~13% in MHK VL (definition differences), so
any fitted model gains from removing that level bias alone. "_adj" benchmarks multiply the ISOLF file by the
training-window mean ratio per zone x hour; the weather value of a model is its gain over isolf_d2_adj.
Targets come from the warehouse (`load_zone_5m`, hourly means); the internal zones only.

Price-model feature (`build_oos`): the corrected forecast for every month from 2022-10, each month predicted by a
model trained only on data ending EMBARGO_DAYS before that month, written to data/features.duckdb `load_fix_oos`
(logged as run `<model>_oos`). The panel joins it, so price models see a load forecast that was out of sample at
the time for every training and test row. Workflow: `lmp panel` -> `lmp loadfix gbm --oos` -> `lmp panel`.
"""
from __future__ import annotations

import time
from datetime import timedelta

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

from nyiso.config import DB_PATH
from lmpsignal import cv, registry
from lmpsignal.config import BURN_IN_START, EMBARGO_DAYS, FEATURES_DB, INTERNAL_ZONES, VALIDATION_END

BASE_T = 18.3
LEVEL = ["hrrr_temp_zone", "hrrr_dewpoint_zone", "hrrr_wind80_zone", "hrrr_cloud_zone", "hrrr_temp_zone_dmean",
         "hrrr_temp_zone_dmax", "hrrr_temp_zone_dmin", "hrrr_temp_nyiso"]
CHANGE = ["d_temp", "d_cdh", "d_hdh"]
CALENDAR = ["hour_local", "dow", "month", "is_weekend", "is_holiday", "doy_sin", "doy_cos"]
GBM_FEATURES = ["zone", "load_fcst_zone", "temp_fcst_zone_isolf", "hrrr_cdh", "hrrr_hdh", *LEVEL, *CHANGE, *CALENDAR]


def _wh() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    return con


def actual_and_d1(start, end) -> pd.DataFrame:
    """Hourly actual zone load and the ISOLF D-1 forecast (benchmark only) for delivery days [start, end)."""
    con = _wh()
    df = con.execute("""
        WITH a AS (SELECT zone, time_bucket(INTERVAL 1 HOUR, ts_utc) AS ts_utc, avg(load_mw) AS load_actual
                   FROM load_zone_5m WHERE ts_utc >= ?::TIMESTAMPTZ - INTERVAL 1 DAY AND ts_utc < ?::TIMESTAMPTZ + INTERVAL 1 DAY
                   GROUP BY ALL),
             f AS (SELECT zone, ts_utc, load_forecast_mw AS isolf_d1 FROM load_forecast
                   WHERE issue_date = CAST(timezone('America/New_York', ts_utc) AS DATE) - INTERVAL 1 DAY)
        SELECT a.*, f.isolf_d1 FROM a LEFT JOIN f USING (zone, ts_utc)""", [str(start), str(end)]).df()
    con.close()
    return df


def frame(p: pd.DataFrame) -> pd.DataFrame:
    """Internal-zone panel rows with targets, benchmarks and derived weather-change features."""
    d = p[p["zone"].isin(INTERNAL_ZONES)].copy()
    a = actual_and_d1(d["delivery_date"].min(), d["delivery_date"].max() + timedelta(days=1))
    d = d.merge(a, on=["zone", "ts_utc"], how="left")
    d["hrrr_cdh"] = (d["hrrr_temp_zone"] - BASE_T).clip(lower=0)
    d["hrrr_hdh"] = (BASE_T - d["hrrr_temp_zone"]).clip(lower=0)
    old = d["temp_fcst_zone_isolf"]
    d["d_temp"] = d["hrrr_temp_zone"] - old
    d["d_cdh"] = d["hrrr_cdh"] - (old - BASE_T).clip(lower=0)
    d["d_hdh"] = d["hrrr_hdh"] - (BASE_T - old).clip(lower=0)
    d["r"] = d["load_actual"] / d["load_fcst_zone"] - 1
    d["zone"] = pd.Categorical(d["zone"], categories=INTERNAL_ZONES)
    return d


# ----------------------------------------------------------------------------- models

class LinearCorrection:
    """Per-zone ridge regression of r on weather-change terms x 4 time-of-day blocks, plus weekend shifts."""
    name = "loadfix_lin"

    def __init__(self, alpha: float = 1.0):
        self.alpha = alpha

    def config(self) -> dict:
        return {"model": "per-zone ridge on weather change since the ISOLF D-2 file x time-of-day block",
                "alpha": self.alpha, "terms": ["d_cdh", "d_hdh", "d_temp", "hrrr_dewpoint_zone x cdh>0", "cloud"],
                "blocks": "hours 0-5, 6-11, 12-17, 18-23; + weekend/holiday intercept"}

    @staticmethod
    def _X(d: pd.DataFrame) -> np.ndarray:
        block = (d["hour_local"].to_numpy() // 6).astype(int)
        terms = np.column_stack([d["d_cdh"], d["d_hdh"], d["d_temp"],
                                 d["hrrr_dewpoint_zone"] * (d["hrrr_cdh"] > 0), d["hrrr_cloud_zone"] / 100])
        cols = [np.ones(len(d)), (d["is_weekend"] | d["is_holiday"]).astype(float).to_numpy()]
        for b in range(4):
            cols.append((block == b).astype(float))
            cols.extend((terms * (block == b)[:, None]).T)
        return np.nan_to_num(np.column_stack(cols))

    def fit(self, d: pd.DataFrame) -> "LinearCorrection":
        self.coef = {}
        for z, g in d.groupby("zone", observed=True):
            X, y = self._X(g), g["r"].to_numpy()
            self.coef[z] = np.linalg.solve(X.T @ X + self.alpha * np.eye(X.shape[1]), X.T @ y)
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        out = np.zeros(len(d))
        for z, idx in d.groupby("zone", observed=True).indices.items():
            out[idx] = self._X(d.iloc[idx]) @ self.coef[z]
        return out

    def importance(self) -> pd.DataFrame | None:
        return None


CAL_FEATURES = ["zone", "load_fcst_zone", *CALENDAR]


class GBMCorrection:
    """weather=False is the ablation: same model on ISOLF + calendar only (learns the seasonal level bias), so the
    gain of loadfix_gbm over loadfix_gbm_cal is what the weather adds."""

    def __init__(self, n_estimators: int = 600, learning_rate: float = 0.03, num_leaves: int = 63, weather: bool = True):
        self.name = "loadfix_gbm" if weather else "loadfix_gbm_cal"
        self.features = GBM_FEATURES if weather else CAL_FEATURES
        self.params = dict(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                           min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                           reg_lambda=1.0, verbose=-1, n_jobs=16)

    def config(self) -> dict:
        return {"model": "LightGBM (L2) on relative ISOLF D-2 error, pooled over zones", "params": self.params,
                "features": self.features}

    def fit(self, d: pd.DataFrame) -> "GBMCorrection":
        self.m = lgb.LGBMRegressor(**self.params).fit(d[self.features], d["r"], categorical_feature=["zone"])
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        return self.m.predict(d[self.features])

    def importance(self) -> pd.DataFrame:
        g = self.m.booster_.feature_importance("gain")
        return pd.DataFrame({"feature": self.features, "gain": g / g.sum()})


MODELS = {"lin": LinearCorrection, "gbm": GBMCorrection, "gbm_cal": lambda: GBMCorrection(weather=False)}


# ----------------------------------------------------------------------------- scoring and runner

BENCH = ("isolf_d2", "isolf_d1", "isolf_d2_adj", "isolf_d1_adj")


def debias(tr: pd.DataFrame, te: pd.DataFrame) -> pd.DataFrame:
    """Add isolf_d2_adj / isolf_d1_adj: ISOLF scaled by its training-window mean ratio per zone x hour."""
    te = te.copy()
    key = ["zone", "hour_local"]
    for src, col in (("load_fcst_zone", "isolf_d2_adj"), ("isolf_d1", "isolf_d1_adj")):
        ratio = (tr["load_actual"] / tr[src]).replace([np.inf, -np.inf], np.nan)
        b = ratio.groupby([tr[k] for k in key], observed=True).mean().rename("b").reset_index()
        te[col] = te[src] * te[key].merge(b, on=key, how="left")["b"].fillna(1.0).to_numpy()
    return te


def _scores(t: pd.DataFrame) -> pd.DataFrame:
    """MAPE / RMSE of the model and the ISOLF benchmarks, per zone, pooled over zones and for the NYISO sum."""
    rows = []
    bench = [c for c in BENCH if c in t]
    sys = (t.groupby("ts_utc")[["load_actual", "pred", *bench]].sum(min_count=11)
            .dropna().assign(zone="NYISO"))
    for zone, g in [*t.groupby("zone", observed=True), ("ALL", t), ("NYISO", sys)]:
        g = g.dropna(subset=["load_actual", "pred", "isolf_d2"])
        if g.empty:                                    # NYISO total needs all 11 zones in the hour
            continue
        row = {"market": "load", "component": "load", "zone": str(zone)}
        for col, tag in (("pred", ""), *((c, f"_{c}") for c in bench)):
            e = g[col] - g["load_actual"]
            row[f"mape{tag}"] = float(np.nanmean(np.abs(e) / g["load_actual"]))
            row[f"rmse{tag}"] = float(np.sqrt(np.nanmean(e ** 2)))
        rows.append(row)
    return pd.DataFrame(rows)


def run(kind: str, p: pd.DataFrame, folds: list[cv.Fold] | None = None, log: bool = True,
        suffix: str = "") -> str | None:
    model = MODELS[kind]()
    d = frame(p)
    folds = folds or cv.folds()
    ok = d["r"].notna() & d["load_fcst_zone"].notna() & d["hrrr_temp_zone"].notna()
    run_id = registry.start_run(model.name + suffix, {**model.config(), "folds": len(folds), "embargo_days": EMBARGO_DAYS,
                                                      "first_fold": folds[0].name, "last_fold": folds[-1].name},
                                int(ok.sum())) if log else None
    try:
        for f in folds:
            t0 = time.time()
            tr = d[ok & (d["delivery_date"] >= pd.Timestamp(f.train_start)) & (d["delivery_date"] < pd.Timestamp(f.train_end))]
            te = d[(d["delivery_date"] >= pd.Timestamp(f.test_start)) & (d["delivery_date"] < pd.Timestamp(f.test_end))].copy()
            model.fit(tr)
            have = te["hrrr_temp_zone"].notna() & te["load_fcst_zone"].notna()
            te["r_hat"] = np.where(have, model.predict(te.fillna({c: 0 for c in CHANGE})), 0.0)
            te["pred"] = te["load_fcst_zone"] * (1 + te["r_hat"])
            te["isolf_d2"] = te["load_fcst_zone"]
            te = debias(tr, te)
            s = _scores(te)
            tag = "NYISO" if (s["zone"] == "NYISO").any() else "ALL"
            allz = s[s["zone"] == tag].iloc[0]
            print(f"  {model.name:<12} {f.name}  {tag} MAPE {100 * allz['mape']:.2f}% | ISOLF D-2 "
                  f"{100 * allz['mape_isolf_d2']:.2f}% raw, {100 * allz['mape_isolf_d2_adj']:.2f}% debiased | D-1 "
                  f"{100 * allz['mape_isolf_d1']:.2f}% / {100 * allz['mape_isolf_d1_adj']:.2f}%  RMSE {allz['rmse']:.0f} MW "
                  f"(D-2 adj {allz['rmse_isolf_d2_adj']:.0f}, D-1 adj {allz['rmse_isolf_d1_adj']:.0f})  "
                  f"{time.time() - t0:.0f}s", flush=True)
            if log:
                keep = ["delivery_date", "ts_utc", "zone", "hour_local", "load_actual", *BENCH, "r_hat", "pred"]
                registry.save_fold(run_id, f.name, te[keep].assign(zone=te["zone"].astype(str)), s)
                imp = model.importance()
                if imp is not None:
                    registry.save_artifact(run_id, f.name, "feature_importance", imp)
        if log:
            registry.finish_run(run_id)
    except Exception as e:
        if log:
            registry.finish_run(run_id, "failed", f"{type(e).__name__}: {e}")
        raise
    return run_id


def oos_folds(first: str = "2022-01", end=VALIDATION_END) -> list[cv.Fold]:
    """One block per month from `first` to `end` (exclusive): expanding training window, same embargo."""
    out = []
    m = pd.Timestamp(first + "-01")
    while m < pd.Timestamp(end):
        nxt = m + pd.offsets.MonthBegin(1)
        out.append(cv.Fold(f"{m:%Y-%m}", BURN_IN_START, (m - timedelta(days=EMBARGO_DAYS)).date(), m.date(), nxt.date()))
        m = nxt
    return out


OOS_SCHEMA = """CREATE TABLE IF NOT EXISTS load_fix_oos (ts_utc TIMESTAMPTZ, zone VARCHAR, delivery_date DATE,
                load_fix DOUBLE, r_hat DOUBLE, run_id VARCHAR)"""


# First month 2022-10: the model needs a full seasonal cycle of training data. Started at 2022-01 it was worse than
# debiased ISOLF D-2 through the first summer (2022-07 RMSE 1,251 vs 788 MW), which would only add noise to the
# price models' early training rows. Chosen on load accuracy in the burn-in year, not on price results.
def build_oos(kind: str, p: pd.DataFrame, first: str = "2022-10") -> str:
    """Out-of-sample corrected load for every month from `first` (see module docstring); replaces load_fix_oos."""
    run_id = run(kind, p, folds=oos_folds(first), log=True, suffix="_oos")
    pr = registry.predictions(run_id)
    pr = pr.assign(delivery_date=pd.to_datetime(pr["delivery_date"]).dt.date, run_id=run_id)
    con = duckdb.connect(str(FEATURES_DB))
    con.execute(OOS_SCHEMA)
    con.execute("DELETE FROM load_fix_oos")
    con.register("pr", pr[["ts_utc", "zone", "delivery_date", "pred", "r_hat", "run_id"]])
    con.execute("INSERT INTO load_fix_oos SELECT ts_utc, zone, delivery_date, pred, r_hat, run_id FROM pr")
    con.close()
    return run_id
