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

## M4: probabilistic combination (evidence: strong for DA, European)
QRA / LQRA over the member pool + isotonic distributional regression + conformal ensemble; EVT (GPD)
tail splice above the ~0.9 conditional quantile; joint DA/RT samples so the DA−RT spread keeps its
error correlation (for DART later).

## M5: horizon extension
Fuel × heat-rate bid-stack anchor (EIA-923 / CEMS heat rates, calibrated to 3-month-lagged masked
offers), seasonal norms and decay curves per component, monthly congestion from the M3 structure.

## M6: deep and graph models (ensemble members, not replacements)
Feed-forward DNN / NBEATSx ensemble (4+ runs), distributional DNN (Johnson SU); TabPFN-TS or
Chronos-2 with covariates as one ensemble member (check pretraining contamination). TFT and
spatio-temporal GNNs deprioritized (weakest real-ISO evidence).

## M7
Single holdout evaluation, freeze signal v1.
