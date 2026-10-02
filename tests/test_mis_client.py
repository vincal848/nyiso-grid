"""Raw-cache freshness: a month cached before it was complete must be re-fetched."""
import os
from datetime import date, datetime

from nyiso.ingest.mis_client import may_be_incomplete


def _touch(path, written: datetime):
    path.write_bytes(b"x")
    ts = written.timestamp()
    os.utime(path, (ts, ts))
    return path


def test_current_month_is_always_incomplete(tmp_path):
    f = _touch(tmp_path / "202610.zip", datetime(2026, 10, 2, 12))
    assert may_be_incomplete(f, 2026, 10, today=date(2026, 10, 2))


def test_month_cached_while_current_is_refetched(tmp_path):
    f = _touch(tmp_path / "202609.zip", datetime(2026, 9, 28, 12))
    assert may_be_incomplete(f, 2026, 9, today=date(2026, 10, 2))


def test_month_cached_before_last_day_published_is_refetched(tmp_path):
    f = _touch(tmp_path / "202609.zip", datetime(2026, 10, 1, 9))
    assert may_be_incomplete(f, 2026, 9, today=date(2026, 10, 5))


def test_complete_month_is_kept(tmp_path):
    f = _touch(tmp_path / "202608.zip", datetime(2026, 9, 2, 0))
    assert not may_be_incomplete(f, 2026, 8, today=date(2026, 10, 2))
