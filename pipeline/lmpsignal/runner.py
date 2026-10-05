"""Run a model over the time-block CV folds, score each fold, and log everything to the registry."""
from __future__ import annotations

import pandas as pd

from lmpsignal import cv, registry
from lmpsignal.config import EMBARGO_DAYS
from lmpsignal.evaluate import QCOLS, score_table
from lmpsignal.models.base import EmpiricalQuantiles, Model, truth_long

REFERENCE = "lago_naive"   # rMAE denominator for every model


def _slice(p: pd.DataFrame, start, end) -> pd.DataFrame:
    d = p["delivery_date"]
    return p[(d >= pd.Timestamp(start)) & (d < pd.Timestamp(end))]


def run(model: Model, p: pd.DataFrame, folds: list[cv.Fold] | None = None, reference: Model | None = None,
        verbose: bool = True, quantiles: str = "model", log: bool = True, resid_lookback_days: int = 365) -> str | None:
    """Fit/predict every fold, score, and (if log) record everything in the registry.

    quantiles="model": the model supplies its own quantiles (e.g. naive + empirical residuals).
    quantiles="oos_residual": point forecast + empirical quantiles of this run's own *out-of-sample* errors
        from earlier folds whose delivery dates end before the current fold's training end (so the error
        distribution never uses information from the scored month). The first fold has no history and gets
        no quantiles; probabilistic metrics then cover folds 2..n.
    log=False: smoke-test mode, nothing is written to the registry (so it does not count as a trial).
    """
    folds = folds or cv.folds()
    config = {**model.config(), "folds": len(folds), "embargo_days": EMBARGO_DAYS, "quantiles": quantiles,
              "first_fold": folds[0].name, "last_fold": folds[-1].name}
    run_id = registry.start_run(model.name, config, len(p), panel=p) if log else None
    if hasattr(model, "prepare"):
        model.prepare(p)
    history: list[pd.DataFrame] = []
    try:
        for f in folds:
            train, test = _slice(p, f.train_start, f.train_end), _slice(p, f.test_start, f.test_end)
            pred = model.fit(train).predict(test)
            if quantiles == "oos_residual":
                pred = _oos_quantiles(pred, history, f, resid_lookback_days)
            joined = pred.merge(truth_long(test)[["ts_utc", "zone", "market", "component", "y", "scored"]],
                                on=["ts_utc", "zone", "market", "component"])
            if reference is not None:
                ref = reference.fit(train).predict(test)[["ts_utc", "zone", "market", "component", "mean"]]
                joined = joined.merge(ref.rename(columns={"mean": "ref_mean"}), on=["ts_utc", "zone", "market", "component"])
            history.append(joined[["delivery_date", "market", "component", "zone", "hour_local", "y", "mean", "scored"]])
            scored = joined[joined["scored"] & joined["y"].notna() & joined["mean"].notna()]
            naive_col = "ref_mean" if reference is not None else None
            by_zone = score_table(scored, ["market", "component", "zone"], naive_col)
            overall = score_table(scored, ["market", "component"], naive_col).assign(zone="ALL")
            if log:
                registry.save_fold(run_id, f.name, joined, pd.concat([overall, by_zone]))
                if hasattr(model, "artifacts"):
                    for name, art in model.artifacts().items():
                        registry.save_artifact(run_id, f.name, name, art)
            if verbose:
                comp = "total" if (overall["component"] == "total").any() else overall["component"].iloc[0]
                t = overall[(overall["component"] == comp)]
                print(f"  {model.name:<16} {f.name}  " + "  ".join(
                    f"{r.market}: MAE {r.mae:6.2f}" + (f" rMAE {r.rmae:4.2f}" if hasattr(r, "rmae") else "")
                    + (f" CRPS {r.crps:6.2f}" if hasattr(r, "crps") and r.crps == r.crps else "")
                    for r in t.itertuples()), flush=True)
        if log and getattr(model, "diag", None):
            import json

            from lmpsignal.config import EXPERIMENTS_DIR
            (EXPERIMENTS_DIR / run_id / "diagnostics.json").write_text(json.dumps(model.diag, indent=1))
        if log:
            registry.finish_run(run_id)
    except Exception as e:
        if log:
            registry.finish_run(run_id, "failed", error=f"{type(e).__name__}: {e}"[:2000])
        raise
    return run_id


def _oos_quantiles(pred: pd.DataFrame, history: list[pd.DataFrame], fold: cv.Fold, lookback_days: int) -> pd.DataFrame:
    if not history:
        return pred
    h = pd.concat(history, ignore_index=True)
    end = pd.Timestamp(fold.train_end)
    h = h[(h["delivery_date"] < end) & (h["delivery_date"] >= end - pd.Timedelta(days=lookback_days)) & h["scored"]]
    if h.empty:
        return pred
    return EmpiricalQuantiles(lookback_days=lookback_days).fit(h).apply(pred)


def summary(run_ids: list[str]) -> pd.DataFrame:
    """Pooled validation metrics per run (recomputed from stored predictions, not averaged fold metrics)."""
    rows = []
    for rid in run_ids:
        pr = registry.predictions(rid)
        pr = pr[pr["scored"] & pr["y"].notna() & pr["mean"].notna()]
        for (m, c), g in pr.groupby(["market", "component"]):
            s = score_table(g.assign(_k=1), ["_k"], "ref_mean" if "ref_mean" in g else None).iloc[0].to_dict()
            s.pop("_k", None)
            rows.append({"run_id": rid, "model": rid.rsplit("-", 2)[0], "market": m, "component": c, **s})
    return pd.DataFrame(rows)


__all__ = ["run", "summary", "REFERENCE", "QCOLS"]
