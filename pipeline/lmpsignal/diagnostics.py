"""Build per-trial daily performance series from the registry and run the overfitting diagnostics.

Trials = every completed run in the registry (each run is one model configuration tried).
Daily loss = MAE over the day's scored (hour, zone) rows for one market/component.
Skill vs a benchmark run = benchmark daily loss − trial daily loss ($/MWh; > 0 = trial better).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from lmpsignal import overfit, registry
from lmpsignal.config import EXPERIMENTS_DIR
from lmpsignal.evaluate import diebold_mariano


LOSSES = ("crps", "se", "ae")     # CRPS and squared error are primary; absolute error secondary


def daily_losses(runs: dict[str, str], market: str, component: str = "total",
                 loss: str = "crps") -> tuple[pd.DataFrame, pd.DataFrame]:
    """(T x N daily mean-loss matrix with columns = model names, T x N scored-row counts).

    Days where any trial lacks a loss (e.g. no quantiles in a model's first fold) are dropped, so every
    trial is compared on the same days."""
    from lmpsignal.evaluate import QCOLS, crps_rows

    con = duckdb.connect()
    frames, counts = {}, {}
    for model, rid in runs.items():
        path = (EXPERIMENTS_DIR / rid).as_posix()
        have = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{path}/*.parquet')").fetchall()}
        qsel = ", " + ", ".join(QCOLS) if loss == "crps" and set(QCOLS) <= have else ""
        df = con.execute(f"""SELECT CAST(delivery_date AS DATE) AS day, y, mean {qsel}
                             FROM read_parquet('{path}/*.parquet')
                             WHERE scored AND y IS NOT NULL AND mean IS NOT NULL AND market = ? AND component = ?""",
                         [market, component]).df()
        if df.empty:
            continue
        y, f = df["y"].to_numpy(float), df["mean"].to_numpy(float)
        if loss == "crps":
            row = crps_rows(y, df[QCOLS].to_numpy(float)) if qsel else np.full(len(df), np.nan)
        elif loss == "se":
            row = (y - f) ** 2
        else:
            row = np.abs(y - f)
        g = pd.DataFrame({"day": df["day"], "l": row}).groupby("day")["l"]
        frames[model], counts[model] = g.mean(), g.size()
    losses = pd.DataFrame(frames).dropna()
    return losses, pd.DataFrame(counts).reindex(losses.index)


def run_diagnostics(runs: dict[str, str], benchmark: str, market: str, component: str = "total",
                    S: int = 16, bootstrap: int = 2000, configs_tried: int | None = None, loss: str = "crps") -> dict:
    """configs_tried: number of distinct configurations ever run (all registry runs, any status). The
    implied independent N uses it with the average correlation estimated from the available trials."""
    losses, counts = daily_losses(runs, market, component, loss)
    aligned = bool((counts.nunique(axis=1) == 1).all())      # same scored rows each day for every trial
    skill = losses[[benchmark]].to_numpy() - losses                # T x N, benchmark column = 0

    # Sharpe inference on each trial's daily skill
    rows = []
    for m in skill.columns:
        mo = overfit.moments(skill[m].to_numpy())
        rows.append({"model": m, **mo})
    per = pd.DataFrame(rows).set_index("model")
    trials = per.drop(index=benchmark, errors="ignore")
    var_sr = float(trials["sr"].var(ddof=1)) if len(trials) > 1 else float("nan")
    _, rho = overfit.implied_independent_trials(skill.drop(columns=[benchmark], errors="ignore"))
    m_total = max(configs_tried or 0, len(trials))
    n_hat = rho + (1 - rho) * m_total if rho == rho else float(m_total)
    sr0 = overfit.expected_max_sr(var_sr, n_hat)
    per["psr_0"] = [overfit.psr(r.sr, r.T, r.skew, r.kurt) for r in per.itertuples()]
    per["dsr"] = [overfit.dsr(r.sr, r.T, r.skew, r.kurt, var_sr, n_hat) if m != benchmark else float("nan")
                  for m, r in zip(per.index, per.itertuples())]
    per["min_trl_days_95"] = [overfit.min_track_record(r.sr, r.skew, r.kurt) for r in per.itertuples()]

    # DM vs benchmark per trial, with multiple-testing adjustments across trials
    days = pd.Series(losses.index, index=losses.index)
    dm = {m: diebold_mariano(losses[m], losses[benchmark], days)["p_a_better"] for m in trials.index}
    p = pd.Series(dm, dtype=float)
    if len(p):
        per.loc[p.index, "dm_p"] = p
        per.loc[p.index, "dm_p_holm"] = overfit.holm(p)
        per.loc[p.index, "dm_p_bhy"] = overfit.bhy(p)

    # Data-snooping over the whole search (all trials vs benchmark)
    d = skill.drop(columns=[benchmark], errors="ignore")
    spa = overfit.spa_test(d, B=bootstrap) if d.shape[1] else {}
    # PBO over all trials incl. the benchmark (selection among everything tried). Performance = skill vs the
    # benchmark, so "OOS loss" means the selected trial did worse than the benchmark out of sample. Rankings are
    # identical to ranking by -MAE (the benchmark's daily loss is subtracted from every trial alike).
    pbo = overfit.pbo_cscv(skill, S=S, stat="mean")

    return {
        "market": market, "component": component, "benchmark": benchmark, "loss": loss,
        "days": len(losses), "rows_aligned": aligned,
        "trials_with_series": int(len(trials)), "configs_tried": m_total,
        "implied_independent_N": n_hat, "avg_trial_corr": rho,
        "var_trial_sr": var_sr, "sr0_expected_max": sr0,
        "per_trial": per.reset_index(), "spa": spa, "pbo": pbo,
    }


def configs_tried() -> int:
    """Distinct configurations ever logged (any status): the M in the DSR's trial count."""
    with registry.connect(read_only=True) as con:
        return con.execute("SELECT count(DISTINCT config_hash) FROM runs").fetchone()[0]


def completed_runs(models: list[str] | None = None) -> dict[str, str]:
    """Latest completed run per model (model = one trial configuration)."""
    with registry.connect(read_only=True) as con:
        rows = con.execute("""SELECT model, arg_max(run_id, created_utc) FROM runs WHERE status = 'done'
                              GROUP BY model ORDER BY model""").fetchall()
    return {m: r for m, r in rows if models is None or m in models}
