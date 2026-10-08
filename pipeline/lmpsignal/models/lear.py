"""LEAR: LASSO-Estimated AutoRegressive model (Lago, Marcjasz, De Schutter & Weron 2021; Uniejewski,
Nowotarski & Weron 2016), adapted to NYISO zones, DA and RT, and additive price components.

For each series (market m, component c, zone z; energy is system-wide so it is fit once) and each
local hour h, a separate linear model is fit on the daily design:
    own DA-c prices, all 24 hours, of D-1, D-2, D-3, D-7            (published by 11:00 on D-2 or earlier)
    own RT-c prices, all 24 hours, of D-2, D-3                      (fully published before 05:00 on D-1)
    zone and NYISO load forecasts, zone temperature forecast, 24 h  (panel, as-of the issue)
    Henry Hub, day-of-week dummies, NERC holiday flag
Prices are variance-stabilized with asinh((x - median) / MAD) fitted on the training window
(Uniejewski, Weron & Ziel 2018); exogenous inputs are z-scored. The LASSO penalty is chosen by AIC
(LassoLarsIC), as in epftoolbox. Forecasts from several calibration windows are averaged.

Deviation from Lago et al.: models are refit once per validation month (fold), not every day.
Calibration windows of 56/84 days are not used: with 225 inputs they would have fewer observations
than regressors, which AIC-based LARS cannot handle.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LassoCV, LassoLarsIC
from sklearn.model_selection import TimeSeriesSplit

from lmpsignal.config import COMPONENTS, MARKETS
from lmpsignal.models import daygrid as dg
from lmpsignal.models.base import Model, to_long

ENERGY_ZONE = "CAPITL"   # energy component is identical across zones (verified); fit it on one


def _vst_params(x: np.ndarray) -> tuple[float, float]:
    med = float(np.nanmedian(x))
    mad = float(np.nanmedian(np.abs(x - med))) * 1.4826
    return med, (mad if mad > 1e-6 else max(float(np.nanstd(x)), 1.0))


def _vst(x, med, mad):
    return np.arcsinh((x - med) / mad)


def _ivst(z, med, mad):
    return np.sinh(z) * mad + med


class Design:
    """Daily grids for every variable LEAR needs, built once per run from the full panel."""

    def __init__(self, p: pd.DataFrame, inputs: str = "isolf_gfs"):
        if inputs == "loadfix_hrrr":
            # weather-corrected load and HRRR temperature, falling back to ISOLF / GFS where missing
            p = p.assign(load_fcst_zone=p["load_fix_zone"].fillna(p["load_fcst_zone"]),
                         load_fcst_nyiso=p["load_fix_nyiso"].fillna(p["load_fcst_nyiso"]),
                         temp_fcst_zone=p["hrrr_temp_zone"].fillna(p["temp_fcst_zone"]),
                         temp_fcst_nyiso=p["hrrr_temp_nyiso"].fillna(p["temp_fcst_nyiso"]))
        self.idx = pd.MultiIndex.from_frame(p[["zone", "delivery_date"]].drop_duplicates()
                                            .sort_values(["zone", "delivery_date"]))
        self.g = {}
        for m in MARKETS:
            for c in COMPONENTS:
                self.g[f"{m}_{c}"] = dg.grid(p, f"{m}_{c}")
        self.zones_with_load = set(p.loc[p["load_fcst_zone"].notna(), "zone"].unique())
        lf = p["load_fcst_zone"].fillna(p["load_fcst_nyiso"])
        p = p.assign(_load_zone=lf)
        for col in ("_load_zone", "load_fcst_nyiso", "temp_fcst_zone", "temp_fcst_nyiso"):
            self.g[col] = dg.grid(p, col)
        daily = p.groupby(["zone", "delivery_date"]).agg(gas=("gas_hh", "first"), dow=("dow", "first"),
                                                         hol=("is_holiday", "first"))
        self.daily = daily
        self._cache: dict[tuple, pd.DataFrame] = {}

    def lag(self, name: str, days: int) -> pd.DataFrame:
        key = (name, days)
        if key not in self._cache:
            self._cache[key] = dg.lagged(self.g[name], days, self.idx)
        return self._cache[key]

    def features(self, market: str, comp: str, zone: str, dates: pd.DatetimeIndex, energy: bool) -> pd.DataFrame:
        rows = pd.MultiIndex.from_product([[zone], dates], names=["zone", "delivery_date"])
        blocks = []
        for lag in (1, 2, 3, 7):
            blocks.append(self.lag(f"da_{comp}", lag).reindex(rows).add_prefix(f"da_d{lag}_h"))
        for lag in (2, 3):
            blocks.append(self.lag(f"rt_{comp}", lag).reindex(rows).add_prefix(f"rt_d{lag}_h"))
        temp = "temp_fcst_nyiso" if energy else "temp_fcst_zone"
        # zone load block only where a zonal forecast exists (external zones and energy use NYISO total only;
        # duplicating it would make the design exactly collinear)
        if not energy and zone in self.zones_with_load:
            blocks.append(self.g["_load_zone"].reindex(rows).add_prefix("load_h"))
        blocks.append(self.g["load_fcst_nyiso"].reindex(rows).add_prefix("loadsys_h"))
        blocks.append(self.g[temp].reindex(rows).add_prefix("temp_h"))
        d = self.daily.reindex(rows)
        exo = pd.DataFrame({"gas": d["gas"].astype(float), "hol": d["hol"].astype(float)}, index=rows)
        for k in range(1, 8):
            exo[f"dow{k}"] = (d["dow"] == k).astype(float)
        blocks.append(exo)
        X = pd.concat(blocks, axis=1)
        X.columns = [str(c) for c in X.columns]
        return X

    def target(self, market: str, comp: str, zone: str, dates) -> pd.DataFrame:
        rows = pd.MultiIndex.from_product([[zone], dates], names=["zone", "delivery_date"])
        return self.g[f"{market}_{comp}"].reindex(rows)


PRICE_PREFIXES = ("da_d", "rt_d")


def _fit_predict_series(X_tr: pd.DataFrame, Y_tr: pd.DataFrame, X_te: pd.DataFrame, windows: tuple,
                        clip: bool = True) -> np.ndarray:
    """Fit 24 hourly LASSO models per calibration window; return the window-averaged (n_test, 24) forecast."""
    warnings.filterwarnings("ignore", category=ConvergenceWarning)
    preds = []
    dates = X_tr.index.get_level_values("delivery_date")
    for w in windows:
        keep = dates > dates.max() - pd.Timedelta(days=w) if w else np.ones(len(dates), bool)
        Xw, Yw = X_tr[keep], Y_tr[keep]
        # transforms fitted on the window
        price_cols = [c for c in Xw.columns if c.startswith(PRICE_PREFIXES)]
        exo_cols = [c for c in Xw.columns if c not in price_cols]
        med_y, mad_y = _vst_params(Yw.to_numpy().ravel())
        fill = Xw.median()
        Xw_f, Xte_f = Xw.fillna(fill), X_te.fillna(fill)
        mu, sd = Xw_f[exo_cols].mean(), Xw_f[exo_cols].std().replace(0, 1).fillna(1)
        # every price input block uses its own robust scale
        pp = {c: _vst_params(Xw_f[c].to_numpy()) for c in price_cols}

        def transform(X, pp=pp, mu=mu, sd=sd):
            out = np.empty((len(X), X.shape[1]))
            for j, c in enumerate(X.columns):
                out[:, j] = _vst(X[c].to_numpy(), *pp[c]) if c in pp else (X[c].to_numpy() - mu[c]) / sd[c]
            return out

        A, A_te = transform(Xw_f), transform(Xte_f)
        # drop constant and exactly duplicated columns (they break the LARS path)
        keep_cols = np.nanstd(A, axis=0) > 1e-9
        _, first = np.unique(np.round(A[:, keep_cols], 10), axis=1, return_index=True)
        cols = np.flatnonzero(keep_cols)[np.sort(first)]
        A, A_te = A[:, cols], A_te[:, cols]
        P = np.full((len(X_te), 24), np.nan)
        for h in range(24):
            y = Yw.iloc[:, h].to_numpy()
            ok = np.isfinite(y)
            if ok.sum() < A.shape[1] + 5:
                continue
            z = _vst(y[ok], med_y, mad_y)
            try:
                m = LassoLarsIC(criterion="aic", max_iter=2500).fit(A[ok], z)
            except (ValueError, FloatingPointError):
                m = LassoCV(cv=TimeSeriesSplit(4), n_alphas=30, max_iter=5000).fit(A[ok], z)   # rare degenerate path
            zp = m.predict(A_te)
            if clip:   # keep forecasts inside the training range in VST space: sinh() explodes on extrapolation
                zp = np.clip(zp, z.min(), z.max())
            P[:, h] = _ivst(zp, med_y, mad_y)
        preds.append(P)
    return np.nanmean(np.stack(preds), axis=0)



def _parallel(fn, arglist: list[tuple], n_jobs: int, retries: int = 2) -> list:
    """joblib/loky map with retries. On Windows a loky worker occasionally dies at start-up (0x800703e5 ->
    BrokenProcessPool / TerminatedWorkerError); the fits are deterministic, so retrying with a fresh pool (and finally
    in-process) returns the same results instead of failing the run."""
    from concurrent.futures.process import BrokenProcessPool

    from joblib.externals.loky.process_executor import TerminatedWorkerError

    for attempt in range(retries + 1):
        try:
            return Parallel(n_jobs=n_jobs, backend="loky")(delayed(fn)(*a) for a in arglist)
        except (BrokenProcessPool, TerminatedWorkerError) as e:
            print(f"  LEAR worker pool failed ({type(e).__name__}), attempt {attempt + 1}/{retries + 1}", flush=True)
    return [fn(*a) for a in arglist]

class LEAR(Model):
    name = "lear"

    def __init__(self, windows=(364, 728, None), n_jobs: int = 10, clip: bool = True, inputs: str = "isolf_gfs"):
        self.inputs = inputs
        if inputs != "isolf_gfs":
            self.name = f"{type(self).name}_wx"
        self.windows = tuple(windows)
        self.clip = clip
        self.n_jobs = n_jobs
        self.design: Design | None = None
        self._train_end = None

    def config(self) -> dict:
        return {"model": "LEAR", "windows": [w or "all" for w in self.windows], "penalty": "LassoLarsIC(aic)",
                "vst": "asinh(median/MAD)", "refit": "per fold (monthly)",
                "clip": "training range in VST space" if self.clip else "none",
                "inputs": "DA lags D-1,2,3,7 x24; RT lags D-2,3 x24; load zone+NYISO x24; temp x24; gas; dow; holiday",
                **({"load_temp_source": "load_fix (loadfix_gbm OOS) + HRRR temperature; ISOLF/GFS where missing"}
                   if self.inputs != "isolf_gfs" else {})}

    def prepare(self, full_panel: pd.DataFrame) -> None:
        """Build the daily grids once for the whole run (inputs are as-of; targets only used via lags)."""
        self.design = Design(full_panel, self.inputs)

    def fit(self, train: pd.DataFrame) -> LEAR:
        self._train = train
        return self

    def _series(self, zones):
        out = [("da", "energy", ENERGY_ZONE, True), ("rt", "energy", ENERGY_ZONE, True)]
        for m in MARKETS:
            for c in ("total", "loss", "congestion"):
                out += [(m, c, z, False) for z in zones]
        return out

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        D, train = self.design, self._train
        tr_dates = pd.DatetimeIndex(sorted(train["delivery_date"].unique()))
        te_dates = pd.DatetimeIndex(sorted(test["delivery_date"].unique()))
        zones = sorted(test["zone"].unique())
        series = self._series(zones)

        # Build each series' (small) design matrices here and ship only those to the workers.
        tasks = [((m, c, z), D.features(m, c, z, tr_dates, energy), D.target(m, c, z, tr_dates),
                  D.features(m, c, z, te_dates, energy)) for m, c, z, energy in series]
        outs = _parallel(_fit_predict_series, [(X_tr, Y_tr, X_te, self.windows, self.clip) for _, X_tr, Y_tr, X_te in tasks],
                         self.n_jobs)
        results = [(t[0], P) for t, P in zip(tasks, outs)]
        grids: dict[tuple[str, str], list[pd.DataFrame]] = {}
        for (m, c, z), P in results:
            zs = zones if c == "energy" else [z]
            for zz in zs:
                idx = pd.MultiIndex.from_product([[zz], te_dates], names=["zone", "delivery_date"])
                grids.setdefault((m, c), []).append(pd.DataFrame(P, index=idx, columns=dg.HOURS))
        means = {k: pd.Series(dg.to_rows(pd.concat(v), test), index=test.index) for k, v in grids.items()}
        return to_long(test, means)


# ============================================================================================ LEAR v2
# Faster and closer to current practice (Lipiecki & Weron 2026: validation-chosen penalty beats LARS-AIC):
#  * one Gram matrix per window shared by the 24 hourly fits (coordinate descent on X'X, p = 225);
#  * penalty chosen per hour on the last 20% of the 364-day window (time-ordered hold-out, 20-point grid)
#    and reused by every window (the 56-day window has fewer rows than inputs and cannot choose its own);
#  * forecasts clipped per hour to the window's training range in VST space;
#  * every window's forecast is returned so window subsets / weights can be changed by post-processing.

from sklearn.linear_model import Lasso, lasso_path  # noqa: E402


def _transform_block(Xw: pd.DataFrame, X_te: pd.DataFrame):
    price = np.array([c.startswith(PRICE_PREFIXES) for c in Xw.columns])
    fill = Xw.median()
    A, B = Xw.fillna(fill).to_numpy(float), X_te.fillna(fill).to_numpy(float)
    med = np.median(A[:, price], axis=0)
    mad = np.median(np.abs(A[:, price] - med), axis=0) * 1.4826
    sd_p = A[:, price].std(axis=0)
    mad = np.where(mad > 1e-6, mad, np.maximum(sd_p, 1.0))
    mu, sd = A[:, ~price].mean(axis=0), A[:, ~price].std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    for M in (A, B):
        M[:, price] = np.arcsinh((M[:, price] - med) / mad)
        M[:, ~price] = (M[:, ~price] - mu) / sd
    keep = A.std(axis=0) > 1e-9
    _, first = np.unique(np.round(A[:, keep], 10), axis=1, return_index=True)
    cols = np.flatnonzero(keep)[np.sort(first)]
    return A[:, cols], B[:, cols]


def _choose_alpha(A: np.ndarray, z: np.ndarray, val_frac: float = 0.2, n_alphas: int = 30) -> float:
    n = len(A)
    nf = int(n * (1 - val_frac))
    Af, zf, Av, zv = A[:nf], z[:nf], A[nf:], z[nf:]
    xm, zm = Af.mean(axis=0), zf.mean()
    Ac, zc = Af - xm, zf - zm
    xy = Ac.T @ zc
    amax = np.abs(xy).max() / nf
    if not amax > 0:
        return 1.0
    grid = np.logspace(np.log10(amax), np.log10(amax * 1e-3), n_alphas)
    _, coefs, _ = lasso_path(Ac, zc, alphas=grid, precompute=Ac.T @ Ac, Xy=xy)
    mse = (((Av - xm) @ coefs + zm - zv[:, None]) ** 2).mean(axis=0)
    return float(grid[int(np.argmin(mse))])


def _fit_predict_series_v2(X_tr: pd.DataFrame, Y_tr: pd.DataFrame, X_te: pd.DataFrame, windows: tuple) -> dict:
    """Returns {window: (n_test, 24) price forecasts}; the average is taken by the caller."""
    warnings.filterwarnings("ignore", category=ConvergenceWarning)
    dates = X_tr.index.get_level_values("delivery_date")
    ref_w = 364 if 364 in windows else next(w for w in windows if w)
    # the penalty is chosen once per hour on the reference window, then reused by every window
    order = [ref_w] + [w for w in windows if w != ref_w]
    alpha_ref: dict[int, float] = {}
    out = {}
    for w in order:
        keep = dates > dates.max() - pd.Timedelta(days=w) if w else np.ones(len(dates), bool)
        Xw, Yw = X_tr[keep], Y_tr[keep].to_numpy(float)
        rows = np.isfinite(Yw).all(axis=1)
        Xw, Yw = Xw[rows], Yw[rows]
        P = np.full((len(X_te), 24), np.nan)
        if len(Xw) < 20:
            out[w] = P
            continue
        A, B = _transform_block(Xw, X_te)
        med_y, mad_y = _vst_params(Yw.ravel())
        Z = _vst(Yw, med_y, mad_y)
        xm, zm = A.mean(axis=0), Z.mean(axis=0)
        Ac = A - xm
        G = Ac.T @ Ac
        for h in range(24):
            z = Z[:, h]
            if h not in alpha_ref:
                alpha_ref[h] = _choose_alpha(A, z, n_alphas=20) if len(A) >= 40 else 1.0
            alpha = alpha_ref[h]
            m = Lasso(alpha=alpha, fit_intercept=False, precompute=G, max_iter=5000).fit(Ac, z - zm[h])
            zp = (B - xm) @ m.coef_ + zm[h]
            P[:, h] = _ivst(np.clip(zp, z.min(), z.max()), med_y, mad_y)
        out[w] = P
    return out


class LEAR2(LEAR):
    """LEAR v2: shared-Gram coordinate descent, validation-chosen penalty, 56-day window, per-window outputs."""

    name = "lear2"

    def __init__(self, windows=(56, 364, 728, None), n_jobs: int = 10):
        super().__init__(windows=windows, n_jobs=n_jobs, clip=True)

    def config(self) -> dict:
        return {"model": "LEAR v2", "windows": [w or "all" for w in self.windows],
                "penalty": "Lasso, alpha per hour by time-ordered 20% hold-out on the 364-day window, reused by all windows",
                "solver": "coordinate descent on shared Gram", "vst": "asinh(median/MAD)",
                "clip": "training range in VST space", "outputs": "window average + per-window forecasts",
                "inputs": "DA lags D-1,2,3,7 x24; RT lags D-2,3 x24; load zone+NYISO x24; temp x24; gas; dow; holiday"}

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        D, train = self.design, self._train
        tr_dates = pd.DatetimeIndex(sorted(train["delivery_date"].unique()))
        te_dates = pd.DatetimeIndex(sorted(test["delivery_date"].unique()))
        zones = sorted(test["zone"].unique())
        tasks = [((m, c, z), D.features(m, c, z, tr_dates, energy), D.target(m, c, z, tr_dates),
                  D.features(m, c, z, te_dates, energy)) for m, c, z, energy in self._series(zones)]
        outs = _parallel(_fit_predict_series_v2, [(X_tr, Y_tr, X_te, self.windows) for _, X_tr, Y_tr, X_te in tasks],
                         self.n_jobs)
        variants = {"mean": None, **{f"mean_w{w or 'all'}": w for w in self.windows}}
        frames = {}
        for col, w in variants.items():
            grids: dict[tuple[str, str], list[pd.DataFrame]] = {}
            for ((m, c, z), *_), res in zip(tasks, outs):
                P = np.nanmean(np.stack(list(res.values())), axis=0) if w is None and col == "mean" else res[w]
                for zz in (zones if c == "energy" else [z]):
                    idx = pd.MultiIndex.from_product([[zz], te_dates], names=["zone", "delivery_date"])
                    grids.setdefault((m, c), []).append(pd.DataFrame(P, index=idx, columns=dg.HOURS))
            means = {k: pd.Series(dg.to_rows(pd.concat(v), test), index=test.index) for k, v in grids.items()}
            frames[col] = to_long(test, means)
        out = frames["mean"]
        for col in variants:
            if col != "mean":
                out[col] = frames[col]["mean"].to_numpy()
        return out
