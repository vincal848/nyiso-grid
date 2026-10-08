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
| Shrink the TCC pricer's gap toward the auction price | M9: realized-minus-price gap loads 0.4 on the pricer's claimed gap (t = 3.6), so the signal is real but noisy | M9 result (docs/experiments/tcc_pricer.md) | New declared milestone; weights fitted walk-forward | open |
| TCC regime features: gas spreads, outage schedule at the auction date | Potomac SOM: unexpected gas-spread and outage regimes drive TCC P&L; the pricer sees only last year's | M9: the market price beats every history-based pricer on squared error | Needs a gas-spread source (see above) and the P-14B archive | open |
| TCC pricing: risk (path payoff variance), sells of held TCCs, BOP vs centralized liquidity | M9 prices means only and buys only | M9 limits | Moderate; needs award-volume and bid-level (masked bid) data | open |
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
| QRA / LQRA, isotonic distributional regression, conformal ensemble (M4) | 98% intervals miss ~3% with clustered misses | Scoreboard (Christoffersen p ≈ 0); not run in M4's distributional step (budget used) | Mostly post-processing | open |
| EVT (GPD) tail splice above the 0.9 quantile | Heavy tails | M4 (2026-10-08): RT CRPS -0.17% (p = 0.13), spike hours +0.21%; q99 miss 1.46% -> 1.23%, q95 5.68% -> 5.92%: not adopted. Open: splice at a higher threshold with a covariate-dependent scale | Post-processing | tried |
| DART v2: size on conditional-mean forecasts + RT spike risk | DART prototype loses (holdout −$195k): v1's median-like RT forecast understates the RT mean by ~$4.5 (validation), biasing the spread to INC | M4: validation +$231k (Sharpe 0.92) vs v1 −$30k; top 1% of days = 80% of P&L; no out-of-sample test yet (docs/experiments/dart_v2.md) | Paper trading live since 2026-10-06 (`live_dart`, `lmp paper`); scored by `lmp dart-score` at 365 counted days (power 38% for a validation-sized effect); rule frozen. The job is disabled, so days only accrue once it is re-enabled | paper |
| DART pricer: scenario-priced virtuals with a bid curve, fees and risk limits | v2 sizes from a Gaussian approximation and clears every virtual; the M4 copula and a bid curve use the full joint distribution | DART pricer result (2026-10-08, ROADMAP, docs/experiments/dart_pricer.md): all three candidates lose after fees on validation (-$28k to -$38k vs v2 +$231k, no trade $0), direction has no skill (INC/DEC realized spread -0.03/+0.03), bid curve adds nothing; v2's own case rests on Winter Storm Elliott (+$55k without it, p 0.21). Open: spike-member mean in the scenarios, a mean-targeting signal, proxy buses | Forward window needs the daily job re-enabled; N = 365 days has 38% power for a v2-sized effect | tried (no edge yet)
| Joint DA/RT samples | DART P&L needs the spread's error correlation | M4 (2026-10-08): per-zone Gaussian copula beats independent draws on spread CRPS (-2.0%, p < 1e-9), empirical copula worse (+3.5%). Open: dependence across hours and zones (TCC), use in the DART rule | Sampler exists (`scenarios.py`); wiring it into DART is a new declared change | tried |
| Robust median combination (M4 `combo3_med_aci`) | Guard against one member blowing up (LEAR, Jan 2026) | DA CRPS +5% (median often picks persistence); RT flat; not adopted | A guard that only triggers out of range (see LEAR blow-up guard) | tried |
| LEAR blow-up guard in shock months | M7: LEAR's DA MAE 140 $/MWh in 2026-01 made signal v1's DA RMSE worse than persistence on the holdout | M7 result (docs/SIGNAL_V1.md) | Post-processing (shrink toward persistence when inputs leave the training range) or robust LEAR loss | open |
| LEAR v2 with corrected load / HRRR inputs | `lear_wx` tested on LEAR v1 only | — | One full run | open |
| DDNN with a hyperparameter search (Optuna on a pre-validation window) and a longer early-stopping window | M6 used a fixed architecture; networks stopped after ~30 epochs; the literature tunes ~1 day per market | M6: `combo4_eq_aci` −1.8% DA CRPS (Holm p = 0.31); DDNN alone +30% DA, failing in shock months | Tuning must use data before 2022-10 only (or nested in each fold): 1 declared milestone | open |
| Foundation models as live shadow members (Chronos-2, TabPFN-TS) | Pretraining overlaps 2022-10..2025-09, so only a live record is a clean test | Pan & Ezzat 2026: Chronos-2 + domain model average beats both (CAISO) | Daily inference job + model download; score on the live record only | open |
| NBEATSx ensemble | Literature gain over a DNN ensemble 2-5%, not significant on PJM | Not run (M6 declaration) | Large | open |
| DNN / NBEATSx ensemble, distributional DNN, TabPFN-TS / Chronos-2 member (M6) | Literature gains 3–8% rMAE over LEAR (European DA) | Literature | Large | tried (M6: DDNN-JSU, not adopted) |
| Monthly norm with recent-year weights or a level adjustment (M5 follow-up) | `m5_norm` weights 2015–2020 equally; missed winter 2025–26 by ~60% | M5 check: `m5_lastyear` 11.3 vs norm 22.2 total CRPS on 2025-10..2026-09 | Post-processing over stored M5 forecasts or one declared run | open |
| Gas forward curve for the heat-rate anchor (M5) | Spot gas at the cutoff is a poor forecast of gas months ahead | `m5_anchor` loses to the norm (13.6 vs 10.2) mostly after the 2022 gas spike | Free NYMEX series ended 2024-04; CME settlements / paid data | blocked (data) |
| EIA-923 / CEMS bid stack, masked offers (M5) | Structural anchor for supply shifts | Not attempted in M5 | Ingest EIA-923, CEMS and NYISO masked bids (3-month lag) | open |
| RT monthly averages, hourly shapes, nodes and TCC path values (M5 scope) | TCC valuation needs node-pair congestion over a month or a capability period | M5 covers zonal DA total and congestion only; TCC path values picked up as M9 (declared 2026-10-08, ROADMAP) | RT averages and hourly shapes stay open | tried (TCC paths: M9, no edge over persistence; RT averages and hourly shapes remain open) |
| Horizon extension (M5): bid-stack anchor, seasonal norms | Needed for TCC / monthly products | Roadmap | Large | tried (M5: seasonal norm adopted) |

## Infrastructure

| Idea | Why | Status |
|---|---|---|
| Retry LEAR when a loky worker dies on Windows (0x800703e5) | `lear_wx` failed once at worker start-up, re-run succeeded | done (2026-10-05): two retries with a fresh pool, then in-process (deterministic fits, same output) |
| Install ruff in the dev environment | Lint was not run on recent commits | done (2026-10-05: ruff in `dev`, CI lint step; rules E/F/W/I/B/UP; `ruff format` not adopted, it would rewrite aligned comments in 61 files) |
| Version the panel per run (snapshot or content hash per column) | `gbm_l1` could not be reproduced exactly for M7: panel changed after the validated runs (docs/SIGNAL_V1.md) | done (2026-10-05): runs store the exact panel once per content hash (`runs.panel_hash`, data/experiments/panel_snapshots, ~39 MB each), `lmp panel-diff`; live forecasts keep their day's panel rows. Runs before this date are not covered |
