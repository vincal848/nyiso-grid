# nyiso-grid — rules for agents working in this repo

## Layering (do not break)
`ingest` → `store` → `api` → `web`. Each layer imports only from layers to its left.
- `src/nyiso/ingest/` — talks to NYISO MIS and external sources, parses files. Knows nothing about DuckDB or HTTP APIs.
- `src/nyiso/store/` — writes curated Parquet, builds DuckDB views/aggregates.
- `src/nyiso/api/` — read-only FastAPI over DuckDB. No ingestion here.
- `web/` — static HTML/JS, talks only to `/api/*`.
- `pipeline/lmpsignal/` — LMP forecasting signal (phase 2). Reads the warehouse read-only; writes only
  `data/features.duckdb`, `data/experiments.duckdb`, `data/experiments/` and `data/structure.duckdb`.
  Must not import `nyiso.api`. The dashboard API may *read* those files (never import pipeline code).
  The frozen signal (`docs/SIGNAL_V1.md`, `pipeline/lmpsignal/presets.py`) runs live via `lmp forecast`; its outputs go
  to experiments.duckdb (`live_forecasts`, `live_node_forecasts`) and data/experiments/live/. The M3b spike member
  (`live_spike`) and DART v2 paper positions (`live_dart`) run beside it; neither is part of the signal.
  M5 monthly forecasts (`lmp monthly`, `presets.M5_CHOICE`) go to `live_monthly`; the M8 Chronos-2 shadow member
  (`lmp shadow`, live-only, never feeds the signal) goes to `live_shadow`. Ingestion for the daily
  job is orchestrated outside the pipeline by scripts/daily.py.
- Keep everything a model computes: predictions with quantiles per fold, and model internals as
  artifacts (`registry.save_artifact`; see `docs/STRUCTURE.md`). Metrics are derived, never the only record.
- DART/TCC pricing is a later phase: build and validate the LMP signal first.

## Data context — read first
- `docs/DATA.md` is the data dictionary: every table and column, units, keys, known gaps, and the
  conventions (timestamps, DST, time weighting, LBMP sign convention, as-of availability, licensing).
  Read it before querying data. `docs/FEATURES.md` documents the forecasting panel.
- Source of truth is `src/nyiso/dictionary.py`. When adding or changing a dataset, table or column,
  update it; `tests/test_dictionary.py` fails otherwise. Then run `nyiso build` (applies DuckDB
  comments) and `nyiso docs` (regenerates docs/DATA.md and docs/data_dictionary.json).
- In SQL: `SELECT table_name, column_name, comment FROM duckdb_columns() WHERE NOT internal`.

## Data rules
- `data/raw/` is an immutable cache of downloads. Never edit; delete a file to force re-download.
- `data/curated/` is fully rebuildable from `data/raw/` (`nyiso backfill --rebuild`).
- All curated tables key on `ts_utc` (interval start, UTC). `ts_local` (America/New_York, naive) is for display only.
- New MIS dataset = one entry in `src/nyiso/datasets.py`; new external source = `src/nyiso/ingest/external.py`.
- `weather_fcst` (Open-Meteo) is research-only; replace it with a licensed source before live trading.

## Forecasting rules (pipeline/lmpsignal)
- Issue time for delivery day D is 05:00 ET on D−1 (DAM bid deadline). Every feature must be as-of that
  time; `lmp panel` fails if any `_avail_*` audit column exceeds `issue_utc`. Document every new
  feature in `panel.FEATURES` (tests enforce it).
- Validation = 36 monthly rolling-origin folds (2022-10..2025-09) with a 7-day embargo. The final
  holdout (2025-10..2026-09) is locked by `config.guard`; unlock it only for the single M7 evaluation.
- Structural estimates (shift factors, regimes) must be fit inside each fold on training data only.
- Fit once, post-process many times: changes to model *outputs* (clipping, window averaging,
  combination, calibration) go through `lmp post` over stored OOS predictions, never a refit.
  Models should store their raw per-variant outputs (e.g. LEAR v2 stores each window's forecast).
- Roadmap: `docs/ROADMAP.md` (authoritative milestone list).
- Primary metrics are CRPS and RMSE; MAE is secondary (it rewards the median; an always-zero forecast
  can win MAE on congestion). Point forecasts for trading should target the conditional mean.
- Every model run goes through `runner.run` so it lands in the registry; compare models with `lmp report`.
  Never delete runs: every configuration tried counts toward the Deflated Sharpe Ratio's trial number.
  Each run logs config hash, code fingerprint, git commit, panel-data fingerprint, environment and duration, and
  stores the exact panel it received (`runs.panel_hash`; compare runs with `lmp panel-diff A B`).
- Training is bounded by the protocol in `docs/ROADMAP.md` ("Training protocol"): signal v1's candidate pool is
  closed; later model milestones declare a candidate list and a full-run budget (default 3) before starting.
  Do not start new variants or retrains outside a declared budget; log the idea in `docs/RESEARCH_LOG.md`.
- `lmp report` includes overfitting diagnostics (PSR, DSR, MinTRL, Holm/BHY-adjusted DM, SPA/Reality Check,
  PBO via CSCV) computed on daily forecast skill vs benchmarks. They are descriptive: no model is accepted or
  rejected on them except through the selection rule in `docs/ROADMAP.md` (lowest pooled total CRPS, gated by
  Holm-adjusted DM vs `persist_da_d1` and PBO < 0.5; DSR/SPA reported only).

## Commands
- `uv run nyiso backfill [--datasets a,b] [--start 2021-10] [--end 2026-09]`
- `uv run nyiso external [--sources gas_henry_hub,weather_obs,weather_fcst]`
- `uv run nyiso reference` — nodes table + zone polygons
- `uv run nyiso build` — DuckDB views + aggregates (stop `nyiso serve` first; it holds the DB file)
- `uv run nyiso validate` — coverage/gap report
- `uv run nyiso docs` — regenerate the data dictionary docs
- `uv run nyiso serve` — dashboard at http://127.0.0.1:8000
- `uv run lmp panel | baselines | report | docs` — forecasting harness
- `uv run lmp train <lear|lear2|gbm_l1|gbm_l2> [--smoke N]` — validate a model (smoke = first N folds, not logged)
- `uv sync --extra dev --extra deep` then `uv run lmp train ddnn` — M6 neural member (torch, CUDA 12.6 wheels; optional)
- `uv run lmp graphs` — compile structural artifacts into data/structure.duckdb (dashboard Signal tab)
- `uv run lmp post <preset>` — clip / combine / calibrate stored predictions (seconds to minutes, logged as a trial)
- `uv run lmp m7 <signal>` — the single holdout evaluation (needs `LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7`; done for v1)
- `uv run lmp forecast [--date D]` / `uv run lmp nodes [--date D]` — live forecast of the frozen signal (zones / nodes)
- `uv run lmp dart [--rule v1|v2]` — DART backtest on stored forecasts -> docs/experiments/dart_prototype.md (v1) / dart_v2.md (v2)
- `uv run lmp risk [--date D]` / `uv run lmp positions [--date D]` / `uv run lmp paper` — live spike risk, DART v2 paper
  positions, paper-trading track record
- `uv run lmp m5 <models> [--window validation|holdout]` / `uv run lmp monthly` — M5 monthly DA products (runs / live)
- `uv run lmp shadow [--date D] [--score]` — M8 Chronos-2 live shadow forecast / its live record vs signal v1
- `uv run python scripts/daily.py` — daily job: data refresh, build, panel, forecast, nodes, risk, positions, monthly, shadow (04:30 ET)
- `uv run pytest` and `uv run ruff check src pipeline scripts tests` (CI runs both)
