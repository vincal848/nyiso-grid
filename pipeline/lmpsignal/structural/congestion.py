"""M3 structural congestion model: per-constraint hurdle x shift factors, blended with persistence.

For each market and fold (all estimates use the fold's training window only):
 1. Constraint catalog: top-K constraint keys by sum |shadow price| over the last `window_days`.
 2. Shift factors A (zones x K): ridge regression of each zone's congestion component (-MCC) on the
    K hourly shadow prices.
 3. Hurdle for each (day, hour, constraint): P(bind) from a pooled LightGBM classifier and
    E[shadow | bind] from a pooled LightGBM regressor on binding rows (winsorized at 0.5/99.5%);
    forecast shadow = P x E[shadow | bind]; structural forecast = A @ forecast shadows.
 4. Zone forecast = per-zone least-absolute-deviation blend of the structural forecast with persistence
    (DA congestion of D-1; for RT also RT congestion of D-2). Blend weights are fit on pseudo-out-of-
    sample structural forecasts for the last 20% of the training window (catalog, A and hurdle refit on
    the first 80%); then everything is refit on the whole window.

Why the blend: on validation diagnostics the hurdle alone lost to persistence on DA congestion
(it is mean-optimal, and congestion is zero most hours), while actual shadows mapped through A left
little error -- the information is in the structure, but binding is hard to forecast.

Information set at the 05:00 ET D-1 issue: DA binding/shadows/congestion of D-1 and earlier (published
11:00 D-2); RT of D-2 and earlier; the panel's load/temperature forecasts and gas for D; scheduled
outages known at issue. RT uses DA binding of D-1 as an input (80% of RT congestion cost falls on
constraints that also bind DA).
"""
from __future__ import annotations

import warnings

import lightgbm as lgb
import numpy as np
import pandas as pd

from lmpsignal.models.base import Model, to_long
from lmpsignal.structural import constraints as cs

LAG = {"da": 1, "rt": 2}          # earliest fully published day for each market at issue time
EXO = ["load_fcst_nyiso", "temp_fcst_nyiso", "gas_hh"]


class StructuralCongestion(Model):
    def __init__(self, k: int = 60, window_days: int = 365, ridge: float = 1.0, n_estimators: int = 300,
                 blend_loss: str = "lad", name: str = "struct_cong", node_factors: bool = True):
        self.k, self.window_days, self.ridge, self.n_estimators = k, window_days, ridge, n_estimators
        self.blend_loss = blend_loss          # "lad" (median, original) or "l2" (conditional mean)
        self.name = name
        self.node_factors = node_factors
        self.diag: list[dict] = []
        self._art: dict[str, list[pd.DataFrame]] = {}

    def config(self) -> dict:
        return {"model": "structural congestion (hurdle x shift factors) blended with persistence", "top_k": self.k,
                "window_days": self.window_days, "ridge": self.ridge, "n_estimators": self.n_estimators,
                "bind_model": "LGBMClassifier pooled over constraints", "shadow_model": "LGBMRegressor on binding rows",
                "combine": f"per-zone {self.blend_loss.upper()} blend of hurdle@A with DA congestion D-1 (and RT "
                           "congestion D-2 for RT); weights from pseudo-OOS forecasts on the last 20% of the training window",
                "rt_shadow_hourly": "sum x 5/60 (nominal intervals)"}

    # ------------------------------------------------------------------------------------------ data
    def prepare(self, p: pd.DataFrame) -> None:
        lo = (p["delivery_date"].min() - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
        hi = (p["delivery_date"].max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        self.sp = cs.shadow_prices(lo, hi)
        days = pd.DatetimeIndex(sorted(p["delivery_date"].unique()))
        self.outages = cs.outage_counts(days).set_index("d")
        self.sys = p[p["zone"] == "WEST"].groupby(["delivery_date", "hour_local"])[EXO + ["dow", "month"]].mean()
        # zone congestion targets (hourly grid by local date/hour; fall-back hour averaged)
        self.cong = {m: p.groupby(["zone", "delivery_date", "hour_local"])[f"{m}_congestion"].mean().unstack("zone")
                     for m in ("da", "rt")}

    def _mu_cube(self, market: str, keys: list[str], days: pd.DatetimeIndex) -> np.ndarray:
        """(n_days, 24, K) shadow prices (0 when not binding)."""
        s = self.sp[(self.sp["market"] == market) & self.sp["key"].isin(keys)]
        cube = np.zeros((len(days), 24, len(keys)))
        di = pd.Series(np.arange(len(days)), index=days)
        ki = {k: i for i, k in enumerate(keys)}
        s = s[s["d"].isin(days)]
        cube[di[s["d"]].to_numpy(), s["hr"].to_numpy(), s["key"].map(ki).to_numpy()] = s["mu"].to_numpy()
        return cube

    def _features(self, market: str, keys: list[str], days: pd.DatetimeIndex) -> pd.DataFrame:
        """Rows = (day, hour, constraint) for `days`; lags come from days before them (all published)."""
        lag = LAG[market]
        span = pd.date_range(days.min() - pd.Timedelta(days=40), days.max(), freq="D")
        own = self._mu_cube(market, keys, span)
        da = own if market == "da" else self._mu_cube("da", keys, span)
        pos = span.get_indexer(days)
        b_own, b_da = (own != 0).astype(float), (da != 0).astype(float)

        def at(cube, off):              # value at day - off, same hour
            return cube[pos - off]

        def mean_back(cube, first, n):  # mean over days [d-first-n+1 .. d-first], same hour
            return np.mean(np.stack([cube[pos - first - j] for j in range(n)]), axis=0)

        feats = {
            "bind_l": at(b_own, lag), "mu_l": at(own, lag), "bind_l7": at(b_own, 7),
            "freq7_h": mean_back(b_own, lag, 7), "freq30_h": mean_back(b_own, lag, 30),
            "mu30_h": mean_back(own, lag, 30),
            "freq_day_l": np.repeat(b_own[pos - lag].mean(axis=1, keepdims=True), 24, axis=1),
            "da_bind_d1": at(b_da, 1), "da_mu_d1": at(da, 1), "da_freq7_h": mean_back(b_da, 1, 7),
        }
        n_d, K = len(days), len(keys)
        out = pd.DataFrame({k: v.reshape(-1) for k, v in feats.items()})
        out["d"] = np.repeat(days.to_numpy(), 24 * K)
        out["hr"] = np.tile(np.repeat(np.arange(24), K), n_d)
        out["key"] = pd.Categorical(np.tile(keys, n_d * 24), categories=keys)
        sys = self.sys.reindex(pd.MultiIndex.from_arrays([out["d"], out["hr"]]))
        for c in EXO + ["dow", "month"]:
            out[c] = sys[c].to_numpy()
        oc = self.outages.reindex(out["d"])
        out["n_outages"], out["n_outages_345"] = oc["n_outages"].to_numpy(), oc["n_outages_345"].to_numpy()
        return out

    # ------------------------------------------------------------------------------------------ pieces
    def _catalog(self, m, days):
        s = self.sp[(self.sp["market"] == m) & self.sp["d"].isin(days)]
        return s.groupby("key")["mu"].apply(lambda x: x.abs().sum()).nlargest(self.k).index.tolist()

    def _zone_grid(self, m, days, zones):
        g = self.cong[m].reindex(pd.MultiIndex.from_product([days, range(24)]))[zones].to_numpy()
        return g.reshape(len(days), 24, len(zones))

    def _shift_factors(self, m, keys, days, zones):
        X = self._mu_cube(m, keys, days).reshape(-1, len(keys))
        Y = self._zone_grid(m, days, zones).reshape(-1, len(zones))
        ok = np.isfinite(Y).all(axis=1)
        return np.linalg.solve(X[ok].T @ X[ok] + self.ridge * np.eye(len(keys)), X[ok].T @ Y[ok])

    def _hurdle_fit(self, m, keys, days):
        F = self._features(m, keys, days)
        y_mu = self._mu_cube(m, keys, days).reshape(-1)
        bind = (y_mu != 0).astype(int)
        cols = [c for c in F.columns if c != "d"]
        kw = dict(n_estimators=self.n_estimators, learning_rate=0.05, num_leaves=63, subsample=0.8, subsample_freq=1,
                  colsample_bytree=0.8, verbose=-1, n_jobs=16)
        clf = lgb.LGBMClassifier(min_child_samples=100, **kw).fit(F[cols], bind)
        lo_, hi_ = np.percentile(y_mu[bind == 1], [0.5, 99.5])
        reg = lgb.LGBMRegressor(min_child_samples=50, **kw).fit(F.loc[bind == 1, cols], np.clip(y_mu[bind == 1], lo_, hi_))
        return clf, reg, cols

    def _hurdle_pred(self, m, keys, days, clf, reg, cols):
        F = self._features(m, keys, days)
        pb = clf.predict_proba(F[cols])[:, 1]
        return (pb * reg.predict(F[cols])).reshape(len(days), 24, len(keys)), pb, F

    def _blend_inputs(self, m, days, zones, H):
        """(days, 24, zones, n_inputs): structural forecast, DA congestion of D-1, own congestion at lag (RT)."""
        span = pd.date_range(days.min() - pd.Timedelta(days=3), days.max(), freq="D")
        pos = span.get_indexer(days)
        cols = [H, self._zone_grid("da", span, zones)[pos - 1]]
        if m == "rt":
            cols.append(self._zone_grid("rt", span, zones)[pos - LAG["rt"]])
        return np.stack([np.nan_to_num(c) for c in cols], axis=-1)

    # ------------------------------------------------------------------------------------------ fit
    def fit(self, train: pd.DataFrame) -> "StructuralCongestion":
        from sklearn.linear_model import QuantileRegressor

        warnings.filterwarnings("ignore")
        end = train["delivery_date"].max()
        days = pd.date_range(end - pd.Timedelta(days=self.window_days - 1), end, freq="D")
        cut = int(len(days) * 0.8)
        fit_days, val_days = days[:cut], days[cut:]
        self.models = {}
        for m in ("da", "rt"):
            zones = list(self.cong[m].columns)
            # 1) pseudo out-of-sample structural forecasts on the last 20% of the window -> LAD blend weights
            keys_f = self._catalog(m, fit_days)
            A_f = self._shift_factors(m, keys_f, fit_days, zones)
            clf, reg, cols = self._hurdle_fit(m, keys_f, fit_days)
            H_val = self._hurdle_pred(m, keys_f, val_days, clf, reg, cols)[0] @ A_f
            Xb = self._blend_inputs(m, val_days, zones, H_val)
            Yv = self._zone_grid(m, val_days, zones)
            coefs = {}
            for j, z in enumerate(zones):
                x, y = Xb[:, :, j, :].reshape(-1, Xb.shape[-1]), Yv[:, :, j].reshape(-1)
                ok = np.isfinite(y)
                if self.blend_loss == "l2":
                    X1 = np.column_stack([np.ones(ok.sum()), x[ok]])
                    beta = np.linalg.lstsq(X1, y[ok], rcond=None)[0]
                    coefs[z] = (float(beta[0]), beta[1:].copy())
                else:
                    q = QuantileRegressor(quantile=0.5, alpha=1e-4, solver="highs").fit(x[ok], y[ok])
                    coefs[z] = (float(q.intercept_), q.coef_.copy())
            # 2) refit catalog, shift factors and hurdle on the full window
            keys = self._catalog(m, days)
            A = self._shift_factors(m, keys, days, zones)
            clf, reg, cols = self._hurdle_fit(m, keys, days)
            self.models[m] = dict(keys=keys, A=A, zones=zones, clf=clf, reg=reg, feat_cols=cols, coefs=coefs)
            self._record_fit(m, keys, days, zones, A, coefs)
        return self

    # ------------------------------------------------------------------------------------------ artifacts
    def _add(self, name: str, df: pd.DataFrame) -> None:
        self._art.setdefault(name, []).append(df)

    def artifacts(self) -> dict[str, pd.DataFrame]:
        """Tables saved by the runner for this fold (then cleared): nothing computed is thrown away."""
        out = {k: pd.concat(v, ignore_index=True) for k, v in self._art.items()}
        self._art = {}
        return out

    def _record_fit(self, m, keys, days, zones, A, coefs):
        cube = self._mu_cube(m, keys, days)
        K = len(keys)
        self._add("constraint_catalog", pd.DataFrame({
            "market": m, "rank": np.arange(1, K + 1), "key": keys,
            "sum_abs_shadow": np.abs(cube).sum(axis=(0, 1)), "bind_rate": (cube != 0).mean(axis=(0, 1)),
            "window_start": days.min(), "window_end": days.max()}))
        self._add("zone_shift_factors", pd.DataFrame({
            "market": m, "zone": np.repeat(zones, K), "key": np.tile(keys, len(zones)), "a": A.T.reshape(-1)}))
        names = ["w_structural", "w_da_cong_d1"] + (["w_rt_cong_d2"] if m == "rt" else [])
        self._add("blend_weights", pd.DataFrame([{"market": m, "zone": z, "intercept": c[0], **dict(zip(names, c[1]))}
                                                 for z, c in coefs.items()]))
        if not self.node_factors:
            return
        nc = cs.node_congestion(m, days.min(), days.max() + pd.Timedelta(days=1))
        X = pd.DataFrame(cube.reshape(-1, K), index=pd.MultiIndex.from_product([days, range(24)], names=["d", "hr"]))
        nc = nc.reindex(X.index)
        keep_nodes = nc.columns[nc.notna().mean() >= 0.9]
        Y = nc[keep_nodes].ffill().bfill().to_numpy()
        Xv = X.to_numpy()
        ok = np.isfinite(Y).all(axis=1)
        An = np.linalg.solve(Xv[ok].T @ Xv[ok] + self.ridge * np.eye(K), Xv[ok].T @ Y[ok])       # (K, nodes)
        fitted = Xv[ok] @ An
        ss_res = ((Y[ok] - fitted) ** 2).sum(axis=0)
        ss_tot = ((Y[ok] - Y[ok].mean(axis=0)) ** 2).sum(axis=0)
        self._add("node_shift_factors", pd.DataFrame({
            "market": m, "ptid": np.repeat(keep_nodes.to_numpy(), K), "key": np.tile(keys, len(keep_nodes)),
            "a": An.T.reshape(-1)}))
        self._add("node_fit", pd.DataFrame({"market": m, "ptid": keep_nodes.to_numpy(),
                                             "r2_in_window": np.where(ss_tot > 0, 1 - ss_res / np.maximum(ss_tot, 1e-12), np.nan)}))

    # ------------------------------------------------------------------------------------------ predict
    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        days = pd.DatetimeIndex(sorted(test["delivery_date"].unique()))
        means = {}
        for m, M in self.models.items():
            mu_hat, p_bind, F = self._hurdle_pred(m, M["keys"], days, M["clf"], M["reg"], M["feat_cols"])
            actual_mu = self._mu_cube(m, M["keys"], days).reshape(-1)
            self._add("constraint_forecasts", pd.DataFrame({
                "market": m, "delivery_date": F["d"].to_numpy(), "hour_local": F["hr"].to_numpy(),
                "key": F["key"].astype(str).to_numpy(), "p_bind": p_bind,
                "shadow_if_bind": M["reg"].predict(F[M["feat_cols"]]), "shadow_forecast": mu_hat.reshape(-1),
                "shadow_actual": actual_mu}))
            Xb = self._blend_inputs(m, days, M["zones"], mu_hat @ M["A"])
            cong = np.stack([M["coefs"][z][0] + Xb[:, :, j, :] @ M["coefs"][z][1] for j, z in enumerate(M["zones"])],
                            axis=-1)
            grid = pd.DataFrame(cong.reshape(-1, len(M["zones"])), columns=M["zones"],
                                index=pd.MultiIndex.from_product([days, range(24)], names=["delivery_date", "hour_local"]))
            long = grid.stack().rename("v").reset_index()
            long.columns = ["delivery_date", "hour_local", "zone", "v"]
            v = test[["delivery_date", "hour_local", "zone"]].merge(long, how="left",
                                                                    on=["delivery_date", "hour_local", "zone"])["v"]
            means[(m, "congestion")] = pd.Series(v.to_numpy(), index=test.index)
            # binding-classification diagnostics vs climatology (the constraint's 30-day hourly frequency)
            actual = (actual_mu != 0).astype(float)
            clim = np.clip(F["freq30_h"].to_numpy(), 1e-3, 1 - 1e-3)
            pb = np.clip(p_bind, 1e-3, 1 - 1e-3)
            w = np.array([c[1] for c in M["coefs"].values()])
            self.diag.append({"market": m, "fold_start": str(days.min().date()), "base_rate": float(actual.mean()),
                              "brier": float(np.mean((pb - actual) ** 2)),
                              "brier_clim": float(np.mean((clim - actual) ** 2)),
                              "logloss": float(-np.mean(actual * np.log(pb) + (1 - actual) * np.log(1 - pb))),
                              "logloss_clim": float(-np.mean(actual * np.log(clim) + (1 - actual) * np.log(1 - clim))),
                              "blend_weight_mean": w.mean(axis=0).round(3).tolist(),
                              "blend_inputs": ["structural", "DA cong D-1"] + (["RT cong D-2"] if m == "rt" else [])})
        return to_long(test, means)
