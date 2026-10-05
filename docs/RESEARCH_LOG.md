# Research log: ideas parked for after the end-to-end build

Signal v1 is frozen under the training protocol in `docs/ROADMAP.md`. Ideas that came up and were *not* pursued
go here instead of into another retrain. Each entry: what, why we think it might help, the evidence so far, and
what it would cost. When an idea is picked up, it gets a milestone with a declared run budget (see the protocol)
and its outcome is recorded here, positive or negative.

Status: `open` (not started), `tried` (result recorded), `blocked` (needs data or a decision).

## Congestion

| Idea | Why | Evidence so far | Cost / blocker | Status |
|---|---|---|---|---|
| Regional gas spreads (Transco Z6 NY, Iroquois, Algonquin vs Dominion South) | NYISO MMU: gas spreads drove most of 2025's $638M DA congestion | Literature/MMU only | Paid data (NGI/Platts/ICE), or free proxy: PJM / ISO-NE DA prices vs NYISO | blocked (data decision) |
| Forward outage schedule (P-14B) | Outages starting on day D are invisible in the D−1 DAM list | M3: D−1 list gave ~1% binding gain, no congestion gain; worse at outage onsets | P-14B has no archive: start a daily archiver now, test in ~12 months | open (archiver first) |
| Interface utilization features (flow / limit, DA vs RT limit changes) | Physically closest driver of binding | Not tried; `interface_flows_hourly` exists | Feature work in the structural model | open |
| Constraint rename mapping | Constraint keys change names over time; catalog treats them as new | Known gap in `structural/constraints.py` | Manual/heuristic mapping | open |
| Joint simulation of co-binding constraints for quantiles | Constraints co-bind; independent hurdles mis-state tails | Research note (congestion_nodal.md) | Moderate | open |
| Congestion regime probabilities as features | Markov chain over patterns fails (4,655 sets / 8,760 h); probabilities may not | Research note | Moderate | open |
| Outage-to-constraint mapping v2: equipment aliases, onset-specific features | Name matching misses alias stations (STONYRDG vs STONYRGE) | M3 result: `struct_cong_out` not adopted | Small, but low expected value until P-14B exists | tried (2026-10-02, no gain) |

## Weather and load

| Idea | Why | Evidence so far | Cost / blocker | Status |
|---|---|---|---|---|
| WeatherNext 2 (DeepMind, 64-member ensemble, archive from 2022) | Frontier AI ensemble; covers most validation folds | Not tried | Access by request; check commercial terms of the historic archive | blocked (terms) |
| ECMWF AIFS / IFS | Best-in-class medium range | AIFS archive only from 2025 (open), IFS archive paid | Start daily archiving of AIFS now for live use | open |
| Ensemble spread as an uncertainty feature for intervals | Model disagreement should widen intervals | Not tried | Needs ≥ 2 archived sources | open |
| Weather regions from shift factors (corridors, not zones) | A node's price follows constraint regions, not local weather | Design discussion 2026-10-02 | Moderate | open |
| Thunderstorm-alert proxy (CAPE × reflectivity × lightning by corridor) | MMU: 50 of 1,377 alert hours carried 99% of thunderstorm congestion cost | HRRR fields ingested (`weather_hrrr`), not yet modeled | Part of M3b | open |
| Shortwave radiation / BTM solar from HRRR GRIB (DSWRF) | Zarr archive stores DSWRF for some runs only | Gap found in HRRR ingest | Byte-range GRIB2 download of one field | open |
| ISOLF vs P-58B level bias (up to 13%, seasonal) | Understanding it may give a cleaner load target | Found in loadfix work | Read NYISO load definitions (P-58B vs ISOLF) | open |
| Summer peak-hour load error | Weakest area of `loadfix_gbm` (peak RMSE 613 vs 553 MW for D−1) | loadfix results | Peak-specific features or quantile load model | open |
| HRRR missing runs fallback (00z / 12z D−2) | 6 days missing in 2021–2026 | HRRR backfill | Small | open |
| GBM first-summer artifact with new features | `gbm_l1_v3` 2023-06 much worse: load_fix never seen in summer in training | Fold log 2026-10-05 | Start features earlier or impute | open |

## Models and calibration

| Idea | Why | Evidence so far | Cost / blocker | Status |
|---|---|---|---|---|
| RT spike track (M3b): sparse logistic P(spike) + GPD magnitude, mixed into v1 | Models lose to persistence in top-5% RT hours | Spike-hour RT CRPS −12% (significant), pooled −2% (p = 0.12): not adopted (ROADMAP M3b result). Open follow-ups: ORDC-aware magnitude, threshold that adapts to price level (2025 winter base rates 41–71%), p_spike used in DART v2 (M4) | Next attempt needs a new declared milestone | tried |
| QRA / LQRA, isotonic distributional regression, conformal ensemble (M4) | 98% intervals miss ~3% with clustered misses | Scoreboard (Christoffersen p ≈ 0) | Mostly post-processing | open |
| EVT (GPD) tail splice above the 0.9 quantile | Heavy tails | Literature | Post-processing | open |
| DART v2: size on conditional-mean forecasts + RT spike risk | DART prototype loses (holdout −$195k): v1's median-like RT forecast understates the RT mean by ~$4.5 (validation), biasing the spread to INC | M4: validation +$231k (Sharpe 0.92) vs v1 −$30k; top 1% of days = 80% of P&L; no out-of-sample test yet (docs/experiments/dart_v2.md) | Paper-trade on `live_forecasts` (needs spike member live) before any capital; rule stays frozen | tried |
| Joint DA/RT samples | DART P&L needs the spread's error correlation | Roadmap M4 | Moderate | open |
| Robust median combination (M4 `combo3_med_aci`) | Guard against one member blowing up (LEAR, Jan 2026) | DA CRPS +5% (median often picks persistence); RT flat; not adopted | A guard that only triggers out of range (see LEAR blow-up guard) | tried |
| LEAR blow-up guard in shock months | M7: LEAR's DA MAE 140 $/MWh in 2026-01 made signal v1's DA RMSE worse than persistence on the holdout | M7 result (docs/SIGNAL_V1.md) | Post-processing (shrink toward persistence when inputs leave the training range) or robust LEAR loss | open |
| LEAR v2 with corrected load / HRRR inputs | `lear_wx` tested on LEAR v1 only | — | One full run | open |
| DNN / NBEATSx ensemble, distributional DNN, TabPFN-TS / Chronos-2 member (M6) | Literature gains 3–8% rMAE over LEAR (European DA) | Literature | Large | open |
| Horizon extension (M5): bid-stack anchor, seasonal norms | Needed for TCC / monthly products | Roadmap | Large | open |

## Infrastructure

| Idea | Why | Status |
|---|---|---|
| Retry LEAR when a loky worker dies on Windows (0x800703e5) | `lear_wx` failed once at worker start-up, re-run succeeded | open |
| Install ruff in the dev environment | Lint was not run on recent commits | open |
| Version the panel per run (snapshot or content hash per column) | `gbm_l1` could not be reproduced exactly for M7: panel changed after the validated runs (docs/SIGNAL_V1.md) | open |
