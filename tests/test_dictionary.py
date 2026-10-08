"""The data dictionary must cover every dataset, table and column — so context never goes stale."""
import re
from pathlib import Path

import pytest

from nyiso.config import DB_PATH
from nyiso.datasets import DATASETS
from nyiso.dictionary import COLUMNS, TABLES
from nyiso.store.docs import col_desc

SRC = Path(__file__).parents[1] / "src" / "nyiso" / "store"


def test_every_dataset_is_documented():
    assert set(DATASETS) <= set(TABLES)
    from nyiso.ingest.external import EXTERNAL

    assert set(EXTERNAL) <= set(TABLES)
    for key, ds in DATASETS.items():
        if ds.snapshot_keys:
            assert set(ds.snapshot_keys) | {"first_seen_utc", "last_seen_utc"} <= set(TABLES[key].columns), key
            continue
        cols = {f"{c}_utc" if c in ds.datetime_cols else c for c in ds.columns.values()} | {"ts_utc", "ts_local"}
        if ds.wide:
            cols |= {"zone", "load_forecast_mw", "issue_date"}
        assert cols <= set(TABLES[key].columns), key


def test_every_derived_table_is_documented():
    created = set(re.findall(r"CREATE OR REPLACE TABLE (\w+)", (SRC / "aggregates.sql").read_text()))
    created |= set(re.findall(r'CREATE OR REPLACE TABLE (\w+) AS', (SRC / "catalog.py").read_text()))
    assert created <= set(TABLES), created - set(TABLES)


def test_every_column_has_a_description():
    for t in TABLES.values():
        for c in t.columns:
            assert col_desc(t, c), f"{t.name}.{c}"
        for o in t.overrides:
            assert o in t.columns, f"{t.name}: override for unknown column {o}"
        assert set(t.key) <= set(t.columns), t.name


def test_shared_columns_are_used():
    used = {c for t in TABLES.values() for c in t.columns}
    assert set(COLUMNS) <= used, set(COLUMNS) - used


@pytest.mark.skipif(not DB_PATH.exists(), reason="no built database")
def test_database_matches_dictionary():
    import duckdb

    from nyiso.store.docs import undocumented

    con = duckdb.connect(str(DB_PATH), read_only=True)
    assert undocumented(con) == []
