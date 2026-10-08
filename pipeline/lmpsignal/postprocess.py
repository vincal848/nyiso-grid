"""Post-processing over stored out-of-sample predictions: clip, combine, calibrate. No model refits.

Each post-processing run reads its parents' predictions from the registry, applies one or more steps,
and is logged as its own trial (config records the parents and steps), so the overfitting
diagnostics count it. A step may only use information available at issue time:

clip       Bound each forecast to [min, max] of its target (market, component, zone, local hour) over
           the delivery days before the fold's training end. Equivalent to LEAR's VST-space clip,
           because the asinh transform is monotone.
combine    Weighted average of parents' point forecasts. 'equal', or 'inv_mae': weights proportional
           to 1/MAE of each parent over earlier folds (delivery before the fold's training end,
           trailing 365 days), per (market, component).
windows    For runs that stored per-variant outputs (LEAR v2: mean_w56, mean_w364, ...), set the point
           forecast to the average of the chosen variants.
assemble   Build a forecast from components of different parents: energy, loss and congestion each
           come from a named parent run, and total = energy + loss + congestion.
calibrate  Quantiles around the point forecast.
           'oos_residual': static per-fold empirical residual quantiles (as in runner.run).
           'aci': adaptive conformal inference (Gibbs & Candès 2021). For every (market, component,
           zone, hour) the residual quantiles come from a trailing window of this run's own OOS
           residuals, and each central interval's miscoverage level is updated online:
               alpha_{t+1} = alpha_t + gamma * (alpha_target - err_t)
           Updates use outcomes of delivery days <= D-2 only (known before 05:00 on D-1).
"""
from __future__ import annotations

import json

import duckdb
import numpy as np
import pandas as pd

from lmpsignal import cv, registry
from lmpsignal.config import EXPERIMENTS_DIR, QUANTILES
from lmpsignal.evaluate import QCOLS, score_table

KEYS = ["delivery_date", "ts_utc", "zone", "hour_local", "market", "component"]


def load_run(run_id: str, cols=("mean",)) -> pd.DataFrame:
    """Stored predictions of a run. 'runA+runB' concatenates runs (M7: validation run + its holdout continuation)."""
    if "+" in run_id:
        return pd.concat([load_run(r, cols) for r in run_id.split("+")], ignore_index=True)
    path = (EXPERIMENTS_DIR / run_id).as_posix()
    have = {r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}/fold=*.parquet')").fetchall()}
    cols = [c for c in cols if c in have]
    extra = ", ".join(cols)
    df = duckdb.sql(f"""SELECT {', '.join(KEYS)}, {extra}, y, scored, ref_mean
                        FROM read_parquet('{(EXPERIMENTS_DIR / run_id).as_posix()}/fold=*.parquet')""").df()
    df["delivery_date"] = pd.to_datetime(df["delivery_date"])
    return df


# ------------------------------------------------------------------------------------------ steps

def clip_to_history(df: pd.DataFrame, panel: pd.DataFrame, folds: list[cv.Fold]) -> pd.DataFrame:
    out = []
    long = []
    for m in ("da", "rt"):
        for c in ("total", "energy", "loss", "congestion"):
            long.append(panel[["delivery_date", "zone", "hour_local"]].assign(market=m, component=c,
                                                                                v=panel[f"{m}_{c}"].to_numpy()))
    hist = pd.concat(long, ignore_index=True).dropna(subset=["v"])
    for f in folds:
        part = df[(df["delivery_date"] >= pd.Timestamp(f.test_start)) & (df["delivery_date"] < pd.Timestamp(f.test_end))]
        h = hist[hist["delivery_date"] < pd.Timestamp(f.train_end)]
        rng = h.groupby(["market", "component", "zone", "hour_local"])["v"].agg(["min", "max"]).reset_index()
        part = part.merge(rng, on=["market", "component", "zone", "hour_local"], how="left")
        part["mean"] = part["mean"].clip(lower=part["min"], upper=part["max"])
        out.append(part.drop(columns=["min", "max"]))
    return pd.concat(out, ignore_index=True)


def combine(parents: dict[str, pd.DataFrame], folds: list[cv.Fold], weights: str = "equal",
            lookback_days: int = 365) -> tuple[pd.DataFrame, list[dict]]:
    names = list(parents)
    base = parents[names[0]][KEYS + ["y", "scored", "ref_mean"]].copy()
    M = np.column_stack([parents[n].set_index(KEYS)["mean"].reindex(pd.MultiIndex.from_frame(base[KEYS])).to_numpy()
                         for n in names])
    log = []
    mean = np.full(len(base), np.nan)
    for f in folds:
        te = ((base["delivery_date"] >= pd.Timestamp(f.test_start)) & (base["delivery_date"] < pd.Timestamp(f.test_end))).to_numpy()
        for (m, c), idx in base[te].groupby(["market", "component"]).groups.items():
            rows = base.index.get_indexer(idx)
            if weights == "equal":
                w = np.ones(len(names)) / len(names)
            else:
                end = pd.Timestamp(f.train_end)
                past = ((base["market"] == m) & (base["component"] == c) & base["scored"] & base["y"].notna()
                        & (base["delivery_date"] < end) & (base["delivery_date"] >= end - pd.Timedelta(days=lookback_days))).to_numpy()
                if past.sum() == 0:
                    w = np.ones(len(names)) / len(names)
                else:
                    mae = np.nanmean(np.abs(M[past] - base.loc[past, "y"].to_numpy()[:, None]), axis=0)
                    w = (1 / mae) / np.sum(1 / mae)
            mean[rows] = M[rows] @ w
            log.append({"fold": f.name, "market": m, "component": c, **{f"w_{n}": float(x) for n, x in zip(names, w)}})
    base["mean"] = mean
    return base, log


def select_windows(df: pd.DataFrame, use: list[str]) -> pd.DataFrame:
    cols = [f"mean_{u}" for u in use]
    missing = [c for c in cols if c not in df]
    if missing:
        raise ValueError(f"parent run has no stored {missing}")
    out = df.copy()
    out["mean"] = out[cols].mean(axis=1, skipna=True)
    return out.drop(columns=[c for c in out if c.startswith("mean_")])


def assemble(parents: dict[str, pd.DataFrame], mapping: dict[str, str]) -> pd.DataFrame:
    """mapping: component -> parent run id. Returns rows for energy, loss, congestion (from their parents)
    and total = their sum; truth / masks come from the congestion parent."""
    parts = {}
    for comp, rid in mapping.items():
        d = parents[rid]
        parts[comp] = d[d["component"] == comp].set_index(["delivery_date", "ts_utc", "zone", "hour_local", "market"])
    base = parts["congestion"]
    idx = base.index
    comps = [parts[c]["mean"].reindex(idx) for c in ("energy", "loss", "congestion")]
    total = sum(comps)
    ref = parents[mapping["congestion"]]
    tot_truth = ref[ref["component"] == "total"].set_index(idx.names)[["y", "scored", "ref_mean"]].reindex(idx)
    rows = []
    for comp in ("energy", "loss", "congestion"):
        d = parts[comp].reset_index()[KEYS[:4] + ["market", "component", "mean", "y", "scored", "ref_mean"]]
        rows.append(d)
    tot = tot_truth.assign(mean=total.to_numpy(), component="total").reset_index()
    rows.append(tot[KEYS[:4] + ["market", "component", "mean", "y", "scored", "ref_mean"]])
    out = pd.concat(rows, ignore_index=True)
    return out[KEYS + ["mean", "y", "scored", "ref_mean"]]


def calibrate_oos_residual(df: pd.DataFrame, folds: list[cv.Fold], lookback_days: int = 365) -> pd.DataFrame:
    from lmpsignal.runner import _oos_quantiles

    out, history = [], []
    for f in folds:
        part = df[(df["delivery_date"] >= pd.Timestamp(f.test_start)) & (df["delivery_date"] < pd.Timestamp(f.test_end))]
        pred = _oos_quantiles(part.drop(columns=[c for c in QCOLS if c in part]), history, f, lookback_days)
        out.append(pred)
        history.append(part[["delivery_date", "market", "component", "zone", "hour_local", "y", "mean", "scored"]])
    return pd.concat(out, ignore_index=True)


def calibrate_aci(df: pd.DataFrame, window_days: int = 365, gamma: float = 0.01, min_obs: int = 30,
                  lag_days: int = 2) -> pd.DataFrame:
    """Adaptive conformal quantiles per (market, component, zone, hour). See module docstring."""
    qs = np.asarray(QUANTILES)
    lo_levels = qs[qs < 0.5]
    targets = 1 - 2 * lo_levels                        # central interval coverage for each lower level
    df = df.sort_values(["market", "component", "zone", "hour_local", "delivery_date", "ts_utc"]).reset_index(drop=True)
    Q = np.full((len(df), len(qs)), np.nan)
    for _, g in df.groupby(["market", "component", "zone", "hour_local"], sort=False):
        idx = g.index.to_numpy()
        days = g["delivery_date"].to_numpy()
        mean, y = g["mean"].to_numpy(float), g["y"].to_numpy(float)
        valid = g["scored"].to_numpy() & np.isfinite(y) & np.isfinite(mean)
        r = np.where(valid, y - mean, np.nan)
        alpha = 1 - targets.copy()                     # current miscoverage per central level
        day_ns = days.astype("datetime64[D]").astype(np.int64)
        pending = []                                   # (known_from_day, row, lo_q, hi_q) awaiting feedback
        for i in range(len(g)):
            d = day_ns[i]
            # apply feedback from rows whose outcome is known by now (delivery day <= d - lag_days)
            keep = []
            for (known, j, lo, hi) in pending:
                if known <= d:
                    if valid[j]:
                        err = ((r[j] < lo) | (r[j] > hi)).astype(float)
                        alpha = np.clip(alpha + gamma * ((1 - targets) - err), 1e-4, 0.999)
                else:
                    keep.append((known, j, lo, hi))
            pending = keep
            a_ = np.searchsorted(day_ns, d - lag_days - window_days, side="right")
            b_ = min(np.searchsorted(day_ns, d - lag_days, side="right"), i)
            seg = r[a_:b_]
            rp = seg[np.isfinite(seg)]
            if len(rp) < min_obs:
                continue
            lo = np.quantile(rp, np.clip(alpha / 2, 0, 1))
            hi = np.quantile(rp, np.clip(1 - alpha / 2, 0, 1))
            med = np.quantile(rp, 0.5)
            Q[idx[i]] = mean[i] + np.sort(np.concatenate([lo, [med], hi]))
            pending.append((d + lag_days, i, lo, hi))
    out = df.copy()
    out[QCOLS] = Q
    return out


# ------------------------------------------------------------------------------------------ runs

def apply(loaded: dict[str, pd.DataFrame], steps: list[dict], panel: pd.DataFrame | None,
          folds: list[cv.Fold]) -> tuple[pd.DataFrame, list[dict]]:
    """Apply `steps` (in order) to in-memory parent predictions {name: frame}; no registry access.
    Used by `run` (logged trials) and by the daily live forecast (lmpsignal/live.py)."""
    parents = list(loaded)
    extra_log: list[dict] = []
    if steps and steps[0]["op"] == "assemble":
        df = assemble(loaded, steps[0]["components"])
        steps = steps[1:]
    elif steps and steps[0]["op"] == "combine":
        df, extra_log = combine(loaded, folds, steps[0].get("weights", "equal"))
        steps = steps[1:]
    else:
        if len(parents) != 1:
            raise ValueError("multiple parents require a leading combine step")
        df = loaded[parents[0]]
    for st in steps:
        if st["op"] == "windows":
            df = select_windows(df, st["use"])
            continue
        if st["op"] == "clip":
            df = clip_to_history(df, panel, folds)
        elif st["op"] == "calibrate" and st["method"] == "aci":
            df = calibrate_aci(df, **{k: v for k, v in st.items() if k not in ("op", "method")})
        elif st["op"] == "calibrate" and st["method"] == "oos_residual":
            df = calibrate_oos_residual(df, folds)
        else:
            raise ValueError(st)
    for c in QCOLS:
        if c not in df:
            df[c] = np.nan
    return df, extra_log


def run(name: str, parents: list[str], steps: list[dict], panel: pd.DataFrame | None = None,
        folds: list[cv.Fold] | None = None, log: bool = True) -> tuple[str | None, pd.DataFrame]:
    """Apply `steps` (in order) to parent runs and score/log the result as a new trial.

    steps: [{"op": "combine", "weights": "equal"|"inv_mae"}, {"op": "clip"},
            {"op": "calibrate", "method": "aci"|"oos_residual", ...}]
    """
    folds = folds or cv.folds()
    requested = [dict(s) for s in steps]
    want = ["mean"] + (["mean_w56", "mean_w364", "mean_w728", "mean_wall"]
                       if any(s["op"] == "windows" for s in steps) else [])
    df, extra_log = apply({p: load_run(p, want) for p in parents}, steps, panel, folds)
    config = {"postprocess": True, "parents": parents, "steps": requested,
              "folds": len(folds), "first_fold": folds[0].name, "last_fold": folds[-1].name}
    run_id = registry.start_run(name, json.loads(json.dumps(config, default=str)), len(df)) if log else None
    for f in folds:
        part = df[(df["delivery_date"] >= pd.Timestamp(f.test_start)) & (df["delivery_date"] < pd.Timestamp(f.test_end))]
        s = part[part["scored"] & part["y"].notna() & part["mean"].notna()]
        by_zone = score_table(s, ["market", "component", "zone"], "ref_mean")
        overall = score_table(s, ["market", "component"], "ref_mean").assign(zone="ALL")
        if log:
            registry.save_fold(run_id, f.name, part, pd.concat([overall, by_zone]))
    if log:
        registry.finish_run(run_id)
    return run_id, pd.DataFrame(extra_log)
