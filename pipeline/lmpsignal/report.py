"""Human-readable outputs: validation scoreboard and feature documentation (docs/)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from nyiso.config import ROOT
from lmpsignal import registry, runner
from lmpsignal.config import (BURN_IN_START, EMBARGO_DAYS, HOLDOUT_END, HOLDOUT_START, ISSUE_HOUR_ET, QUANTILES,
                              VALIDATION_END, VALIDATION_START)
from lmpsignal.evaluate import diebold_mariano
from lmpsignal.panel import FEATURES, KEYS, MASKS, TARGETS

DOCS = ROOT / "docs"


def _md(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(floatfmt.format(v) if isinstance(v, float) else f"{v:,}" if isinstance(v, int) else str(v)
                                     for v in r) + " |")
    return "\n".join(out)


def _runs(models: list[str] | None) -> dict[str, str]:
    with registry.connect(read_only=True) as con:
        rows = con.execute("""SELECT model, arg_max(run_id, created_utc) FROM runs WHERE status = 'done'
                              GROUP BY model ORDER BY model""").fetchall()
    return {m: r for m, r in rows if models is None or m in models}


def write_scoreboard(models: list[str] | None = None) -> Path:
    runs = _runs(models)
    summ = runner.summary(list(runs.values()))
    keep = ["model", "market", "component", "n", "mae", "rmae", "rmse", "smape", "normal_mae", "tail_mae", "crps",
            "cov50", "cov90", "cov98"]
    summ = summ[[c for c in keep if c in summ]].sort_values(["market", "component", "crps", "rmse"], na_position="last")
    summ["n"] = summ["n"].astype(int)

    # DM tests vs the bar (yesterday's DA price), on the primary losses (CRPS, squared error) and on |error|
    from lmpsignal import diagnostics

    dm_rows = []
    bar = "persist_da_d1"
    if bar in runs:
        for comp in ("total", "congestion"):
            for mkt in ("da", "rt"):
                for loss in ("crps", "se", "ae"):
                    L, _ = diagnostics.daily_losses(runs, mkt, comp, loss)
                    if bar not in L:
                        continue
                    for model in L.columns:
                        if model == bar:
                            continue
                        dm = diebold_mariano(L[model], L[bar], pd.Series(L.index, index=L.index))
                        dm_rows.append({"component": comp, "market": mkt, "loss": loss, "model": model,
                                        "p_better_than_bar": dm["p_a_better"], "mean_loss_diff": dm["mean_diff"],
                                        "days": dm["n_days"]})
    dm_table = pd.DataFrame(dm_rows)
    if len(dm_table):
        dm_table = (dm_table.pivot_table(index=["component", "market", "model"], columns="loss",
                                         values="p_better_than_bar").reset_index()
                    .rename(columns={"crps": "p_crps", "se": "p_se", "ae": "p_ae"}))
        dm_table = dm_table[[c for c in ["component", "market", "model", "p_crps", "p_se", "p_ae"] if c in dm_table]]
        dm_table = dm_table.sort_values(["component", "market", "p_crps"])

    # per-fold win rate vs reference (total price)
    with registry.connect(read_only=True) as con:
        ids = ",".join(f"'{r}'" for r in runs.values())
        wins = con.execute(f"""
            SELECT r.model, s.market, count(*) AS folds,
                   avg((s.value < 1)::INT) AS frac_folds_beat_ref, median(s.value) AS median_fold_rmae
            FROM scores s JOIN runs r USING (run_id)
            WHERE s.run_id IN ({ids}) AND s.metric = 'rmae' AND s.component = 'total' AND s.zone = 'ALL'
            GROUP BY ALL ORDER BY s.market, median_fold_rmae""").df() if ids else pd.DataFrame()

    lines = [
        "# Validation scoreboard (anchor horizon h0)", "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M} by `lmp report`._", "",
        f"- Forecast: hourly DA and RT prices for delivery day D, issued {ISSUE_HOUR_ET:02d}:00 ET on D−1; "
        "15 NYISO zones (11 internal + 4 external proxies).",
        f"- Validation: {VALIDATION_START} → {VALIDATION_END} (exclusive), monthly rolling-origin folds, expanding "
        f"window from {BURN_IN_START}, {EMBARGO_DAYS}-day embargo. Holdout {HOLDOUT_START} → {HOLDOUT_END} untouched.",
        f"- **Primary metrics: CRPS (whole distribution) and RMSE (conditional mean).** MAE is secondary: it rewards "
        "the median, and for zero-inflated targets such as congestion an always-zero forecast can win on MAE while "
        "being useless for trading. Tables are sorted by CRPS.",
        f"- rMAE = MAE / MAE of `{runner.REFERENCE}` on the same rows. CRPS from {len(QUANTILES)} stored quantiles "
        "(models whose quantiles come from their own out-of-sample errors have none in the first fold, so their CRPS "
        "covers folds 2..36). RT hours flagged in `rt_flag` are not scored.",
        "- Components are additive: total = energy + loss + congestion (congestion = −MCC).", "",
        "## Pooled validation metrics", "", _md(summ), "",
    ]
    if len(dm_table):
        lines += ["## Diebold–Mariano vs yesterday's DA price (daily-averaged loss, HAC)", "",
                  "One-sided p-values for H1: the model's loss is lower than `persist_da_d1`'s, for CRPS, squared error "
                  "(se) and absolute error (ae). Smaller = stronger evidence. Reported, not thresholded. Days where any "
                  "compared model lacks quantiles are dropped from the CRPS test.", "",
                  _md(dm_table), ""]
    if len(wins):
        lines += ["## Fold stability (total price)", "", _md(wins), ""]
    lines += _coverage_section(runs)
    lines += _overfit_section(runs)
    lines += _runs_section(runs)
    out = DOCS / "experiments" / "scoreboard.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def write_feature_docs() -> Path:
    lines = ["# LMP signal: panel features", "",
             "_Generated by `lmp docs` from `pipeline/lmpsignal/panel.py`. Every feature is built as-of the issue time; "
             "`lmp panel` verifies it through the `_avail_*` audit columns._", "",
             f"Issue time: {ISSUE_HOUR_ET:02d}:00 ET on D−1 for delivery day D (anchor horizon h0).", "",
             "## Keys", "", ", ".join(f"`{k}`" for k in KEYS), "",
             "## Targets", "",
             "`{market}_{component}` for market ∈ {da, rt}, component ∈ {total, energy, loss, congestion}. "
             "energy = LBMP − MLC + MCC (identical across zones), loss = MLC, congestion = −MCC; they sum to total.", "",
             ", ".join(f"`{t}`" for t in TARGETS), "",
             "## Scoring masks", "",
             "- `score_da`: DA price present.",
             "- `score_rt`: RT price present and not flagged (`lbmp_zone_hourly.rt_flag`).", "",
             "## Features", "", "| Feature | Description | Available from |", "|---|---|---|"]
    lines += [f"| `{k}` | {d} | {a} |" for k, (d, a) in FEATURES.items()]
    lines += ["", "## Model-specific inputs", "",
              "- **LEAR** (`models/lear.py`) builds a daily design from panel columns: all 24 hours of the target's own "
              "DA component at D−1, D−2, D−3, D−7 and RT component at D−2, D−3; 24-hour zone load forecast (internal "
              "zones only), NYISO load forecast and temperature forecast for D; Henry Hub; day-of-week dummies; NERC "
              "holiday. DST days are mapped to 24 slots (fall-back hour averaged, spring-forward hour interpolated). "
              "Only lags already published at 05:00 on D−1 are used (tested in `test_m2.py`).",
              "- **LightGBM** (`models/gbm.py`) uses every panel feature above plus the zone as a categorical input.",
              "- **Quantiles** for LEAR and LightGBM come from each run's own out-of-sample errors in earlier validation "
              "folds (ending before the current fold's embargo), per zone and hour; the first fold has no quantiles.", "",
              "## Availability audit columns", "",
              "`_avail_*` columns hold the latest publication time of any source row a feature block used. "
              "`lmp panel` fails if any of them is later than `issue_utc`.", ""]
    out = DOCS / "FEATURES.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


_ = MASKS


# ------------------------------------------------------------------------------------ overfitting diagnostics

BENCHMARKS = ("lago_naive", "persist_da_d1")


def _overfit_section(runs: dict[str, str]) -> list[str]:
    from lmpsignal import diagnostics

    tried = diagnostics.configs_tried()
    out = ["## Backtest-overfitting and multiple-testing diagnostics", "",
           "Applied to daily forecast *skill*: benchmark daily CRPS − model daily CRPS ($/MWh, total price, "
           "averaged over the day's scored hours and zones). SR = non-annualized Sharpe ratio of that daily skill. "
           "Trials = every configuration in the registry. All values are descriptive; none is used to accept or "
           "reject a model.", "",
           "- **PSR(0)**: probability the true skill SR > 0 given sample length, skew and kurtosis (Bailey & López de "
           "Prado 2012).",
           "- **DSR**: PSR against SR0, the expected maximum SR from the implied number of independent trials "
           "(Bailey & López de Prado 2014).",
           "- **MinTRL**: days of track record needed for PSR(0) to reach 95% at the observed SR, skew and kurtosis.",
           "- **DM p (Holm / BHY)**: Diebold–Mariano p-values adjusted for testing every trial (Harvey, Liu & Zhu 2016).",
           "- **SPA / Reality Check**: p-value for H0 'no trial beats the benchmark', accounting for the search over "
           "all trials (Hansen 2005; White 2000; stationary bootstrap, mean block 10 days).",
           "- **PBO**: probability that the configuration with the best in-sample mean skill ranks below the median "
           "out-of-sample, from CSCV with S=16 blocks (Bailey, Borwein, López de Prado & Zhu 2017). With few trials "
           "PBO is coarse and varies a lot between samples.", "",
           "Reading notes:", "",
           "- DSR assumes the trials are variants from one search (e.g. hyper-parameter settings of one model). "
           "Mixing deliberately different benchmarks inflates Var[SR] and hence SR0, which makes DSR conservative.",
           "- CSCV's in-sample and out-of-sample halves are complements, so when the same trial is selected in every "
           "combination its IS and OOS means sum to twice its full-sample mean and the degradation slope is exactly "
           "−1 by construction. The slope is informative only when the selected trial changes across combinations.",
           "- Skill series are heavy-tailed (price spikes), so PSR/DSR/MinTRL rely heavily on the kurtosis estimate.", ""]
    for bench in BENCHMARKS:
        if bench not in runs:
            continue
        for market in ("da", "rt"):
            r = diagnostics.run_diagnostics(runs, bench, market, configs_tried=tried, loss="crps")
            per = r["per_trial"][["model", "T", "mean", "std", "sr", "skew", "kurt", "psr_0", "dsr", "min_trl_days_95"]
                                 + [c for c in ("dm_p", "dm_p_holm", "dm_p_bhy") if c in r["per_trial"]]]
            per = per.rename(columns={"mean": "mean_skill", "std": "sd_skill"})
            out += [f"### {market.upper()} vs `{bench}`", "",
                    f"Days: {r['days']} (rows aligned across trials: {r['rows_aligned']}). Configurations tried: "
                    f"{r['configs_tried']}; avg correlation of trial skill series: {r['avg_trial_corr']:.3f}; implied "
                    f"independent trials N̂ = {r['implied_independent_N']:.2f}; Var[SR] across trials = "
                    f"{r['var_trial_sr']:.5f}; SR0 (expected max SR under no skill) = {r['sr0_expected_max']:.4f}.", "",
                    _md(per), ""]
            if r["spa"]:
                sp = r["spa"]
                out += [f"SPA p-values (lower / consistent / upper): {sp['p_spa_lower']:.3f} / "
                        f"{sp['p_spa_consistent']:.3f} / {sp['p_spa_upper']:.3f}; Reality Check p: "
                        f"{sp['p_reality_check']:.3f} ({sp['models']} trials, {sp['bootstrap']} bootstrap draws).", ""]
            pb = r["pbo"]
            if pb.get("pbo") == pb.get("pbo"):
                out += [f"PBO = {pb['pbo']:.3f} over {pb['n_trials']} trials ({pb['combinations']:,} CSCV combinations, "
                        f"{pb['days_used']} days); median logit {pb['logit_median']:.2f}; performance degradation "
                        f"slope {pb['degradation_slope']:.2f}; P(selected trial's OOS mean skill < 0) = "
                        f"{pb['prob_oos_loss']:.3f}; share of quantiles where selected-OOS ≥ all-OOS = "
                        f"{pb['fsd_share_quantiles_selected_ge_all']:.2f}.", ""]
    return out


def _runs_section(runs: dict[str, str]) -> list[str]:
    with registry.connect(read_only=True) as con:
        ids = ",".join(f"'{r}'" for r in runs.values()) or "''"
        df = con.execute(f"""SELECT model, run_id, config_hash, code_fingerprint, git_commit, data_fingerprint,
                                    round(duration_s) AS duration_s
                             FROM runs WHERE run_id IN ({ids}) ORDER BY model""").df()
        tried = con.execute("SELECT status, count(*) AS runs, count(DISTINCT config_hash) AS configs FROM runs GROUP BY 1").df()
    out = ["## Runs and reproducibility", "", _md(df.astype(object).where(df.notna(), "—")), ""]
    for col, what in (("code_fingerprint", "code"), ("data_fingerprint", "panel data")):
        vals = df[col].dropna().unique()
        if len(vals) > 1:
            out += [f"> Note: the compared runs used {len(vals)} different {what} versions ({col}).", ""]
    out += ["All logged runs (every trial counts toward the DSR):", "", _md(tried), ""]
    return out


def _coverage_section(runs: dict[str, str]) -> list[str]:
    import duckdb

    from lmpsignal.config import EXPERIMENTS_DIR
    from lmpsignal.evaluate import QCOLS, coverage_tests

    rows = []
    for model, rid in runs.items():
        for mkt in ("da", "rt"):
            d = duckdb.sql(f"""SELECT ts_utc, zone, hour_local, y, {', '.join(QCOLS)}
                               FROM read_parquet('{(EXPERIMENTS_DIR / rid).as_posix()}/*.parquet')
                               WHERE scored AND y IS NOT NULL AND market = '{mkt}' AND component = 'total'""").df()
            if d[QCOLS].notna().all(axis=1).any():
                rows.append({"model": model, "market": mkt, **coverage_tests(d)})
    if not rows:
        return []
    return ["## Interval calibration tests (total price)", "",
            "miss90 / miss98: share of outcomes outside the 90% / 98% intervals (nominal 0.10 / 0.02). Kupiec p: "
            "H0 miss rate = nominal (pooled misses are dependent across zones and hours, so p is optimistic). "
            "Christoffersen p: median over zone × hour day-sequences of the independence test (H0: misses do not "
            "cluster in time). Descriptive only.", "", _md(pd.DataFrame(rows)), ""]


ARTIFACTS = {
    "constraint_catalog": "Top-K constraints of the fold's training window: rank, key, sum |shadow|, bind rate, window.",
    "zone_shift_factors": "Zone x constraint sensitivity of zonal congestion (-MCC) to each constraint's shadow price.",
    "node_shift_factors": "Generator-node x constraint sensitivity (ridge on nodal -MCC); the node-constraint graph.",
    "node_fit": "In-window R² of each node's congestion explained by the top-K constraints.",
    "blend_weights": "Per-zone weights combining the structural forecast with persistence (and the intercept).",
    "constraint_forecasts": "Per constraint and delivery hour: P(bind), shadow price if binding, forecast, actual.",
}


def write_structure_docs() -> Path:
    from lmpsignal import graphs

    lines = ["# LMP signal: stored model internals and structure graphs", "",
             "_Generated by `lmp docs`._ Nothing a model computes is discarded: predictions (point + 21 quantiles) "
             "live in `data/experiments/<run>/fold=*.parquet`, model internals in "
             "`data/experiments/<run>/artifacts/<name>/fold=*.parquet`, and `lmp graphs` compiles the structural "
             "model's artifacts into `data/structure.duckdb` (shown in the dashboard's Signal tab).", "",
             "## Artifacts written by the structural congestion model (per fold)", "",
             "| Artifact | Contents |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in ARTIFACTS.items()]
    lines += ["", "## data/structure.duckdb", "", "```", graphs.__doc__.strip(), "```", ""]
    out = DOCS / "STRUCTURE.md"
    out.write_text(chr(10).join(lines), encoding="utf-8")
    return out
