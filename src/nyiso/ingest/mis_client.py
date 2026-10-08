"""Download NYISO MIS archives into the immutable raw cache.

Monthly archives: {MIS_BASE}/{mis_dir}/{YYYYMM}01{stem}_csv.zip  (one CSV per day)
Daily files:      {MIS_BASE}/{mis_dir}/{YYYYMMDD}{stem}.csv       (fallback for gaps)

Cache layout: data/raw/{key}/{YYYYMM}.zip plus data/raw/{key}/daily/{YYYYMMDD}.csv.
A month whose archive was cached before the month was complete (the current month, or a month fetched
while it was still current) is re-fetched; complete months are never downloaded again.
"""
from __future__ import annotations

import calendar
import time
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from nyiso.config import MIS_BASE, RAW
from nyiso.datasets import Dataset

_TIMEOUT = httpx.Timeout(120.0, connect=30.0)


def http_get(url: str, retries: int = 4) -> bytes | None:
    """GET with retry/backoff. Returns None on 404."""
    for attempt in range(retries):
        try:
            r = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except (httpx.HTTPError, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt * 3)
    return None


def month_days(year: int, month: int, today: date | None = None) -> list[date]:
    today = today or date.today()
    n = calendar.monthrange(year, month)[1]
    return [d for d in (date(year, month, i) for i in range(1, n + 1)) if d <= today]


def is_current_month(year: int, month: int, today: date | None = None) -> bool:
    today = today or date.today()
    return (year, month) == (today.year, today.month)


# NYISO posts a day's files by the next day; allow one more day before trusting a month as complete.
PUBLISH_LAG = timedelta(days=2)


def may_be_incomplete(path: Path, year: int, month: int, today: date | None = None) -> bool:
    """True if a file built from month (year, month) could be missing days: the month is current, or the
    file was written before the month's last day had been published."""
    if is_current_month(year, month, today):
        return True
    month_end = date(year, month, calendar.monthrange(year, month)[1])
    return datetime.fromtimestamp(path.stat().st_mtime).date() < month_end + PUBLISH_LAG


def fetch_month_zip(ds: Dataset, year: int, month: int) -> Path | None:
    dest = RAW / ds.key / f"{year}{month:02d}.zip"
    if dest.exists() and not may_be_incomplete(dest, year, month):
        return dest
    content = http_get(f"{MIS_BASE}/{ds.mis_dir}/{year}{month:02d}01{ds.stem}_csv.zip")
    if content is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(content)
    tmp.replace(dest)
    return dest


def fetch_daily_csv(ds: Dataset, day: date) -> bytes | None:
    dest = RAW / ds.key / "daily" / f"{day:%Y%m%d}.csv"
    if dest.exists():
        return dest.read_bytes()
    content = http_get(f"{MIS_BASE}/{ds.mis_dir}/{day:%Y%m%d}{ds.stem}.csv")
    if content is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    return content


def iter_month_files(ds: Dataset, year: int, month: int) -> Iterator[tuple[date, bytes]]:
    """Yield (file_date, csv_bytes) for every available day in the month.

    Uses the monthly archive; any day missing from it is tried as a daily CSV.
    Days that exist in neither are simply not yielded (validate reports them).
    """
    seen: set[date] = set()
    path = fetch_month_zip(ds, year, month)
    if path is not None:
        with zipfile.ZipFile(path) as zf:
            for name in sorted(zf.namelist()):
                if not name.lower().endswith(".csv"):
                    continue
                d = date(int(name[:4]), int(name[4:6]), int(name[6:8]))
                seen.add(d)
                yield d, zf.read(name)
    for d in month_days(year, month):
        if d in seen:
            continue
        content = fetch_daily_csv(ds, d)
        if content is not None:
            yield d, content
