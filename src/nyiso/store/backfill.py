"""Backfill: for each (dataset, month) download -> parse -> dedupe -> write Parquet.

Each (dataset, month) is an independent task, so the job is resumable and
parallelizes across processes.
"""
from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

import pandas as pd
from tqdm import tqdm

from nyiso.datasets import BACKFILL_ORDER, DATASETS
from nyiso.ingest.mis_client import iter_month_files, may_be_incomplete
from nyiso.ingest.parse import compact_snapshots, dedupe, parse_csv
from nyiso.store.writer import partition_path, write_month

log = logging.getLogger(__name__)


@dataclass
class TaskResult:
    key: str
    year: int
    month: int
    rows: int = 0
    days: int = 0
    skipped: bool = False
    error: str | None = None


def months_between(start: str, end: str) -> list[tuple[int, int]]:
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def run_task(key: str, year: int, month: int, rebuild: bool = False) -> TaskResult:
    ds = DATASETS[key]
    res = TaskResult(key, year, month)
    part = partition_path(key, year, month)
    if part.exists() and not rebuild and not may_be_incomplete(part, year, month):
        res.skipped = True
        return res
    try:
        frames = []
        for day, content in iter_month_files(ds, year, month):
            df = parse_csv(content, ds, file_date=day)
            if not df.empty:
                frames.append(df)
                res.days += 1
        if not frames:
            return res
        df = dedupe(pd.concat(frames, ignore_index=True), ds)
        if ds.snapshot_keys:
            df = compact_snapshots(df, ds)
        write_month(df, key, year, month)
        res.rows = len(df)
    except Exception as e:  # noqa: BLE001 — report and keep the backfill going
        res.error = f"{type(e).__name__}: {e}"
    return res


def backfill(keys: list[str] | None, start: str, end: str, workers: int = 4,
             rebuild: bool = False) -> list[TaskResult]:
    keys = [k for k in BACKFILL_ORDER if keys is None or k in keys]
    months = months_between(start, end)
    tasks = [(k, y, m) for k in keys for (y, m) in months]
    results: list[TaskResult] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(run_task, k, y, m, rebuild): (k, y, m) for k, y, m in tasks}
        with tqdm(total=len(futs), unit="task") as bar:
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                bar.set_postfix_str(f"{r.key} {r.year}-{r.month:02d}")
                bar.update()
                if r.error:
                    tqdm.write(f"ERROR {r.key} {r.year}-{r.month:02d}: {r.error}")
    return results


def default_end() -> str:
    t = date.today()
    return f"{t.year}-{t.month:02d}"
