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

## Holdout (M7)

_Pending: `LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7 uv run lmp m7 combo3_eq_aci`._
