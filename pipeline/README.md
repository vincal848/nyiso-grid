# pipeline/ (not started)

This directory is reserved for the agentic train, validation and trading pipeline.
It is intentionally empty: phase 1 covers data plus the dashboard only.

When this work starts, it should consume only the DuckDB catalog (`data/nyiso.duckdb`) and
curated Parquet. It must never call NYISO MIS directly, so that ingestion stays in
`src/nyiso/ingest/`.
