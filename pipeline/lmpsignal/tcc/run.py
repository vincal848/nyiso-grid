"""TCC pricer runs (declared in docs/ROADMAP.md, "M9 declaration"): walk-forward over past auctions, one logged run per candidate.

Universe: awarded paths of every auction period posted after the first 365-day window fits inside the warehouse and
finished before the final holdout (2025-10-01; the holdout stays locked, so no payoff after 2025-09-30 is read).
Each forecast uses delivery days before posted date - 7 days only.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from lmpsignal import registry
from lmpsignal.config import BURN_IN_START, EXPERIMENTS_DIR, HOLDOUT_START, guard
from lmpsignal.structural import constraints as cs
from lmpsignal.tcc import data, pricer
from lmpsignal.tcc.pricer import Period

# candidate run name -> forecast column evaluated; the third is evaluated on illiquid nodal paths only
CANDIDATES = {"tcc_struct_trailing": "struct_trailing", "tcc_struct_seasonal": "struct_seasonal",
              "tcc_struct_blend_illiquid": "struct_blend"}
BASELINES = ("c", "persistence", "climatology")        # c = the clearing price itself (the market baseline)
FINAL_FROM = pd.Timestamp("2025-01-01")                # auctions posted on/after this: the pre-declared final test set
ILLIQUID_MONTHS = 24                                   # nodal path with no award in this many months before the auction


def _illiquid(paths: pd.DataFrame, nodes: set[int]) -> pd.Series:
    """Nodal path (an end is a generator node) that no earlier auction awarded in the previous 24 months."""
    posted = {k: np.sort(v.unique()) for k, v in paths.groupby(["poi", "pow"])["posted"]}
    lag = pd.DateOffset(months=ILLIQUID_MONTHS)

    def seen(r) -> bool:
        a = posted[(r["poi"], r["pow"])]
        before = a[a < r["posted"].to_datetime64()]
        return len(before) > 0 and before[-1] >= (r["posted"] - lag).to_datetime64()

    nodal = paths["poi"].isin(nodes) | paths["pow"].isin(nodes)
    return nodal & ~paths.apply(seen, axis=1)


def build_obs(forecast: str, first_n: int | None = None) -> pd.DataFrame:
    """One row per (auction period, path): clearing price c, realized payoff y, the baselines and `forecast`."""
    paths = data.auction_paths()
    _, nodes = data.poi_ptids()
    paths["illiquid"] = _illiquid(paths, nodes)
    last_day = pd.Timestamp(HOLDOUT_START) - timedelta(days=1)
    guard(last_day.date())
    first_cutoff = pd.Timestamp(BURN_IN_START) + timedelta(days=pricer.WINDOW_DAYS)
    paths["cutoff"] = paths["posted"].dt.normalize() - timedelta(days=pricer.CUTOFF_LAG_DAYS)
    sel = paths[(paths["cutoff"] >= first_cutoff) & (paths["end"] <= last_day)].copy()
    cong, grid = data.poi_congestion(str(BURN_IN_START), str(HOLDOUT_START))
    sp = cs.shadow_prices(str(BURN_IN_START), str(HOLDOUT_START))
    sp = sp[sp["market"] == "da"]
    out = []
    keys = sel.sort_values(["posted", "round_id", "period_id"])[["round_id", "period_id"]].drop_duplicates()
    for n, (rid, pid) in enumerate(keys.itertuples(index=False)):
        if first_n is not None and n >= first_n:
            break
        g = sel[(sel["round_id"] == rid) & (sel["period_id"] == pid)].reset_index(drop=True)
        p = Period(g["posted"].iloc[0], g["start"].iloc[0], g["end"].iloc[0])
        poi, pow_ = g["poi"].to_numpy(np.int64), g["pow"].to_numpy(np.int64)
        g["auction"] = n
        g["y"] = pricer.realized(cong, grid, p, poi, pow_)
        g["climatology"] = pricer.climatology(cong, grid, p, poi, pow_)
        g["persistence"] = pricer.persistence(cong, grid, p, poi, pow_)
        g[forecast] = pricer.structural(sp, cong, grid, p, poi, pow_)[forecast].to_numpy()
        out.append(g)
    obs = pd.concat(out, ignore_index=True)
    obs["path"] = obs["poi"].astype(str) + ">" + obs["pow"].astype(str)
    obs["final"] = obs["posted"] >= FINAL_FROM
    return obs


def run(candidate: str, log: bool = True, first_n: int | None = None) -> str | None:
    """One candidate pass over all auctions; the observation table is stored with the run."""
    forecast = CANDIDATES[candidate]
    config = {"model": "TCC pricer (structural shift factors x constraint shadow prices)", "forecast": forecast,
              "window_days": pricer.WINDOW_DAYS, "top_k": pricer.K, "ridge": pricer.RIDGE,
              "cutoff_lag_days": pricer.CUTOFF_LAG_DAYS, "final_from": str(FINAL_FROM.date()),
              "evaluated_on": "illiquid nodal paths" if candidate.endswith("illiquid") else "all awarded paths"}
    run_id = registry.start_run(candidate, config, 0) if log else None
    try:
        obs = build_obs(forecast, first_n)
        if log:
            obs.to_parquet(EXPERIMENTS_DIR / run_id / "obs.parquet", index=False)
            registry.finish_run(run_id)
    except Exception as e:
        if log:
            registry.finish_run(run_id, "failed", error=f"{type(e).__name__}: {e}"[:2000])
        raise
    print(f"{candidate}: {len(obs)} path-periods, {obs['auction'].nunique()} auction periods, "
          f"{obs['y'].notna().sum()} with realized payoff, {obs[forecast].notna().sum()} with a forecast", flush=True)
    return run_id
