"""Parse tests on slices of real tcc.nyiso.com downloads (tests/fixtures/tcc_*)."""
from pathlib import Path

import pandas as pd

from nyiso.dictionary import TABLES
from nyiso.ingest import tcc
from nyiso.store.tcc import build, write

FX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FX / name).read_text(encoding="utf-8")


def test_parse_rounds_decodes_labels():
    r = tcc.parse_rounds(_read("tcc_round_list.html")).set_index("round_id")
    assert r.loc[3511, ["kind", "round_no", "term_months", "status"]].tolist() == ["centralized", 6, 6, "Approved"]
    assert r.loc[3504, "term_months"] == 12 and r.loc[3484, "term_months"] == 24
    assert r.loc[3507, "kind"] == "bop" and pd.isna(r.loc[3507, "term_months"])
    assert r.loc[3507, "season_year"] == 2026 and r.loc[3507, "season"] == "Summer"


def test_parse_nodal_prices_drops_footer_and_reads_header():
    df, posted, status = tcc.parse_report(_read("tcc_nodal_prices_20260827.csv"))
    assert (posted, status) == ("2026-08-27", "Approved")
    assert len(df) == 12 and df["poi"].dtype == "int64"                       # footer row dropped, ids are ints
    assert df.iloc[0][["poi", "poi_name", "poi_zone", "nodal_price"]].tolist() == [23512, "ARTHUR_KILL_2", "N.Y.C.", 24978.59]
    assert df["period_start"].iloc[0] == pd.Timestamp("2026-11-01") and df["period_months"].iloc[0] == 12


def test_parse_old_round_has_negative_prices():
    df, posted, status = tcc.parse_report(_read("tcc_nodal_prices_20060920.csv"))
    assert (posted, status) == ("2006-09-20", "Finalized") and (df["nodal_price"] < 0).any()


def test_parse_awards():
    df, posted, _ = tcc.parse_report(_read("tcc_awards_20261001.csv"))
    assert posted == "2026-10-01" and set(df["award_type"]) <= {"Bid", "Offer"}
    assert df.loc[df["poi"] == 61754, "mcp"].iloc[0] == -6941.83 and df["tccs_awarded"].dtype == "int64"


def test_build_and_write_match_the_dictionary(tmp_path, monkeypatch):
    rounds = tcc.parse_rounds(_read("tcc_round_list.html")).query("round_id == 3504")
    reports = {(3504, "nodal_prices"): _read("tcc_nodal_prices_20260827.csv"),
               (3504, "awards_summary"): _read("tcc_awards_20261001.csv")}
    tables = build(rounds, reports)
    for k, df in tables.items():
        assert list(df.columns) == list(TABLES[k].columns), k
    monkeypatch.setattr("nyiso.store.writer.CURATED", tmp_path)
    write(tables)
    assert (tmp_path / "tcc_nodal_prices" / "year=2026" / "month=08" / "part.parquet").exists()
