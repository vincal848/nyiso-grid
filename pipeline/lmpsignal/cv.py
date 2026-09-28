"""Time-block cross-validation: rolling-origin monthly blocks with an embargo, nested tuning, holdout guard.

For validation month m (2022-10 .. 2025-09):
  test  = delivery days in month m
  train = delivery days in [train_start, m_start - EMBARGO_DAYS)
where train_start is the burn-in start (expanding window) or m_start - window_days (fixed window).
Every fold is fit only on the past, so structural estimates (shift factors, regimes) re-estimated
inside a fold can never see the scored month.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from lmpsignal.config import (BURN_IN_START, EMBARGO_DAYS, HOLDOUT_END, HOLDOUT_START, VALIDATION_END,
                              VALIDATION_START, guard)


@dataclass(frozen=True)
class Fold:
    name: str             # e.g. "2023-07"
    train_start: date
    train_end: date       # exclusive
    test_start: date
    test_end: date        # exclusive

    def contains_train(self, d: date) -> bool:
        return self.train_start <= d < self.train_end

    def contains_test(self, d: date) -> bool:
        return self.test_start <= d < self.test_end


def _month_starts(start: date, end: date) -> list[date]:
    out, d = [], start
    while d < end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def folds(window_days: int | None = None, start: date = VALIDATION_START, end: date = VALIDATION_END,
          embargo_days: int = EMBARGO_DAYS) -> list[Fold]:
    """Monthly rolling-origin folds. window_days=None -> expanding window from the burn-in start."""
    guard(end - timedelta(days=1))
    out = []
    for m in _month_starts(start, end):
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        train_end = m - timedelta(days=embargo_days)
        train_start = BURN_IN_START if window_days is None else max(BURN_IN_START, train_end - timedelta(days=window_days))
        out.append(Fold(f"{m:%Y-%m}", train_start, train_end, m, nxt))
    return out


def inner_folds(outer: Fold, n: int = 3, embargo_days: int = EMBARGO_DAYS) -> list[Fold]:
    """Nested folds for hyperparameter selection: the last n months inside the outer fold's training data."""
    last = date(outer.train_end.year, outer.train_end.month, 1)
    months = _month_starts(date(last.year - 1, last.month, 1), last)[-n:]
    return [Fold(f"{outer.name}/inner-{m:%Y-%m}", outer.train_start, m - timedelta(days=embargo_days), m,
                 min(date(m.year + (m.month == 12), m.month % 12 + 1, 1), outer.train_end)) for m in months]


def holdout_fold() -> Fold:
    """The single final test (M7). Raises unless the holdout is explicitly unlocked."""
    guard(HOLDOUT_START)
    return Fold("holdout", BURN_IN_START, HOLDOUT_START - timedelta(days=EMBARGO_DAYS), HOLDOUT_START, HOLDOUT_END)


def iter_folds(**kw) -> Iterator[Fold]:
    yield from folds(**kw)
