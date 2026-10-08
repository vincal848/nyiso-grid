"""DuckDB catalog: views over curated Parquet, aggregate tables, reference tables, validation."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from nyiso.config import CURATED, DATA, DB_PATH, REF
from nyiso.datasets import DATASETS
from nyiso.ingest import geo, reference
from nyiso.store.timeweight import twa_sql

AGG_SQL = Path(__file__).with_name("aggregates.sql")


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    con.execute("SET TimeZone = 'UTC'")
    return con


def _glob(key: str) -> str:
    return (CURATED / key / "**" / "*.parquet").as_posix()


def available_keys() -> list[str]:
    from nyiso.ingest.external import EXTERNAL
    from nyiso.ingest.tcc import TCC_KEYS

    return [k for k in [*DATASETS, *EXTERNAL, *TCC_KEYS] if any((CURATED / k).rglob("*.parquet"))]


def interval_keys() -> list[str]:
    """MIS interval datasets (validated for coverage); excludes snapshot and external tables."""
    return [k for k in available_keys() if k in DATASETS and not DATASETS[k].snapshot_keys]


def create_views(con: duckdb.DuckDBPyConnection) -> list[str]:
    keys = available_keys()
    for k in keys:
        con.execute(f"CREATE OR REPLACE VIEW {k} AS "
                    f"SELECT * FROM read_parquet('{_glob(k)}', hive_partitioning = false)")
    return keys


def build_reference(refresh: bool = False) -> dict:
    """nodes.parquet (generators + which price sets they appear in) and zones.geojson."""
    REF.mkdir(parents=True, exist_ok=True)
    gens = reference.generators(refresh)
    loads = reference.loads(refresh)
    loads.to_parquet(REF / "loads.parquet", index=False)

    priced: set[int] = set()
    if any((CURATED / "da_lbmp_node").rglob("*.parquet")):
        priced = set(duckdb.sql(f"SELECT DISTINCT ptid FROM read_parquet('{_glob('da_lbmp_node')}')")
                     .df()["ptid"].dropna().astype(int))
    gens["has_prices"] = gens["ptid"].isin(priced)
    gens.to_parquet(REF / "nodes.parquet", index=False)

    zones = geo.build_zones(gens)
    (REF / "zones.geojson").write_text(json.dumps(zones))

    has_coords = gens["lat"].notna() & gens["lon"].notna()
    report = {
        "generators": len(gens),
        "with_coords": int(has_coords.sum()),
        "priced_nodes": len(priced),
        "priced_with_coords": int((gens["has_prices"] & has_coords).sum()),
        "priced_missing_from_generator_csv": len(priced - set(gens["ptid"].dropna().astype(int))),
        "zones": [f["properties"]["zone"] for f in zones["features"]],
    }
    (REF / "reference_report.json").write_text(json.dumps(report, indent=2))
    return report


def build(con: duckdb.DuckDBPyConnection | None = None) -> None:
    con = con or connect()
    create_views(con)
    if (REF / "nodes.parquet").exists():
        con.execute(f"CREATE OR REPLACE TABLE nodes AS SELECT * FROM '{(REF / 'nodes.parquet').as_posix()}'")
    # RTD-interval series -> time-weighted 5-minute grid (aggregates.sql builds on these)
    con.execute("CREATE OR REPLACE TABLE rt_lbmp_zone_5m AS "
                + twa_sql("rt_lbmp_zone", "zone", ["lbmp", "mlc", "mcc"]))
    con.execute("CREATE OR REPLACE TABLE fuel_mix_5m AS " + twa_sql("fuel_mix", "fuel", ["gen_mw"]))
    con.execute("CREATE OR REPLACE TABLE load_zone_5m AS "
                + twa_sql("load", "zone", ["load_mw"], stamped="start"))
    con.execute("CREATE OR REPLACE TABLE interface_flows_hourly AS "
                + twa_sql("interface_flows", "interface", ["flow_mw", "pos_limit_mw", "neg_limit_mw"],
                          bucket="1 HOUR", stamped="start"))
    con.execute(AGG_SQL.read_text())


# ---------------------------------------------------------------- validation

def validate() -> tuple[pd.DataFrame, dict[str, int]]:
    """Per dataset per local day: distinct (snapped) intervals vs expected, plus duplicate keys.

    Runs partition by partition in an in-memory DuckDB (no lock on nyiso.duckdb). Keys never
    span partitions (each file holds one source month), so per-file duplicate checks are complete.
    Sparse event datasets (constraints) only report presence.
    """
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    frames, dups = [], {}
    for key in interval_keys():
        ds = DATASETS[key]
        minutes = ds.interval_min
        bucket = f"time_bucket(INTERVAL {minutes} MINUTE, ts_utc + INTERVAL {minutes * 30} SECOND)"
        where = ("WHERE issue_date = CAST(timezone('America/New_York', ts_utc) AS DATE) - INTERVAL 1 DAY"
                 if key == "load_forecast" else "")
        entity = " || '|' || ".join(f"CAST({c} AS VARCHAR)" for c in ds.curated_entity)
        keys = ", ".join(["ts_utc", *ds.curated_entity] + (["issue_date"] if ds.wide else []))
        dups[key] = 0
        for f in sorted((CURATED / key).rglob("*.parquet")):
            src = f"read_parquet('{f.as_posix()}')"
            frames.append(con.execute(f"""
                WITH b AS (
                    SELECT CAST(timezone('America/New_York', ts_utc) AS DATE) AS day, {bucket} AS t, {entity} AS e
                    FROM {src} {where}
                )
                SELECT '{key}' AS dataset, day, count(DISTINCT t) AS intervals,
                       count(DISTINCT e) AS entities, count(*) AS rows
                FROM b GROUP BY day
            """).df().assign(interval_min=minutes))
            dups[key] += con.execute(
                f"SELECT count(*) FROM (SELECT {keys} FROM {src} GROUP BY ALL HAVING count(*) > 1)"
            ).fetchone()[0]

    cov = pd.concat(frames, ignore_index=True)
    # a local day can straddle two monthly files (interval-ending shift) -> merge
    cov = (cov.groupby(["dataset", "day", "interval_min"], as_index=False)
              .agg(intervals=("intervals", "sum"), entities=("entities", "max"), rows=("rows", "sum")))
    cov["day"] = pd.to_datetime(cov["day"])
    # days entirely missing within each dataset's span
    missing = []
    for key, g in cov.groupby("dataset"):
        if key.endswith("constraints"):
            continue
        full = pd.date_range(g["day"].min(), g["day"].max(), freq="D")
        for d in full.difference(pd.DatetimeIndex(g["day"])):
            missing.append({"dataset": key, "day": d, "interval_min": DATASETS[key].interval_min,
                            "intervals": 0, "entities": 0, "rows": 0})
    if missing:
        cov = pd.concat([cov, pd.DataFrame(missing)], ignore_index=True)
    # expected intervals per local day (23/24/25 hours around DST)
    start = cov["day"].dt.tz_localize("America/New_York")
    end = (cov["day"] + pd.Timedelta(days=1)).dt.tz_localize("America/New_York")
    cov["expected"] = ((end - start) / pd.to_timedelta(cov["interval_min"], unit="min")).astype(int).clip(lower=1)
    cov["coverage"] = (cov["intervals"] / cov["expected"]).clip(upper=1.0)
    cov.loc[cov["dataset"].str.endswith("constraints"), "coverage"] = 1.0  # event data: presence only
    cov = cov.sort_values(["dataset", "day"]).reset_index(drop=True)
    cov.to_parquet(DATA / "coverage.parquet", index=False)
    return cov, dups
