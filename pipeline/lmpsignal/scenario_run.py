"""M4 edge: load stored signal predictions, run `scenarios` over the validation folds, log the runs, write the results page.

Declared in docs/ROADMAP.md ("M4 distributional calibration declaration"). Pure computation is in `scenarios.py`.
Runs are stored like model runs: `scen_<method>` under market "dart" / component "spread" (DA - RT total price spread),
`rt_gpd_tail` as RT total rows (same schema as the signal), so the price scoreboard ignores the first and
diagnostics.daily_losses scores both.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import kstest

from lmpsignal import cv, registry, scenarios
from lmpsignal.config import EXPERIMENTS_DIR, INTERNAL_ZONES
from lmpsignal.dart import SPIKE_DAY
from lmpsignal.diagnostics import completed_runs, daily_losses
from lmpsignal.evaluate import QCOLS, diebold_mariano, kupiec_pof, score_table
from lmpsignal.overfit import holm
from lmpsignal.presets import SIGNAL_V1


def _load(run_id: str, extra: str = "") -> pd.DataFrame:
    d = duckdb.sql(f"""SELECT delivery_date, ts_utc, zone, hour_local, market, mean, y, scored, {', '.join(QCOLS)}{extra}
                       FROM read_parquet('{(EXPERIMENTS_DIR / run_id).as_posix()}/fold=*.parquet')
                       WHERE component = 'total'""").df()
    d["delivery_date"] = pd.to_datetime(d["delivery_date"])
    return d


def _log_folds(name: str, config: dict, df: pd.DataFrame, folds: list[cv.Fold], log: bool,
               diag: pd.DataFrame | None = None) -> str | None:
    run_id = registry.start_run(name, {**config, "folds": len(folds), "first_fold": folds[0].name,
                                       "last_fold": folds[-1].name}, len(df)) if log else None
    for f in folds:
        part = df[(df["delivery_date"] >= pd.Timestamp(f.test_start)) & (df["delivery_date"] < pd.Timestamp(f.test_end))]
        if part.empty or not log:
            continue
        s = part[part["y"].notna() & part[QCOLS].notna().all(axis=1)]
        keys = ["market", "component"]
        scores = pd.concat([score_table(s, keys).assign(zone="ALL"), score_table(s, [*keys, "zone"])])
        registry.save_fold(run_id, f.name, part, scores)
        if diag is not None and (diag["fold"] == f.name).any():
            registry.save_artifact(run_id, f.name, "dependence", diag[diag["fold"] == f.name])
    if log:
        registry.finish_run(run_id)
    return run_id


def run_scenarios(method: scenarios.Method, folds: list[cv.Fold] | None = None, log: bool = True,
                  k: int = 500, seed: int = 0) -> str | None:
    """Joint DA/RT scenarios from signal v1's stored marginals; logged as `scen_<method>`."""
    folds = folds or cv.folds()
    run = completed_runs([SIGNAL_V1])[SIGNAL_V1]
    w = scenarios.to_wide(_load(run)[lambda d: d["zone"].isin(INTERNAL_ZONES) & d["scored"]])
    df, diag = scenarios.spread_forecast(w, folds, method, k=k, seed=seed)
    df = df.assign(market="dart", component="spread", scored=True, ref_mean=np.nan)
    cfg = {"model": f"M4 joint DA/RT scenarios ({method} dependence)", "parent": run, "method": method,
           "samples": k, "seed": seed, "lookback_days": 365, "target": "DA - RT total price, internal zones"}
    return _log_folds(f"scen_{method}", cfg, df, folds, log, diag)


def run_tail(folds: list[cv.Fold] | None = None, log: bool = True) -> str | None:
    """GPD splice of signal v1's RT total q95 / q99; logged as `rt_gpd_tail`."""
    folds = folds or cv.folds()
    run = completed_runs([SIGNAL_V1])[SIGNAL_V1]
    d = _load(run)
    d = d[d["market"] == "rt"]
    df = scenarios.splice_frame(d.reset_index(drop=True), folds).assign(component="total", ref_mean=np.nan)
    cfg = {"model": "M4 EVT: GPD splice above q90 of RT total", "parent": run, "lookback_days": 730,
           "scale": "q95 - q05", "levels": [0.95, 0.99]}
    return _log_folds("rt_gpd_tail", cfg, df, folds, log)


# ------------------------------------------------------------------------------------------ results page

def _dm_rows(runs: dict[str, str], bench: str, market: str, comp: str, days_filter=None) -> pd.DataFrame:
    losses, _ = daily_losses(runs, market, comp, "crps")
    if days_filter is not None:
        losses = losses[days_filter(losses.index)]
    days = pd.Series(losses.index, index=losses.index)
    rows = [{"model": m, "crps": losses[m].mean(), "change": losses[m].mean() / losses[bench].mean() - 1,
             "p": diebold_mariano(losses[m], losses[bench], days)["p_a_better"]} for m in losses if m != bench]
    t = pd.DataFrame(rows)
    t["holm_p"] = holm(t.set_index("model")["p"]).to_numpy()
    return t.assign(bench_crps=losses[bench].mean())


def _md(df: pd.DataFrame) -> str:
    f = lambda v: f"{v:.4g}" if isinstance(v, (float, np.floating)) else str(v)
    return "\n".join(["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns),
                      *("| " + " | ".join(f(v) for v in r) + " |" for r in df.itertuples(index=False))])


def report() -> str:
    """Markdown results from the logged runs: spread CRPS vs independent, dependence recovery, PIT uniformity,
    tail calibration vs signal v1."""
    runs = completed_runs(["scen_indep", "scen_gauss", "scen_emp", "rt_gpd_tail", SIGNAL_V1, "spike_full"])
    out: list[str] = []
    ex = lambda idx: idx != SPIKE_DAY.date()
    spread = {m: runs[m] for m in ("scen_indep", "scen_gauss", "scen_emp") if m in runs}
    if len(spread) == 3:
        out += ["## Joint DA/RT scenarios: DA - RT spread, CRPS vs independent draws (folds 2..36)", ""]
        for lab, flt in (("all days", None), ("excluding 2025-06-24", ex)):
            t = _dm_rows(spread, "scen_indep", "dart", "spread", flt)
            out += [f"{lab} (independent CRPS {t['bench_crps'].iloc[0]:.4g})", "", _md(t.drop(columns="bench_crps")), ""]
        dep = pd.concat([registry.artifact(spread[m], "dependence").assign(model=m) for m in ("scen_gauss", "scen_emp")])
        z = dep.groupby(["model", "zone"])[["rho_fit", "spearman_samples", "spearman_realized"]].mean().reset_index()
        out += ["Rank correlation of the DA / RT PIT pairs, mean over folds: drawn vs realized", "", _md(z.round(3)), ""]
        pit = []
        for m, rid in spread.items():
            p = duckdb.sql(f"SELECT pit FROM read_parquet('{(EXPERIMENTS_DIR / rid).as_posix()}/fold=*.parquet')").df()["pit"]
            pit.append({"model": m, "n": len(p), "ks_stat": kstest(p, "uniform").statistic,
                        "share_in_10_90": float(((p > 0.1) & (p < 0.9)).mean())})
        out += ["Realized spread's PIT under the draws (uniform = calibrated; share in 10-90% should be 0.8)", "",
                _md(pd.DataFrame(pit)), ""]
    if "rt_gpd_tail" in runs and SIGNAL_V1 in runs:
        base = _load(runs[SIGNAL_V1])
        base = base[base["market"] == "rt"]
        cand = _load(runs["rt_gpd_tail"])
        sp = _load(runs["spike_full"], ", spike")[["ts_utc", "zone", "spike"]]
        key = ["ts_utc", "zone"]
        m = base.merge(cand[[*key, *QCOLS]], on=key, suffixes=("", "_c")).merge(sp, on=key, how="left")
        m = m[m["scored"] & m["y"].notna() & m["q05"].notna()]
        from lmpsignal.evaluate import crps_rows
        rows = []
        for lab, sfx in (("signal v1", ""), ("rt_gpd_tail", "_c")):
            Q = m[[c + sfx for c in QCOLS]].to_numpy(float)
            cr = crps_rows(m["y"].to_numpy(float), Q)
            sph = (m["spike"] == 1).to_numpy()
            k95, k99 = (kupiec_pof((m["y"] > m["q" + q + sfx]).to_numpy(), p) for q, p in (("95", 0.05), ("99", 0.01)))
            rows.append({"model": lab, "n": len(m), "crps": cr.mean(), "crps_spike_hours": cr[sph].mean(),
                         "miss95": k95["miss_rate"], "kupiec_p95": k95["p_value"],
                         "miss99": k99["miss_rate"], "kupiec_p99": k99["p_value"]})
        out += ["## EVT: GPD splice above q90 of RT total (folds 2..36, internal and external zones)", "",
                _md(pd.DataFrame(rows)), ""]
        m = m.assign(day=m["delivery_date"].dt.date)
        for lab, sel in (("RT total", np.ones(len(m), bool)), ("spike hours", (m["spike"] == 1).to_numpy())):
            for dl, keep in (("all days", np.ones(len(m), bool)), ("excl. 2025-06-24", (m["day"] != SPIKE_DAY.date()).to_numpy())):
                g = m[sel & keep]
                la, lb = (pd.Series(crps_rows(g["y"].to_numpy(float), g[[c + s for c in QCOLS]].to_numpy(float)), index=g.index)
                          for s in ("_c", ""))
                dm = diebold_mariano(la, lb, g["day"])
                out.append(f"- CRPS {lab}, {dl}: {la.mean() / lb.mean() - 1:+.2%} vs signal v1, DM one-sided p = {dm['p_a_better']:.3f}")
        out.append("")
    return "\n".join(out)
