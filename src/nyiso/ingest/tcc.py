"""NYISO TCC auction results from the public TCC site (tcc.nyiso.com/tcc/public, no login).

Two reports per auction round, both downloaded as CSV (POST, format=csv) and cached raw in data/raw/tcc/:
  nodal_prices    clearing price at every point of injection/withdrawal (POI) for each contract period of the round;
                  a TCC from POI to POW costs price(POW) - price(POI)
  awards_summary  awarded paths: POI, POW, bid or offer, TCCs (MW) awarded, path market clearing price (MCP)
Round list: the option list of the report form (every round since 2006). Prices are $ per TCC (1 MW) for the whole
contract period, which is what a TCC pays out as the sum of hourly DA congestion differences over that period.

`posted_date` (from the report header) is when the result became public; use it as the as-of date.
"""
from __future__ import annotations

import io
import re
import time

import httpx
import pandas as pd

from nyiso.config import RAW

BASE = "https://tcc.nyiso.com/tcc/public"
TCC_KEYS = ("tcc_rounds", "tcc_nodal_prices", "tcc_awards")
REPORTS = {"nodal_prices": "view_nodal_prices", "awards_summary": "view_awards_summary"}
_TIMEOUT = httpx.Timeout(120.0, connect=30.0)

_LABEL = re.compile(r"^(?P<year>\d{4}) (?P<season>Winter|Spring|Summer|Autumn) (?P<what>.+?) "
                    r"\(Ver (?P<ver>\d+) - (?P<status>\w+)\)$")
_TERMS = {"One Year": 12, "Six Month": 6, "Two Year": 24}


def parse_rounds(html: str) -> pd.DataFrame:
    """The round dropdown of a report page -> one row per round (id, label and what the label encodes)."""
    rows = []
    for rid, label in re.findall(r'<option value="(\d+)">([^<]+)</option>', html):
        m = _LABEL.match(label.replace("&amp;", "&").strip())
        if m is None:
            raise ValueError(f"unrecognised TCC round label: {label!r}")
        what = m["what"]
        if what.startswith("Centralized TCC Auction"):
            kind, rn = "centralized", re.search(r"Round (\d+)", what)
        elif what.startswith("Monthly Reconfiguration"):
            kind, rn = "monthly", None
        elif what.startswith("Balance-of-Period"):
            kind, rn = "bop", None
        else:
            kind, rn = "fixed_price", None                       # non-historic fixed-price allocation/renewal: no clearing
        term = next((t for t in _TERMS if t in what), None)
        rows.append({"round_id": int(rid), "label": label.strip(), "season_year": int(m["year"]), "season": m["season"],
                     "kind": kind, "round_no": int(rn[1]) if rn else None, "term_months": _TERMS.get(term),
                     "version": int(m["ver"]), "status": m["status"]})
    return pd.DataFrame(rows).astype({"round_no": "Int64", "term_months": "Int64"})


def parse_report(text: str) -> tuple[pd.DataFrame, str, str]:
    """A downloaded CSV -> (data rows with columns renamed to snake_case, posted_date, status).

    The header block is a few title lines ('Current Status - Approved', '"Posted: October 1, 2026"'), then the table."""
    lines = text.lstrip("\ufeff").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("Period ID,"))
    head = "\n".join(lines[:start])
    posted = re.search(r"Posted: ([A-Za-z]+ \d+, \d{4})", head)
    status = re.search(r"Current Status - (\w+)", head)
    if posted is None or status is None:
        raise ValueError("TCC report header has no posted date / status")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df = df[pd.to_numeric(df["Period ID"], errors="coerce").notna()]          # drops the 'Report Created' footer
    df.columns = [re.sub(r"\s*\(.*\)", "", c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns={"period_duration": "period_months", "start_date": "period_start", "end_date": "period_end",
                            "ptid_name": "poi_name", "ptid": "poi", "zone": "poi_zone"})
    for c in ("period_start", "period_end"):
        df[c] = pd.to_datetime(df[c], format="%m/%d/%Y")
    ints = [c for c in ("period_id", "period_months", "poi", "pow", "tccs_awarded") if c in df]
    df = df.astype({c: "int64" for c in ints})
    posted_date = str(pd.to_datetime(posted[1], format="%B %d, %Y").date())
    return df, posted_date, status[1]


def _post(path: str, form: dict) -> str:
    for attempt in range(4):
        try:
            r = httpx.post(f"{BASE}/{path}.do", data=form, timeout=_TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return r.text
        except (httpx.HTTPError, httpx.TransportError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt * 3)
    raise AssertionError("unreachable")


def fetch_rounds() -> pd.DataFrame:
    return parse_rounds(httpx.get(f"{BASE}/view_nodal_prices.do", timeout=_TIMEOUT).text)


def fetch_report(round_id: int, report: str, refresh: bool = False, pause: float = 0.3) -> str:
    """CSV text of one report for one round, cached in data/raw/tcc/. A cached result that was not yet 'Finalized'
    is fetched again (approved results can still be revised)."""
    path = RAW / "tcc" / f"{round_id}_{report}.csv"
    if path.exists() and not refresh and "Current Status - Finalized" in path.read_text(encoding="utf-8"):
        return path.read_text(encoding="utf-8")
    text = _post(f"{REPORTS[report]}_xls_view", {"display": "Y", "roundVersionId": round_id, "format": "csv"})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    time.sleep(pause)
    return text
