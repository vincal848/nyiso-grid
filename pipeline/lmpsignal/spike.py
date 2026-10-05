"""M3b: RT spike member (declared in docs/ROADMAP.md, "M3b declaration", before any run).

Spike = RT total price >= the zone's 95th percentile of RT total over the 365 training days before the fold's training
end (11 internal zones). Per fold:
  P(spike) per zone-hour: L1-regularized logistic regression pooled over zones (zone and 4-hour-block indicators),
      penalty chosen by time-ordered 3-fold CV inside the training window (log loss). Features as of 05:00 ET D-1:
      reserve prices and shortage counts, decayed counts of recent zone spikes (RT through D-2), load-forecast
      surprise, HRRR storm proxy (CAPE p90 x reflectivity share, x load), temperature extremes, DAM-list outage
      counts, gas, yesterday's DA price level.
      Deviation from the declaration: outages are counted system-wide (and 345 kV), because equipment names cannot be
      mapped to NYC/LI without a network model.
  Spike magnitude: threshold + generalized Pareto excess, fit per zone on the last 730 training days (pooled over
      zones when a zone has fewer than 50 spikes).
Output per (zone, hour): p_spike, threshold, GPD (xi, sigma), the spike-conditional distribution's mean and quantiles.
Stored like a model run (market "rt", component "total", so post-processing can mix it into the signal) and scored
under market "spike" (Brier / log loss vs in-fold climatology and vs "spiked at D-2, same hour"), so the price
scoreboard ignores it. Integration: postprocess op "spike_mix".
"""
from __future__ import annotations

import time
import warnings

import numpy as np
import pandas as pd
from scipy.stats import genpareto
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit

from lmpsignal import cv, registry
from lmpsignal.config import EMBARGO_DAYS, INTERNAL_ZONES, QUANTILES
from lmpsignal.evaluate import QCOLS

THRESH_Q, THRESH_DAYS, GPD_DAYS, MIN_SPIKES = 0.95, 365, 730, 50
DECAY, DECAY_DAYS = 0.7, 30
STORM = ["storm", "storm_x_load", "hrrr_lightning_zone", "hrrr_cape_zone"]
BASE_FEATURES = ["rt_spin_max_24h", "rt_spin_mean_24h", "rt_shortage_7d", "da_spin_max_d1", "spike_d2_h", "spike_decay",
                 "spike_freq7", "load_surprise_zone", "load_surprise_nyiso", "hrrr_cdh", "hrrr_hdh", "dam_outages_d",
                 "dam_outages_345_d", "gas_hh", "lag_da_d1_total", "rt_d2_std"]
VARIANTS = {"full": BASE_FEATURES + STORM, "no_storm": BASE_FEATURES}


def frame(p: pd.DataFrame) -> pd.DataFrame:
    d = p[p["zone"].isin(INTERNAL_ZONES)].copy()
    t = d["hrrr_temp_zone"].fillna(d["temp_fcst_zone"])
    d["hrrr_cdh"] = (t - 18.3).clip(lower=0)
    d["hrrr_hdh"] = (18.3 - t).clip(lower=0)
    d["storm"] = d["hrrr_cape_zone"].fillna(0) / 1000 * d["hrrr_refl40_zone"].fillna(0)
    d["storm_x_load"] = d["storm"] * d["load_fcst_zone"] / 1000
    d["hour_block"] = (d["hour_local"] // 4).astype(int)
    return d.sort_values(["zone", "ts_utc"]).reset_index(drop=True)


def _history_features(d: pd.DataFrame, thr: pd.Series) -> pd.DataFrame:
    """Spike-history features relative to this fold's thresholds; only RT days <= D-2 are used."""
    g = d.pivot_table(index=["zone", "delivery_date"], columns="hour_local", values="rt_total", aggfunc="mean")
    s = (g.ge(thr.reindex(g.index.get_level_values("zone")).to_numpy()[:, None])) & g.notna()
    any_day = s.any(axis=1).astype(float)
    out = []
    for zone, a in any_day.groupby(level="zone"):
        a = a.droplevel("zone")
        a = a.reindex(pd.date_range(a.index.min(), a.index.max(), freq="D"), fill_value=0.0)
        decay = sum(DECAY ** (k - 2) * a.shift(k) for k in range(2, DECAY_DAYS + 2)).fillna(0.0)
        freq7 = a.shift(2).rolling(7, min_periods=1).mean().fillna(0.0)
        out.append(pd.DataFrame({"zone": zone, "delivery_date": a.index, "spike_decay": decay.to_numpy(),
                                 "spike_freq7": freq7.to_numpy()}))
    daily = pd.concat(out, ignore_index=True)
    sh = s.astype(float).stack().rename("spike_now").reset_index()
    sh["delivery_date"] = sh["delivery_date"] + pd.Timedelta(days=2)                 # the D-2 value, seen on D
    sh = sh.rename(columns={"spike_now": "spike_d2_h"})
    return daily, sh


def _design(d: pd.DataFrame, feats: list[str], stats=None):
    X = d[feats].astype(float)
    if stats is None:
        stats = (X.mean(), X.std().replace(0, 1).fillna(1))
    X = ((X - stats[0]) / stats[1]).fillna(0.0)
    for z in INTERNAL_ZONES[1:]:
        X[f"z_{z}"] = (d["zone"] == z).astype(float).to_numpy()
    for b in range(1, 6):
        X[f"hb_{b}"] = (d["hour_block"] == b).astype(float).to_numpy()
    return X.to_numpy(), stats


class SpikeMember:
    def __init__(self, variant: str = "full"):
        self.variant = variant
        self.features = VARIANTS[variant]
        self.name = "spike_full" if variant == "full" else f"spike_{variant}"

    def config(self) -> dict:
        return {"model": "M3b spike member: L1 logistic P(spike) + per-zone GPD excess", "variant": self.variant,
                "features": self.features, "threshold": f"zone q{int(THRESH_Q * 100)} of RT total, last {THRESH_DAYS} "
                "training days", "gpd_days": GPD_DAYS, "decay": DECAY, "penalty": "L1, C by TimeSeriesSplit(3) log loss"}

    def fit(self, tr: pd.DataFrame, thr: pd.Series) -> SpikeMember:
        X, self.stats = _design(tr, self.features)
        y = tr["spike"].to_numpy()
        best, self.clf = None, None
        for C in (0.003, 0.01, 0.03, 0.1, 0.3):                     # time-ordered CV, log loss
            losses = []
            for a, b in TimeSeriesSplit(3).split(X):
                m = LogisticRegression(penalty="l1", C=C, solver="liblinear", max_iter=500).fit(X[a], y[a])
                pr = np.clip(m.predict_proba(X[b])[:, 1], 1e-4, 1 - 1e-4)
                losses.append(-np.mean(y[b] * np.log(pr) + (1 - y[b]) * np.log(1 - pr)))
            if best is None or np.mean(losses) < best[0]:
                best = (np.mean(losses), C)
        self.C = best[1]
        self.clf = LogisticRegression(penalty="l1", C=self.C, solver="liblinear", max_iter=500).fit(X, y)
        # magnitude: GPD of excess over the threshold, per zone (pooled fallback)
        recent = tr[tr["delivery_date"] > tr["delivery_date"].max() - pd.Timedelta(days=GPD_DAYS)]
        exc = recent.loc[recent["spike"] == 1, ["zone", "rt_total"]].assign(e=lambda x: x["rt_total"] - thr.reindex(x["zone"]).to_numpy())
        exc = exc[exc["e"] > 0]
        pooled = genpareto.fit(exc["e"], floc=0)
        self.gpd = {}
        for z in INTERNAL_ZONES:
            e = exc.loc[exc["zone"] == z, "e"]
            self.gpd[z] = genpareto.fit(e, floc=0) if len(e) >= MIN_SPIKES else pooled
        self.thr = thr
        return self

    def predict(self, te: pd.DataFrame) -> pd.DataFrame:
        X, _ = _design(te, self.features, self.stats)
        out = te[["delivery_date", "ts_utc", "zone", "hour_local", "rt_total", "score_rt", "spike", "spike_d2_h"]].copy()
        out["p_spike"] = self.clf.predict_proba(X)[:, 1]
        out["thr"] = out["zone"].map(self.thr)
        xi = out["zone"].map(lambda z: self.gpd[z][0]).to_numpy()
        sig = out["zone"].map(lambda z: self.gpd[z][2]).to_numpy()
        out["xi"], out["sigma"] = xi, sig
        qs = np.asarray(QUANTILES)
        Q = out["thr"].to_numpy()[:, None] + genpareto.ppf(qs[None, :], xi[:, None], 0, sig[:, None])
        out[QCOLS] = Q
        mean_exc = np.where(xi < 0.9, sig / (1 - np.minimum(xi, 0.9)), Q[:, -1] - out["thr"].to_numpy())
        out["mean"] = out["thr"] + np.minimum(mean_exc, Q[:, -1] - out["thr"].to_numpy())   # capped at the q99
        return out


def _scores(o: pd.DataFrame, clim: pd.Series) -> pd.DataFrame:
    o = o[o["score_rt"] & o["rt_total"].notna()]
    rows = []
    for zone, g in [*o.groupby("zone"), ("ALL", o)]:
        yy = g["spike"].to_numpy()
        p = np.clip(g["p_spike"].to_numpy(), 1e-4, 1 - 1e-4)
        pc = np.clip(g["zone"].map(clim).to_numpy(), 1e-4, 1 - 1e-4)
        pp = np.clip(g["spike_d2_h"].fillna(0).to_numpy() * 0.5 + 0.02, 1e-4, 1 - 1e-4)   # persistence as a probability
        ll = lambda q, yy=yy: float(-np.mean(yy * np.log(q) + (1 - yy) * np.log(1 - q)))
        rows.append({"market": "spike", "component": "rt_total", "zone": str(zone), "base_rate": float(yy.mean()),
                     "brier": float(np.mean((p - yy) ** 2)), "brier_clim": float(np.mean((pc - yy) ** 2)),
                     "brier_persist": float(np.mean((pp - yy) ** 2)), "logloss": ll(p), "logloss_clim": ll(pc),
                     "logloss_persist": ll(pp)})
    return pd.DataFrame(rows)


def fold_data(base: pd.DataFrame, f: cv.Fold) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """Training rows, test rows and per-zone thresholds for one fold (thresholds from the fold's training data)."""
    in_train = (base["delivery_date"] >= pd.Timestamp(f.train_start)) & (base["delivery_date"] < pd.Timestamp(f.train_end))
    recent = in_train & (base["delivery_date"] >= pd.Timestamp(f.train_end) - pd.Timedelta(days=THRESH_DAYS))
    thr = base[recent].groupby("zone")["rt_total"].quantile(THRESH_Q)
    daily, sh = _history_features(base[base["delivery_date"] < pd.Timestamp(f.test_end)], thr)
    d = (base.drop(columns=[c for c in ("spike_decay", "spike_freq7", "spike_d2_h") if c in base])
         .merge(daily, on=["zone", "delivery_date"], how="left")
         .merge(sh, on=["zone", "delivery_date", "hour_local"], how="left"))
    d["spike"] = (d["rt_total"] >= d["zone"].map(thr)).astype(int)
    tr = d[in_train.to_numpy() & d["rt_total"].notna().to_numpy()]
    te = d[(d["delivery_date"] >= pd.Timestamp(f.test_start)) & (d["delivery_date"] < pd.Timestamp(f.test_end))]
    return tr, te, thr


def run(variant: str, p: pd.DataFrame, folds: list[cv.Fold] | None = None, log: bool = True) -> str | None:
    warnings.filterwarnings("ignore")
    member = SpikeMember(variant)
    folds = folds or cv.folds()
    base = frame(p)
    run_id = registry.start_run(member.name, {**member.config(), "folds": len(folds), "embargo_days": EMBARGO_DAYS,
                                              "first_fold": folds[0].name, "last_fold": folds[-1].name}, len(base), panel=p) if log else None
    try:
        for f in folds:
            t0 = time.time()
            tr, te, thr = fold_data(base, f)
            member.fit(tr, thr)
            o = member.predict(te)
            clim = tr.groupby("zone")["spike"].mean()
            s = _scores(o, clim)
            a = s[s["zone"] == "ALL"].iloc[0]
            print(f"  {member.name:<15} {f.name}  base {a.base_rate:.3f}  Brier {a.brier:.4f} (clim {a.brier_clim:.4f}, "
                  f"persist {a.brier_persist:.4f})  logloss {a.logloss:.4f} (clim {a.logloss_clim:.4f})  C={member.C}  "
                  f"{time.time() - t0:.0f}s", flush=True)
            if log:
                keep = o.assign(market="rt", component="total", y=o["rt_total"], scored=o["score_rt"], ref_mean=np.nan)
                keep = keep[["delivery_date", "ts_utc", "zone", "hour_local", "market", "component", "y", "scored", "ref_mean",
                             "mean", *QCOLS, "p_spike", "thr", "xi", "sigma", "spike"]]
                registry.save_fold(run_id, f.name, keep, s)
                coef = pd.DataFrame({"feature": member.features + [f"z_{z}" for z in INTERNAL_ZONES[1:]] +
                                     [f"hb_{b}" for b in range(1, 6)], "coef": member.clf.coef_[0]})
                registry.save_artifact(run_id, f.name, "coefficients", coef.assign(C=member.C))
        if log:
            registry.finish_run(run_id)
    except Exception as e:
        if log:
            registry.finish_run(run_id, "failed", f"{type(e).__name__}: {e}"[:2000])
        raise
    return run_id
