"""Experiment registry: every run's config, per-fold scores, and predictions (for DM tests / ensembles).

data/experiments.duckdb
  runs(run_id, model, config_json, config_hash, panel_rows, created_utc, status)
  scores(run_id, fold, market, component, zone, metric, value)
data/experiments/<run_id>/fold=<YYYY-MM>.parquet   predictions, long format
data/experiments/<run_id>/artifacts/<name>/fold=<YYYY-MM>.parquet   model internals per fold (e.g. shift
    factors, constraint catalog, per-constraint forecasts), so nothing a model computes is thrown away
data/experiments/panel_snapshots/<panel_hash>.parquet (+ .columns.json)   the exact panel a run received (runs from
    2026-10-05 on), stored once per distinct content; runs.panel_hash points to it, `lmp panel-diff` compares runs
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import duckdb
import pandas as pd

from lmpsignal.config import EXPERIMENTS_DB, EXPERIMENTS_DIR, FEATURES_DB

# The checkout this code runs from. NYISO_ROOT may point the data at another checkout (a worktree sharing a warehouse),
# so fingerprints and the git commit must not follow it.
CODE_ROOT = Path(__file__).resolve().parents[2]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (run_id VARCHAR PRIMARY KEY, model VARCHAR, config_json VARCHAR,
    config_hash VARCHAR, panel_rows BIGINT, created_utc TIMESTAMPTZ, status VARCHAR);
CREATE TABLE IF NOT EXISTS scores (run_id VARCHAR, fold VARCHAR, market VARCHAR, component VARCHAR,
    zone VARCHAR, metric VARCHAR, value DOUBLE);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS code_fingerprint VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS git_commit VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS data_fingerprint VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS data_summary VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS environment VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS finished_utc TIMESTAMPTZ;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS duration_s DOUBLE;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS error VARCHAR;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS panel_hash VARCHAR;
"""
SNAPSHOT_DIR = EXPERIMENTS_DIR / "panel_snapshots"


def code_fingerprint() -> str:
    """sha256 over every .py/.sql file of the warehouse and pipeline code (path + content).

    Platform-independent: POSIX relative paths in POSIX sort order, CRLF normalized to LF, so a commit
    hashes the same on Windows and in CI. Runs logged before 2026-10-02 used OS-native paths (Windows
    backslashes); their fingerprints are not comparable with later ones."""
    h = hashlib.sha256()
    files = sorted((f.relative_to(CODE_ROOT).as_posix(), f)
                   for base in (CODE_ROOT / "src" / "nyiso", CODE_ROOT / "pipeline" / "lmpsignal")
                   for f in base.rglob("*")
                   if f.suffix in (".py", ".sql") and "__pycache__" not in f.parts)
    for rel, f in files:
        h.update(rel.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def git_commit() -> str | None:
    """HEAD commit (+ '-dirty' if the tree has changes), or None if there are no commits yet."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=CODE_ROOT, capture_output=True, text=True)
        if head.returncode != 0:
            return None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=CODE_ROOT, capture_output=True, text=True).stdout.strip()
        return head.stdout.strip() + ("-dirty" if dirty else "")
    except OSError:
        return None


def data_fingerprint() -> tuple[str, str]:
    """Fingerprint of the modeling panel: row count, date span and checksums of targets and key inputs."""
    con = duckdb.connect(str(FEATURES_DB), read_only=True)
    row = con.execute("""SELECT count(*), min(delivery_date), max(delivery_date), max(issue_utc),
                                round(sum(da_total), 2), round(sum(rt_total), 2),
                                round(sum(load_fcst_nyiso), 0), round(sum(temp_fcst_nyiso), 2), round(sum(gas_hh), 2)
                         FROM panel""").fetchone()
    con.close()
    summary = json.dumps(dict(zip(["rows", "first_day", "last_day", "last_issue", "sum_da", "sum_rt", "sum_load_fcst",
                                   "sum_temp_fcst", "sum_gas"], [str(v) for v in row])))
    return hashlib.sha256(summary.encode()).hexdigest()[:16], summary


def environment() -> str:
    pkgs = {}
    for name in ("pandas", "numpy", "duckdb", "pyarrow", "lightgbm", "scikit-learn"):
        try:
            pkgs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return json.dumps({"python": platform.python_version(), "platform": platform.platform(), **pkgs})


def connect(read_only: bool = False, retries: int = 60) -> duckdb.DuckDBPyConnection:
    """Open the registry. DuckDB allows one writing process at a time; runs and post-processing jobs
    may overlap, so a lock conflict is retried with backoff instead of crashing the run."""
    import random
    import time

    for attempt in range(retries):
        try:
            con = duckdb.connect(str(EXPERIMENTS_DB), read_only=read_only)
            break
        except duckdb.IOException as e:
            msg = str(e).lower()
            busy = "lock" in msg or "being used by another process" in msg or "cannot open file" in msg
            if not busy or attempt == retries - 1:
                raise
            time.sleep(min(0.2 * 1.5 ** attempt, 5) + random.random() * 0.2)
    if not read_only:
        con.execute(_SCHEMA)
    return con


def config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:12]


def panel_hashes(p: pd.DataFrame) -> tuple[str, dict[str, str]]:
    """Content hash per column (values in row order) and an overall hash over the sorted (column, hash) pairs."""
    cols = {c: hashlib.sha256(pd.util.hash_pandas_object(p[c], index=False).to_numpy().tobytes()).hexdigest()[:16]
            for c in p.columns}
    return hashlib.sha256(json.dumps(sorted(cols.items())).encode()).hexdigest()[:16], cols


def snapshot_panel(p: pd.DataFrame) -> str:
    """Store the panel a run receives (once per distinct content) and return its hash."""
    h, cols = panel_hashes(p)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{h}.parquet"
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        p.to_parquet(tmp, compression="zstd", index=False)
        tmp.replace(path)
        (SNAPSHOT_DIR / f"{h}.columns.json").write_text(json.dumps({"rows": len(p), "columns": cols}, indent=1))
    return h


def load_snapshot(run_id: str) -> pd.DataFrame:
    """The exact panel a run received (for reproducing it)."""
    with connect(read_only=True) as con:
        r = con.execute("SELECT panel_hash FROM runs WHERE run_id = ?", [run_id]).fetchone()
    if not r or not r[0]:
        raise ValueError(f"{run_id} has no panel snapshot (runs before 2026-10-05, or not panel-based)")
    return pd.read_parquet(SNAPSHOT_DIR / f"{r[0]}.parquet")


def panel_diff(run_a: str, run_b: str) -> pd.DataFrame:
    """Columns whose content differs between the panels two runs received (added / removed / changed)."""
    with connect(read_only=True) as con:
        hs = dict(con.execute("SELECT run_id, panel_hash FROM runs WHERE run_id IN (?, ?)", [run_a, run_b]).fetchall())
    meta = []
    for r in (run_a, run_b):
        if not hs.get(r):
            raise ValueError(f"{r} has no panel snapshot")
        meta.append(json.loads((SNAPSHOT_DIR / f"{hs[r]}.columns.json").read_text()))
    a, b = meta[0]["columns"], meta[1]["columns"]
    rows = [{"column": c, "change": "added" if c not in a else "removed" if c not in b else "changed"}
            for c in sorted(set(a) | set(b)) if a.get(c) != b.get(c)]
    return pd.DataFrame(rows, columns=["column", "change"]).assign(rows_a=meta[0]["rows"], rows_b=meta[1]["rows"])


def start_run(model: str, config: dict, panel_rows: int, panel: pd.DataFrame | None = None) -> str:
    h = config_hash({"model": model, **config})
    run_id = f"{model}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{h[:6]}"
    dfp, dsum = data_fingerprint()
    ph = snapshot_panel(panel) if panel is not None else None
    with connect() as con:
        con.execute("""INSERT INTO runs (run_id, model, config_json, config_hash, panel_rows, created_utc, status,
                                         code_fingerprint, git_commit, data_fingerprint, data_summary, environment,
                                         panel_hash)
                       VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)""",
                    [run_id, model, json.dumps(config, sort_keys=True, default=str), h, panel_rows,
                     datetime.now(UTC), code_fingerprint(), git_commit(), dfp, dsum, environment(), ph])
    (EXPERIMENTS_DIR / run_id).mkdir(parents=True, exist_ok=True)
    return run_id


def save_fold(run_id: str, fold: str, preds: pd.DataFrame, scores: pd.DataFrame) -> None:
    preds.to_parquet(EXPERIMENTS_DIR / run_id / f"fold={fold}.parquet", index=False)
    long = scores.melt(id_vars=["market", "component", "zone"], var_name="metric", value_name="value")
    long.insert(0, "fold", fold)
    long.insert(0, "run_id", run_id)
    with connect() as con:
        con.register("s", long)
        con.execute("INSERT INTO scores SELECT run_id, fold, market, component, zone, metric, value FROM s")


def finish_run(run_id: str, status: str = "done", error: str | None = None) -> None:
    now = datetime.now(UTC)
    with connect() as con:
        con.execute("""UPDATE runs SET status = ?, finished_utc = ?, error = ?,
                              duration_s = epoch(? - created_utc) WHERE run_id = ?""", [status, now, error, now, run_id])


def predictions(run_id: str) -> pd.DataFrame:
    files = sorted((EXPERIMENTS_DIR / run_id).glob("fold=*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def latest_run(model: str) -> str | None:
    with connect(read_only=True) as con:
        r = con.execute("SELECT run_id FROM runs WHERE model = ? AND status = 'done' ORDER BY created_utc DESC LIMIT 1",
                        [model]).fetchone()
    return r[0] if r else None


def log_exploration(model: str, config: dict, note: str) -> str:
    """Record a configuration that was tried informally on validation data (e.g. a diagnostic script) so it
    counts toward the number of trials in the DSR, even though no full run was stored."""
    h = config_hash({"model": model, **config})
    run_id = f"{model}-explore-{datetime.now(UTC):%Y%m%dT%H%M%S}-{h[:6]}"
    with connect() as con:
        con.execute("""INSERT INTO runs (run_id, model, config_json, config_hash, panel_rows, created_utc, status,
                                         code_fingerprint, error)
                       VALUES (?, ?, ?, ?, 0, ?, 'exploratory', ?, ?)""",
                    [run_id, model, json.dumps(config, sort_keys=True, default=str), h, datetime.now(UTC),
                     code_fingerprint(), note])
    return run_id


def save_artifact(run_id: str, fold: str, name: str, df: pd.DataFrame) -> None:
    d = EXPERIMENTS_DIR / run_id / "artifacts" / name
    d.mkdir(parents=True, exist_ok=True)
    df.assign(fold=fold).to_parquet(d / f"fold={fold}.parquet", index=False)


def artifact(run_id: str, name: str) -> pd.DataFrame:
    return pd.read_parquet(EXPERIMENTS_DIR / run_id / "artifacts" / name)
