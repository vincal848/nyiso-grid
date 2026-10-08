# Signal v1 (frozen 2026-10-05)

Selected under the training protocol in `docs/ROADMAP.md`. Validation: 36 monthly rolling-origin folds,
2022-10..2025-09, 7-day embargo. The holdout (2025-10..2026-09) is evaluated once with `lmp m7` (results below).

## What it is

`combo3_eq_aci`: the equal-weight average of two models' point forecasts, clipped to the historical price range,
with adaptive conformal intervals.

| Layer | Run (validation) | Configuration |
|---|---|---|
| LEAR (LASSO autoregression, Lago et al. 2021) | `lear-20260928T030707-d13937` | windows 364 / 728 / all days, LassoLarsIC(aic), asinh VST, monthly refit; inputs: DA lags D−1,2,3,7 ×24, RT lags D−2,3 ×24, ISOLF zone + NYISO load ×24, GFS temperature ×24, gas, day of week, holiday. Rebuilt for M7 as `LEAR(clip=False)` |
| `lear_clip` | `lear_clip-20260928T042346-fc5edf` | clip to history, out-of-sample residual quantiles |
| LightGBM-L1 | `gbm_l1-20260928T024002-cb6de8` | 500 trees, L1 objective, 728-day window, panel feature set `v1` (36 features) + zone |
| `combo3_eq_aci` | `combo3_eq_aci-20260928T145307-9a2801` | combine (equal weights) → clip → ACI calibration |

Forecast: hourly DA and RT prices (total, energy, loss, congestion) for delivery day D, 15 zones, issued 05:00 ET
on D−1, 21 quantiles.

## Why this one (selection rule applied 2026-10-05)

| Candidate | Total CRPS DA | RT | Pooled | DM (Holm) vs `persist_da_d1` DA / RT | Gates |
|---|---|---|---|---|---|
| **combo3_eq_aci** | 4.432 | 10.754 | **7.593** | 0.000 / 0.000 | pass |
| combo3wx_eq_aci (HRRR + corrected load members) | 4.475 | 10.736 | 7.606 | 0.000 / 0.000 | pass |
| combo2_eq_aci | 4.837 | 10.891 | 7.864 | 0.000 / 0.001 | pass |
| lear_clip_aci | 4.682 | 11.228 | 7.955 | 0.000 / 0.030 | pass |
| assemble_v1_final (declared assembly) | 5.273 | 11.329 | 8.301 | 0.000 / 0.085 | fail |
| persist_da_d1 (benchmark) | 6.512 | 12.161 | 9.337 | | |

PBO vs `persist_da_d1`: 0.000 (DA), 0.003 (RT). `combo3wx_eq_aci` is within 1% of the winner; the simpler
candidate (no HRRR / load-model dependency) wins under the rule. Full table: `docs/experiments/scoreboard.md`.

## Reproducibility notes

- The validation runs predate the repository's first commit (2026-09-28 15:25 ET): they are identified by config
  hash and code fingerprint, not a git commit. The M7 runs record the commit.
- LEAR: `LEAR(clip=False)` on today's code and data reproduces the stored validation predictions exactly
  (fold 2022-10, max abs difference 0).
- LightGBM: identical configuration and library versions, and deterministic run to run, but today's panel gives
  predictions that differ from the stored run by ~0.9 $/MWh mean absolute (~2% of price) from the first fold on.
  The panel's data fingerprint changed between the runs (the validated runs used a panel built before a
  re-ingest of `weather_fcst` on 2026-09-27 21:13 and before later rebuilds); the old panel no longer exists, so
  the exact column cannot be identified. M7 runs the frozen configuration on the data as it exists, with
  calibration history taken from the stored validation runs. Fix logged in `docs/RESEARCH_LOG.md`: version the
  panel per run.

## Holdout (M7, run once on 2026-10-05)

`LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7 uv run lmp m7 combo3_eq_aci` at commit `b1b1c8e`: base models refit monthly over
2025-10..2026-09 with the validation rule; the frozen chain continued over validation + holdout. Runs:
`lear_m7-20261005T045943-b0d998`, `lear_clip_m7-20261005T051922-13256f`, `gbm_l1_m7-20261005T052010-ccdb0a`,
`combo3_eq_aci_m7-20261005T053459-548f60`; benchmarks `persist_da_d1_m7-20261005T053547-581643`,
`lago_naive_m7-20261005T053653-e7c74b`. Lineage: `data/experiments/m7_lineage.json`. (A first attempt stopped in
fold 2026-01 on a scoring bug, before any result was produced: NORTH had zero RT congestion all month; fixed in
`b1b1c8e`.)

Total price ($/MWh):

| | DA CRPS | DA RMSE | DA MAE | RT CRPS | RT RMSE | RT MAE | 90% / 98% coverage DA, RT |
|---|---|---|---|---|---|---|---|
| **Signal v1, holdout** | **9.75** | 42.54 | **11.43** | **14.55** | **50.97** | **17.89** | 0.89 / 0.97, 0.91 / 0.98 |
| persist_da_d1, holdout | 11.54 | **34.42** | 13.94 | 19.56 | 64.86 | 23.84 | 0.90 / 0.96, 0.89 / 0.96 |
| lago_naive, holdout | 16.45 | 47.21 | 19.30 | 23.37 | 70.93 | 28.23 | |
| Signal v1, validation | 4.43 | 11.89 | 5.59 | 10.75 | 50.20 | 13.07 | 0.90 / 0.97, 0.90 / 0.97 |

Diebold–Mariano vs `persist_da_d1` on the holdout (one-sided p, 365 days): total CRPS DA 0.088, RT 0.017; total
squared error DA 0.759, RT 0.096. Congestion CRPS: DA 2.36 vs 2.54, RT 3.75 vs 4.17 (`zero_congestion` still has the
lowest congestion MAE).

Monthly total CRPS, signal v1 / persist_da_d1:

| | 25-10 | 25-11 | 25-12 | 26-01 | 26-02 | 26-03 | 26-04 | 26-05 | 26-06 | 26-07 | 26-08 | 26-09 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DA | 3.2 / 4.1 | 3.1 / 5.0 | 8.7 / 15.7 | **53.7 / 47.1** | 11.4 / 16.7 | 4.6 / 7.0 | 3.7 / 5.2 | 3.3 / 5.5 | 2.9 / 5.1 | 10.2 / 17.5 | **8.8 / 5.0** | 2.8 / 4.2 |
| RT | 7.2 / 8.1 | 8.9 / 9.8 | 17.0 / 22.0 | 43.5 / 76.7 | 18.3 / 24.0 | 11.9 / 13.0 | 8.3 / 9.0 | 9.1 / 10.6 | 10.9 / 12.7 | 20.6 / 27.8 | 11.7 / 12.4 | 6.8 / 7.9 |

**Reading.** The holdout year was far more volatile than validation (total CRPS roughly doubled). On the primary
metric the signal generalizes: CRPS 16% (DA) and 26% (RT) below yesterday's DA price, better in every RT month and
10 of 12 DA months, significant in RT. Intervals are well calibrated, including the 98% level that missed in
validation. The weakness is the DA point forecast in shock months: DA RMSE is worse than persistence, driven by
January 2026 (LEAR's DA MAE 140 $/MWh that month) and August 2026. Follow-ups are in `docs/RESEARCH_LOG.md`
(tail handling, LEAR blow-up guard), to be picked up after the end-to-end build with a declared run budget.

## Node layer (`lmp nodes`, scored once on validation 2026-10-05)

Node forecast = signal energy + per-node OLS mapping of the zone's loss and congestion (365 days to month start − 7d).
36 validation folds, ~16M node-hours per market (`data/experiments/nodes_v1_validation.csv`):

| | DA MAE | DA RMSE | RT MAE | RT RMSE |
|---|---|---|---|---|
| node mapping | **7.00** | **17.16** | 14.80 | 60.65 |
| zone forecast used at every node | 7.02 | 17.44 | **14.76** | 60.98 |
| node's own DA price of D−1 | 8.70 | 20.11 | 16.36 | **59.75** |

The mapping beats node persistence on MAE but adds little over the zone forecast: within-zone congestion that moves
nodes differently is not captured from a zone-level congestion forecast. Route: structural node shift factors
(`docs/RESEARCH_LOG.md`).
