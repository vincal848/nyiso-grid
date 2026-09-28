"""NERC holiday calendar (used for peak/off-peak classification and calendar features)."""
from __future__ import annotations

from datetime import date, timedelta


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def nerc_holidays(year: int) -> dict[date, str]:
    """NERC off-peak holidays. A holiday falling on Sunday is observed on Monday; Saturday is not moved."""
    fixed = {date(year, 1, 1): "New Year's Day", date(year, 7, 4): "Independence Day",
             date(year, 12, 25): "Christmas Day"}
    out = {}
    for d, name in fixed.items():
        out[d + timedelta(days=1) if d.weekday() == 6 else d] = name
    out[_last_weekday(year, 5, 0)] = "Memorial Day"
    out[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    out[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    return out


def holiday_table(start_year: int, end_year: int) -> list[tuple[date, str]]:
    return sorted((d, n) for y in range(start_year, end_year + 1) for d, n in nerc_holidays(y).items())
