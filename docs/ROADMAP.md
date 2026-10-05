# LMP signal roadmap (phase 2)

_Revised 2026-09-28 after the M2 results and the literature/industry review
(`docs/research/lmp_forecasting_model_landscape.md`, with source notes in `docs/research/notes/`). DART and TCC pricing come after this
phase; this phase builds the probabilistic LMP signal._

## Done
- **M0**: data audit. Issue time 05:00 ET on D−1; ISOLF of D−2 only; weather/gas/outage/reserve-price ingest.
- **M1**: point-in-time panel, 36-fold rolling-origin CV with a locked holdout, metrics, registry,
  overfitting diagnostics (PSR/DSR/MinTRL/SPA/PBO), naive baselines.
- **M2 (first pass)**: LEAR and LightGBM. DA total MAE: LEAR 6.30 vs 7.97 for yesterday's DA (−21%).
  RT: LightGBM-L1 −8%. Neither beats persistence on congestion or in the top-5% RT spike hours.
  90%/98% intervals cover 88% and 95–96%.
- **M2.5**: post-processing layer (`lmp post`: clip / combine / ACI over stored predictions), LEAR v2
  (shared Gram matrix, time-ordered penalty, 56-day window, per-window outputs), cross-family combination,
  adaptive conformal intervals, spike/normal splits and Kupiec/Christoffersen tests. Best:
  `combo3_eq_aci` (clipped LEAR + LightGBM-L1, equal weights, ACI): DA total CRPS 4.43 vs 6.51 for
  yesterday's DA (beats it in 35 of 36 folds); RT total CRPS 10.75 vs 11.22, but the RT squared-error gain
  is not significant (DM p = 0.18). 90% intervals now cover 90%; 98% intervals miss ~3% with clustered
  misses (Christoffersen p ≈ 0), which is M4's job.
- **M3 (first version)**: `struct_cong` / `struct_cong_l2`, a hurdle model per binding constraint without
  outage information. `struct_cong` wins MAE on congestion but loses on RMSE/CRPS to LEAR v2; `struct_cong_l2`
  is worse than persistence. RT congestion is still roughly tied with `zero_congestion` on CRPS.
- **M3 outage step (2026-10-02): no congestion gain.** Ingested the DAM outage lists (P-54C; the RT
  `sched_outages` feed only looks ~2.6 h ahead, useless at the D−1 issue) and mapped outages to constraints
  (station-name match + cross-fitted binding lift). `struct_cong_out` improves binding log loss ~1% on six
  diagnostic folds, but over 36 folds congestion is slightly *worse* than `struct_cong`: DA CRPS 3.135 vs
  3.069 (RMSE 11.56 vs 10.89), RT CRPS 4.971 vs 4.919. On outage-onset constraint-hours it is worse than v1
  (log loss +1.5% DA, +5.6% RT); the small gains come after outages end. Recent binding history carries
  ~60% of P(bind) gain and already reflects long outages; the D−1 list cannot see outages starting on D.
  Kept as an ensemble candidate, not adopted. A forward schedule (P-14B) must be archived from now on to
  test planned-outage onsets.
- **M3w step 1-2: HRRR weather and the weather-to-load correction (2026-10-02).** `weather_hrrr` (NOAA HRRR 06z
  D−1, public domain, zone aggregates incl. convection) replaces nothing yet but is the licensed path off
  Open-Meteo. `loadfix_gbm` predicts the error of the ISOLF D−2 forecast from the weather change since that
  file. NYISO total over 36 folds: RMSE 538 MW vs 583 for debiased ISOLF D−2 (−8%) and 697 raw; MAPE 2.16% vs
  2.34%. It recovers ~55% of the gap to the (unusable) debiased D−1 file (502 MW) and beats it in winter (432 vs
  448). The calendar-only ablation (619 MW) shows the gain is weather, not level-bias learning. ISOLF runs up
  to 13% below P-58B actuals with a seasonal pattern, so raw-ISOLF comparisons overstate any model.
  Next (step 3): corrected load and load surprise as price-model features (OOS stacking table), then M3b.
- **M7 (2026-10-05): signal v1 frozen and evaluated once.** `combo3_eq_aci` (selection rule, pooled CRPS 7.593).
  Holdout total CRPS DA 9.75 vs 11.54 for yesterday's DA (−16%), RT 14.55 vs 19.56 (−26%); intervals calibrated;
  DA RMSE worse than persistence because of January 2026. Details: `docs/SIGNAL_V1.md`.
- **M3b / M4 (2026-10-05)**: spike member and robust combination not adopted; DART v2 positive on validation, now
  paper-traded live. **M5 (2026-10-05)**: monthly DA products, horizons 1-6; the seasonal norm beat the gas x heat-rate
  anchor and the decay model and is the live monthly forecast (`lmp monthly`).
- **M6 (2026-10-05)**: DDNN-JSU member (4-network ensemble) not adopted: worse alone (+30% DA CRPS); in
  combination with LEAR + GBM −1.8% DA, not significant. Signal v1 unchanged.
- **Holdout data complete** (2026-10-02): warehouse and panel cover 2025-10-01..2026-09-30. Still locked.

## Metric decision (2026-09-28)
Primary scores are **CRPS** (whole predictive distribution) and **RMSE** (conditional mean); MAE is
secondary. Reason: MAE rewards the median. For zero-inflated targets (congestion is ~0 in 64% of DA and
73% of RT hours) an always-zero forecast ties the structural model on RT congestion MAE while being
useless for trading, where DART P&L is linear in the price difference. `zero_congestion` is a formal
baseline; models are compared to `persist_da_d1` on CRPS / squared error with DM tests.

## Design principle added after M2: fit once, post-process many times
Refitting a model to change something about its *outputs* (clipping, window averaging, combination,
calibration) is waste. Model runs store their raw out-of-sample outputs; post-processing runs read
them from the registry, take seconds, and are logged as their own trials with parent-run lineage.

## M2.5: quick wins (evidence: strong/replicated; mostly European DA + PJM)
1. **Post-processing layer**: combine / calibrate / clip over stored OOS predictions, no refits.
2. **Faster, better LEAR**: one Gram matrix shared by the 24 hourly LASSO fits; penalty chosen by
   time-ordered validation instead of LARS-AIC (Lipiecki & Weron 2026); add a short 56-day window;
   store each window's raw forecast so window subsets and clipping are post-hoc.
3. **Cross-family combination**: LEAR + LightGBM (equal weights, and weights learned on earlier folds
   only). Per-hour and pooled models are complementary (Ziel & Weron 2018).
4. **Adaptive conformal intervals** (ACI, Gibbs & Candès 2021) per zone × hour, updated only with
   outcomes known at issue time, replacing static residual quantiles.
5. **Evaluation**: spike-hour vs normal-hour splits; Kupiec / Christoffersen coverage tests.

## Training protocol (agreed 2026-10-05)
Training is bounded: a fixed start and end per phase, not open-ended variant-and-retrain.

1. **Signal v1 candidate pool is closed** after the queued runs of 2026-10-05 (`gbm_l1_v3`, `lear_wx` and the
   post presets `gbm_l1_v3_aci`, `lear_wx_clip`, `lear_wx_clip_aci`, `combo3wx_eq_aci`). No new model families,
   feature variants or full retrains for v1.
2. **One extra post-processing candidate**, declared now: `assemble_v1_final`: congestion from `lear2_long_aci`,
   energy and loss from the better (by pooled total CRPS) of `combo3wx_eq_aci` / `combo3_eq_aci`, then ACI.
3. **Selection rule** (fixed before the final scoreboard is read): lowest total-price CRPS averaged over DA and RT
   on the 36 folds, subject to (a) Holm-adjusted DM p < 0.05 vs `persist_da_d1` on CRPS in both markets and
   (b) PBO < 0.5. Within 1% CRPS the simpler candidate wins. DSR / SPA are reported, not used.
4. **Freeze and evaluate once (M7):** record the winner's config and git commit as signal v1, unlock the holdout,
   run the frozen configuration on 2025-10..2026-09, report whatever comes out. Training for this phase ends.
5. **Later model milestones** (M3b, M4, M6, ...) declare their candidate list and a maximum number of full runs
   (default 3) before starting; smoke tests do not count. When the budget is spent, the milestone stops.

Ideas that come up meanwhile go to `docs/RESEARCH_LOG.md`, not into another retrain.

## M3: structural congestion (evidence: strong theory, no published real-ISO horse race)
Per-constraint hurdle model for the top 50–100 constraints: P(bind) (regularized logistic / GBM) ×
shadow price given binding (quantile model), mapped to nodes through pooled reduced-rank shift
factors re-estimated per topology epoch; rare constraints grouped into a residual term; joint
simulation for quantiles. Drivers: interface utilization, scheduled outages mapped to constraints,
zonal load/weather, imports, gas-spread regime (regional hub data is not free: gap). The congestion
regime Markov chain becomes a *feature* (filtered regime probabilities), not the forecaster, because
binding patterns almost never repeat (4,655 distinct sets in 8,760 hours).

## M3b: RT spike track (evidence: moderate, US real: Hubert, Lolas & Sircar 2026, NYISO MMU)
Sparse logistic spike-occurrence model per zone (lagged reserve prices and shortage flags, load-forecast
error, decayed counts of recent spikes, NYC/LI outages, thunderstorm proxy × load) plus an
ORDC-aware magnitude model (energy + Σ P(shortage_k) × reserve-curve step + congestion) with an EVT tail.
Report results with and without 2025-06-24 (single-event concentration).

### M3b declaration (2026-10-05, before any M3b run)
- **Target**: RT total price spikes. Spike = RT total ≥ the zone's 95th percentile of RT total over the 365 training
  days before the fold's training end (top-5% hours carry 30–38% of absolute DART spread in validation).
- **Model** (`spike` member): per-zone-hour P(spike) from an L1-regularized logistic regression pooled over the 11
  internal zones (zone and hour-block indicators); spike magnitude as threshold + GPD-fitted excess per zone, fit
  in-fold. Features, from the research notes (MMU drivers; Hubert, Lolas & Sircar 2026), all as of 05:00 ET D−1:
  lagged reserve prices (RT ASP up to issue, DA ASP of D−1) and shortage counts (RT 10/30-min reserve price above
  $50 over the last 7 days), decayed counts of recent zone spikes (RT through D−2), load-forecast surprise
  (`load_surprise_*`), HRRR storm proxy (CAPE p90 × reflectivity share × hot-hour load), temperature extremes,
  NYC/LI outages on the DAM list of D−1, gas.
- **Integration** (post-processing over signal v1, RT total only; components unchanged in this milestone):
  mixture F = (1 − p)·F_v1 + p·F_spike. Post variants declared: `v1_spike_mix` and `v1_spike_mix_aci` (ACI after the mix).
- **Budget: 3 full runs.** (1) full features; (2) ablation without HRRR storm features; (3) reserved for one
  bug-fix re-run. Smoke runs do not count. Post variants: the two above only.
- **Metrics**: spike Brier and log loss vs in-fold climatology and vs "spiked at D−2" persistence; RT total CRPS
  pooled and on top-5% hours vs `combo3_eq_aci`, DM tests, all reported with and without 2025-06-24.
- **Adoption rule**: a variant becomes signal v2 only if pooled RT total CRPS and top-5%-hour RT CRPS both improve
  on `combo3_eq_aci` with Holm-adjusted DM p < 0.05 (both with and without 2025-06-24). The holdout is spent (M7),
  so v2 evidence is validation plus the live track record; no second holdout evaluation.

### M3b result (2026-10-05): spike member works, not adopted into the signal
Budget used: run 1 `spike_full-20261005T062326-ef62f5`; run 2 `spike_no_storm` killed after 10 folds (out of memory
while post-processing ran concurrently; marked failed); run 3 its re-run `spike_no_storm-20261005T065811-2bd4e0`.
- Classifier: beats in-fold climatology on Brier in 35/36 folds and "spiked at D−2" in 34/36; pooled Brier 0.0403,
  log loss 0.1416 (base rate 7.4%). HRRR storm features add little (log loss 0.1423 without them).
- Mixed into signal v1's RT total (`v1_spike_mix`): RT CRPS on spike hours −12.4% (Holm p < 0.0001), pooled −2.0%
  (Holm p = 0.12); without 2025-06-24: −12.8% / −1.9% (p = 0.15). `v1_spike_mix_aci` is worse pooled (+1.3%).
- Adoption rule needs both gains significant, so **signal v1 is unchanged**. The spike probabilities stay available
  as a separate risk output (and as an input for DART v2, see `docs/RESEARCH_LOG.md`).

### M4 declaration (2026-10-05, before any M4 run) — post-processing only, no base-model runs
- **Signal candidates** (budget: 2 post presets + 1 reserved for a bug-fix re-run):
  1. `combo3_med_aci`: robust combination, the **median** of `lear_clip`, `gbm_l1` and `persist_da_d1` point
     forecasts (instead of the mean of the first two), then clip and ACI. Guards against one member blowing up, as
     LEAR did in January 2026 (M7).
  2. `combo3_med_spike`: candidate 1, then `spike_mix` with `spike_full` on RT total (M3b's −12% on spike hours).
- **Adoption rule**: a candidate replaces signal v1 only if pooled total CRPS improves on `combo3_eq_aci` in **both**
  DA and RT, each with Holm-adjusted DM p < 0.05 (Holm over the candidates), with and without 2025-06-24. Validation
  only: the holdout is spent.
- **DART v2** (trading rule, not part of the signal; declared, not tuned): spread s = DA distribution mean − RT
  mixture mean, where the distribution mean is the average of the q05..q95 quantiles and the RT mean mixes in the
  spike member, (1 − p)·mean_RT + p·spike mean; spread scale σ_s = sqrt(σ_DA² + σ_RT² − 2ρσ_DAσ_RT) with ρ the zone's
  DA/RT residual correlation over the 365 days before the month (as of the fold's training end). Position and cost as
  in DART v1. Reported on validation only, against DART v1 and the persistence rule, with and without 2025-06-24.
- Not attempted in this milestone (left in the research log): QRA/LQRA, isotonic distributional regression, EVT
  tail splice (the M7 intervals are already calibrated at 90% and 98%).

### M4 result (2026-10-05): no candidate adopted; DART v2 is positive on validation
Budget used: 2 of 3 (`combo3_med_aci-20261005T073759-06aab6`, `combo3_med_spike-20261005T073858-3a40a6`). The
reserved run went to a bug fix in the DART v2 backtest (ρ for the first validation month, which has no earlier
residuals: now 0), not to a signal re-run.

| market | candidate | CRPS v1 | CRPS cand | change | Holm p | change ex 06-24 | Holm p ex 06-24 |
|---|---|---|---|---|---|---|---|
| DA | combo3_med_aci | 4.432 | 4.659 | +5.1% | 1.00 | +5.3% | 1.00 |
| DA | combo3_med_spike | 4.432 | 4.659 | +5.1% | 1.00 | +5.3% | 1.00 |
| RT | combo3_med_aci | 10.754 | 10.751 | −0.03% | 0.48 | −0.00% | 0.50 |
| RT | combo3_med_spike | 10.754 | 10.623 | −1.2% | 0.22 | −1.1% | 0.27 |

- The median of three often picks `persist_da_d1`, so it gives up the LEAR/GBM average's DA skill (DA RMSE 12.7 vs
  12.0). The spike mix only touches RT, which is why the two candidates are identical in DA. **Signal v1 is unchanged.**
- DART v2 (`docs/experiments/dart_v2.md`, validation only): +$231k (+$2.96/MWh, Sharpe 0.92, max drawdown −$39k), or
  +$258k without 2025-06-24. Same rows: DART v1 −$30k, persistence −$16k. Hit rate is 48%, so gains come from size,
  not frequency; the top 1% of days carry 80% of P&L. The holdout is spent, so this has **no out-of-sample
  confirmation**: it goes into paper trading on the live forecasts before any capital (research log).
- Paper trading started 2026-10-05 (first delivery day 2026-10-06): the daily job runs the spike member live
  (`lmp risk` -> `live_spike`) and writes DART v2 positions (`lmp positions` -> `live_dart`); track record via
  `lmp paper` and the dashboard's Signal tab. The rule stays frozen while the record accumulates.

## M4: probabilistic combination (evidence: strong for DA, European)
QRA / LQRA over the member pool + isotonic distributional regression + conformal ensemble; EVT (GPD)
tail splice above the ~0.9 conditional quantile; joint DA/RT samples so the DA−RT spread keeps its
error correlation (for DART later).

## M5: horizon extension
Fuel × heat-rate bid-stack anchor (EIA-923 / CEMS heat rates, calibrated to 3-month-lagged masked
offers), seasonal norms and decay curves per component, monthly congestion from the M3 structure.

### M5 declaration (2026-10-05, before any M5 run)
- **Targets** (monthly products, the inputs for monthly / capability-period TCC and forward valuation): per internal
  zone and month, the average **DA total LBMP** and average **DA congestion** (−mcc, positive = congestion raises the
  price) over **on-peak** hours (Mon–Fri except NERC holidays, HE08–HE23) and **off-peak** hours (all others).
  RT monthly averages, hourly shapes, nodes and TCC path values are out of scope (research log).
- **Issue rule, horizons h = 1..6**: for target month M at horizon h, data cutoff = first day of month M − (h − 1)
  months, minus 7 days (the daily folds' training end, moved back h − 1 months). Prices with delivery date < cutoff.
  Gas = mean Henry Hub spot of the last 10 trade days with trade date ≤ cutoff − 7 days (EIA posts weekly).
- **History**: DA zonal LBMP backfilled to 2015-01 (warehouse only; the daily panel still starts 2021-10, so signal v1
  is unaffected). Forecasts are made for every target month from 2016-01 so each model has its own past errors.
- **Distributions** (same for every model): total in logs, congestion in levels. Quantiles = point forecast combined
  with the empirical quantiles of that model's past errors at the same horizon and zone (errors of target months fully
  known at the cutoff, pooled over on/off-peak; pooled over zones while fewer than 24). Mean = point forecast
  corrected by the mean past error (it is the forecast scored by RMSE).
- **Baselines** (benchmarks, not budgeted): `m5_persist` (last full month before the cutoff), `m5_lastyear` (same
  month a year earlier), `m5_norm` (mean of the same calendar month over all earlier years).
- **Candidates, budget 3 full runs**: (1) `m5_anchor`: total = implied heat rate × gas, heat rate = median of
  (monthly price ÷ monthly Henry Hub) for the zone, calendar month and period over the last 5 years; congestion =
  median of the same calendar month over the last 5 years. (2) `m5_decay`: anchor + decaying recent deviation per
  component, log total = log anchor + φ_h · (log of the last full month's price ÷ its anchor at realized gas),
  congestion = norm + ψ_h · (last full month − its norm), with φ_h, ψ_h ∈ [0, 1] per horizon fit by least squares on
  earlier target months only. (3) reserved for one bug-fix re-run. The EIA-923/CEMS bid stack, masked offers and
  M3-structure congestion are not attempted (no data ingested or no gain in M3; research log).
- **Validation**: target months 2022-10..2025-09 (36), all six horizons. Scores: CRPS (primary) and RMSE, pooled over
  zones, periods and horizons, also by horizon. DM tests on the per-target-month mean loss (36 observations).
- **Adoption, per target** (total, congestion): the candidate with the lowest pooled CRPS is the M5 forecast if it
  beats **every** baseline with Holm-adjusted DM p < 0.05 (Holm over its three comparisons); otherwise the M5
  forecast is the baseline with the lowest pooled CRPS.
- **Then one run on target months 2025-10..2026-09** for the adopted models and the baselines, reported as a check on
  an already-seen period (the M7 holdout year: not used for fitting, but its daily prices have been looked at).

### M5 result (2026-10-05): the seasonal norm wins; no candidate adopted
Budget used: 2 of 3 (`m5_anchor-20261005T080925-a2f04c`, `m5_decay-20261005T080942-c339fc`); the reserved run was not
needed. Baselines: `m5_persist-…d90f81`, `m5_lastyear-…0838ca`, `m5_norm-…dacb08`. Validation, 36 target months ×
6 horizons × 11 zones × on/off-peak (4,752 rows per target):

| model | total CRPS | total RMSE | congestion CRPS | congestion RMSE |
|---|---|---|---|---|
| m5_norm | **10.18** | **20.2** | **3.84** | 8.64 |
| m5_decay | 13.10 | 27.0 | 3.86 | **8.52** |
| m5_anchor | 13.63 | 27.4 | 4.14 | 9.24 |
| m5_persist | 16.83 | 36.9 | 4.67 | 10.81 |
| m5_lastyear | 19.42 | 43.5 | 6.39 | 14.03 |

- Total: `m5_decay` loses to `m5_norm` at every horizon (h1 10.21 vs 10.02, h6 15.2 vs 10.3). The anchor treats spot
  gas at the cutoff as the forecast of future gas: right while gas was stable (2022Q4, 2023Q3–Q4), badly wrong
  after the 2022 spike (2023Q1 CRPS 26 vs 6). Without a gas forward curve (EIA's futures series ended 2024-04) the
  anchor cannot beat the norm. Congestion: decay ties the norm (3.86 vs 3.84; DM vs persistence Holm p = 0.20).
- **M5 forecast = `m5_norm` for both targets** (`presets.M5_CHOICE`). φ_h (total) came out ≈ 0, ψ_h 0.01–0.13.
- Check on the already-seen target months 2025-10..2026-09 (baselines only, since the norm was adopted): total CRPS
  `m5_lastyear` 11.3, `m5_norm` 22.2, `m5_persist` 35.9; congestion `m5_persist` 2.3, `m5_lastyear` 3.2, `m5_norm`
  3.9. Winter 2025–26 broke the norm: NYISO on-peak DA averaged $208 in January 2026 vs a $77 norm, because the norm
  weights 2015–2020 low-price years equally. A norm with recent-year weights or a level adjustment, and a gas forward
  curve, are the next ideas (research log); the declared choice is not re-tuned on this period.
- Live: `lmp monthly` (daily job; the vintage changes on the cutoff, about the 24th) -> `live_monthly`, dashboard
  Signal tab.

## M6: deep and graph models (ensemble members, not replacements)
Feed-forward DNN / NBEATSx ensemble (4+ runs), distributional DNN (Johnson SU); TabPFN-TS or
Chronos-2 with covariates as one ensemble member (check pretraining contamination). TFT and
spatio-temporal GNNs deprioritized (weakest real-ISO evidence).

### M6 declaration (2026-10-05, before any M6 run)
- **Member** `ddnn`: distributional feed-forward network with Johnson's SU output (DDNN-JSU, Marcjasz, Narajewski,
  Weron & Ziel 2023), the strongest classic CRPS model in the research notes. One network per market (DA, RT), pooled
  over the 15 locations. Input per location-day: the panel features for the 24 hours of D (all as of 05:00 ET D−1),
  location one-hot and weekday. Output: JSU parameters for the 24 hours × 4 targets (total, energy, loss, congestion).
  Targets are standardized per fold (median, MAD) and asinh-transformed; quantiles map back through the inverse.
  Architecture fixed in advance, no hyperparameter search: 2 hidden layers (512, 256), ReLU, dropout 0.1, weight decay
  1e-5, Adam (lr 1e-3, batch 256), early stopping on the last 56 days of the training window (patience 20, at most 200
  epochs). Training window: all panel data up to the fold's training end (same monthly refit as the other members).
  **Ensemble of 4 networks** (seeds 0–3) per fold and market, combined by averaging quantiles (the qEns variant).
  Point forecast = mean of the 1%..99% quantiles (a trimmed mean; the JSU-of-asinh mean can explode).
- **Budget: 3 full runs.** (1) `ddnn` with feature set v1 (signal v1's inputs); (2) `ddnn_v3` with v3 (+ HRRR,
  weather-corrected load); (3) reserved for one bug-fix re-run. Smoke runs (≤ 2 folds, not logged) do not count.
- **Post presets** (with `ddnn*` = the run with the lower pooled total CRPS, chosen before any combination is scored):
  `ddnn_aci` (ACI over the member's mean, for the scoreboard), `combo4_eq_aci` (equal-weight mean of `lear_clip`,
  `gbm_l1`, `ddnn*`, then clip and ACI), `combo_dnn_lear_aci` (equal-weight `lear_clip` + `ddnn*`, the literature's
  "DNN ensemble averaged with LEAR"; then clip and ACI).
- **Adoption rule**: a candidate (`ddnn*` raw, `combo4_eq_aci`, `combo_dnn_lear_aci`) replaces signal v1 only if pooled
  total CRPS improves on `combo3_eq_aci` in **both** DA and RT, each with Holm-adjusted DM p < 0.05 (Holm over the
  three), with and without 2025-06-24, and PBO < 0.5. Validation only (the holdout is spent); a signal change would go
  live as v2 with the live track record as its out-of-sample evidence.
- **Not run in M6** (research log): Chronos-2 and TabPFN-TS, because their pretraining corpora and cutoffs (2025)
  overlap the 2022-10..2025-09 validation period, so a validation score cannot be trusted; they can be scored cleanly
  only as live shadow members. NBEATSx: its documented gain over a DNN ensemble is 2–5% and not significant on PJM.
  TFT and graph networks: weakest real-ISO evidence (as above).

### M6 result (2026-10-05): DDNN member not adopted; signal v1 unchanged
Budget used: 2 of 3 (`ddnn-20261005T155208-51c50c`, `ddnn_v3-20261005T162140-04cb4b`); the reserved run was not
needed. `ddnn*` = `ddnn` (pooled total CRPS 8.56 vs 10.94 for `ddnn_v3`; the v3 inputs made it worse). Presets:
`ddnn_aci-…28b6e3`, `combo4_eq_aci-…663eca`, `combo_dnn_lear_aci-…7081af`. Total CRPS vs `combo3_eq_aci`:

| candidate | DA | RT | Holm p (DA / RT) |
|---|---|---|---|
| `ddnn` (own JSU distribution) | +30.3% | +6.7% | 1.00 / 1.00 |
| `combo4_eq_aci` (LEAR + GBM + DDNN) | **−1.8%** | −0.0% | 0.31 / 1.00 |
| `combo_dnn_lear_aci` (LEAR + DDNN) | +2.7% | +4.7% | 1.00 / 1.00 |

Without 2025-06-24 the picture is the same; PBO over the four = 0.003. No candidate passes, so **signal v1 is unchanged**.
- Where the DDNN fails: in ordinary months it is close to LEAR (median fold RMSE ratio 1.09 DA, 1.03 RT); in
  cold-weather shock months it is far worse (DA RMSE 58 vs 30 in 2022-12, Winter Storm Elliott; 84 vs 24 in 2025-01).
  It cannot extrapolate beyond its training range (and the tail guard caps it there), while LEAR extrapolates
  linearly in asinh space.
- Training stopped early: networks ran 21–115 epochs (median ~30) with patience 20, so many had their best
  validation loss within the first few epochs. The literature tunes DNNs with about a day of hyperparameter search
  per market; M6 fixed the architecture in advance. Follow-ups are in the research log.
- Smoke-test fixes before the runs (fold 1, not logged): the output quantiles were sorted together with the
  trimmed-mean grid (wrong quantiles); tails are now clipped to the training range of the transformed target.

## M8: live shadow members (foundation models)

### M8 declaration (2026-10-05, before any M8 forecast)
- **Why live only**: foundation models are pretrained on public series up to 2025, which overlaps the 2022-10..2025-09
  validation folds (and possibly NYISO data itself). Validation scores would be untrustworthy, so **none are
  computed**; the clean test is forecasts issued live, before the outcome exists.
- **Member** `chronos2`: Chronos-2 (`amazon/chronos-2`, Apache-2.0), zero-shot, no fine-tuning. Per location (15)
  and market, the target is the hourly total price in UTC hours. Context: the last 28 days known at issue (DA through
  D−1; RT through the last hour ending at or before 05:00 ET D−1). Covariates: zone load forecast and temperature
  forecast (panel values, past and future). Forecast: the 21 signal quantiles for D's hours (RT includes the gap
  hours between issue and D, which are dropped). Mean = average of the q05..q95 quantiles.
- **Output**: `live_shadow` in experiments.duckdb, beside `live_forecasts`; daily job step `lmp shadow`; it never
  feeds signal v1, DART or the dashboard forecast.
- **Evaluation**: on settled live days, total-price CRPS, RMSE and 90% coverage vs signal v1 on the same rows
  (`lmp shadow --score`). First read-out after 90 settled days: one-sided DM test vs signal v1 per market, and the
  CRPS of an equal-weight mean of the two (descriptive). Entering a signal requires a new declared milestone using
  the live record as its evidence; nothing is adopted from M8 directly.
- **Not in M8**: TabPFN-TS (a second member doubles the daily run time; added only if Chronos-2 shows promise),
  fine-tuning (would need a clean training/evaluation split again).

## M7
Single holdout evaluation, freeze signal v1.
