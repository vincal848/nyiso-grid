# nyiso-grid

A NYISO power-market research project in two layers:

1. **Warehouse and dashboard.** Five years of public NYISO market data (plus weather, gas and outage
   schedules) in a local Parquet + DuckDB warehouse, with a dashboard modeled on
   [gridstatus.io/live/nyiso](https://www.gridstatus.io/live/nyiso).
2. **LMP forecasting signal** (`pipeline/lmpsignal`). Probabilistic day-ahead and real-time price
   forecasts by zone, split into energy, loss and congestion, validated with time-block
   cross-validation and backtest-overfitting diagnostics. The signal will later feed DART and TCC pricers.

Raw and derived data live in `data/` (git-ignored); every table is rebuildable from the public sources.

## Quick start
```bash
uv sync --extra dev

# warehouse
uv run nyiso backfill            # NYISO MIS history, 2021-10 → current month (resumable)
uv run nyiso external            # EIA Henry Hub, NOAA GHCNh weather, Open-Meteo forecast vintages
uv run nyiso reference           # nodes table + approximate zone polygons
uv run nyiso build               # DuckDB views + time-weighted aggregates
uv run nyiso validate            # coverage / gap report
uv run nyiso docs                # data dictionary -> docs/DATA.md
uv run nyiso serve               # dashboard at http://127.0.0.1:8000

# forecasting signal
uv run lmp panel                 # point-in-time modeling panel (fails on any look-ahead)
uv run lmp baselines             # naive benchmarks over 36 monthly validation folds
uv run lmp train lear            # also: lear2, gbm_l1, gbm_l2, struct_cong, zero_congestion
uv run lmp post combo3_eq_aci    # clip / combine / calibrate stored predictions (no refit)
uv run lmp graphs                # compile structural artifacts -> data/structure.duckdb
uv run lmp report                # scoreboard -> docs/experiments/scoreboard.md

uv run pytest
```

## Documentation
| Doc | Contents |
|---|---|
| [docs/DATA.md](docs/DATA.md) | Every warehouse table and column, units, keys, gaps and conventions |
| [docs/FEATURES.md](docs/FEATURES.md) | Forecasting panel features and their publication times |
| [docs/STRUCTURE.md](docs/STRUCTURE.md) | Stored model internals and the network-structure graph store |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Milestones, decisions (metrics, post-processing) and what comes next |
| [docs/experiments/scoreboard.md](docs/experiments/scoreboard.md) | Validation results for every logged model |
| [docs/research/](docs/research/lmp_forecasting_model_landscape.md) | Literature and industry review behind the model choices |
| [CLAUDE.md](CLAUDE.md) | Working rules for coding agents in this repo |

## Layout
| Path | Role |
|---|---|
| `src/nyiso/datasets.py` | Registry of every MIS dataset: source path, timestamp convention, columns |
| `src/nyiso/ingest/` | MIS and external-source downloads (cached), parsing, DST/UTC normalization, reference data |
| `src/nyiso/store/` | Backfill, Parquet writer, DuckDB catalog, time-weighted aggregates, validation, docs |
| `src/nyiso/dictionary.py` | Data dictionary: source of truth for DuckDB comments and docs/DATA.md |
| `src/nyiso/api/`, `web/` | Read-only FastAPI and the dashboard (ECharts + MapLibre), including the Signal tab |
| `pipeline/lmpsignal/` | Forecasting signal: panel, CV, models, post-processing, diagnostics, registry, reports |
| `data/` | Git-ignored: raw downloads, curated Parquet, DuckDB files, experiment outputs |

## Key conventions
- **Time.** Every table keys on `ts_utc` (interval start, UTC). NYISO real-time LBMP and fuel mix are
  stamped at interval end and shifted to start. Fall-back DST hours are resolved by file order.
- **Irregular RT intervals.** About 4% of dispatch intervals are not 5 minutes; aggregates rebuild each
  interval's true length and time-weight it, matching NYISO's integrated hourly RT LBMP to the cent.
- **No look-ahead.** Forecasts for day D are issued 05:00 ET on D−1 (DAM bid deadline). Every input
  carries its publication time and the panel build fails if anything post-dates the issue.
- **Honest validation.** 36 monthly rolling-origin folds with an embargo, a locked 12-month holdout,
  every trial logged (including failed and exploratory ones), CRPS and RMSE as primary metrics.
- **Zone boundaries** are approximate (county-based); see docs/DATA.md.
