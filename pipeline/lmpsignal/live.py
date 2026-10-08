"""Daily live forecast of the frozen signal (`lmp forecast`).

For delivery day D (issued 05:00 ET on D-1), exactly as validated:
  1. Base models (presets.FROZEN_BASES) are trained with the validation rule for D's month: all data from the burn-in
     start up to 7 days before the first of the month (so they refit once a month, like the 36 folds). Their raw
     forecasts for D are kept in data/experiments/live/<base>/date=YYYY-MM-DD.parquet.
  2. The frozen post-processing chain (presets.POST_PRESETS) is applied in memory over each base's history:
     validation run + M7 holdout continuation (data/experiments/m7_lineage.json) + earlier live days, whose
     outcomes are filled from the panel once known. Calibration therefore continues without a break.
     For speed the chain sees the last HISTORY_DAYS of history; ACI's miscoverage state adapts within ~100 days
     (gamma 0.01), so this changes intervals negligibly.
  3. Day D's rows go to experiments.duckdb `live_forecasts` (replacing any earlier forecast for D); the panel rows
     the forecast used are kept in data/experiments/live/panel/date=YYYY-MM-DD.parquet.
The panel must contain D's feature rows: `lmp panel --through D` (scripts/daily.py runs the whole sequence).
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from lmpsignal import cv, panel, postprocess, registry
from lmpsignal.config import BURN_IN_START, EMBARGO_DAYS, EXPERIMENTS_DIR, ISSUE_HOUR_ET
from lmpsignal.evaluate import QCOLS
from lmpsignal.presets import FROZEN_BASES, POST_PRESETS, SIGNAL_V1

LIVE_DIR = EXPERIMENTS_DIR / "live"
HISTORY_DAYS = 460
KEYS = postprocess.KEYS
SCHEMA = f"""CREATE TABLE IF NOT EXISTS live_forecasts (
    signal VARCHAR, issue_utc TIMESTAMPTZ, delivery_date DATE, ts_utc TIMESTAMPTZ, zone VARCHAR, hour_local INTEGER,
    market VARCHAR, component VARCHAR, mean DOUBLE, {", ".join(f"{q} DOUBLE" for q in QCOLS)},
    git_commit VARCHAR, created_utc TIMESTAMPTZ)"""


def month_fold(d: date) -> cv.Fold:
    m = d.replace(day=1)
    nxt = (m + timedelta(days=32)).replace(day=1)
    return cv.Fold(f"{m:%Y-%m}", BURN_IN_START, m - timedelta(days=EMBARGO_DAYS), m, nxt)


def _folds(first: date, d: date) -> list[cv.Fold]:
    out, m = [], first.replace(day=1)
    while m <= d:
        out.append(month_fold(m))
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def issue_utc(d: date) -> pd.Timestamp:
    return (pd.Timestamp(d - timedelta(days=1)) + pd.Timedelta(hours=ISSUE_HOUR_ET)).tz_localize("America/New_York").tz_convert("UTC")


def _outcomes(p: pd.DataFrame) -> pd.DataFrame:
    """Long table of known outcomes: KEYS + y + scored."""
    rows = []
    for m in ("da", "rt"):
        for c in ("total", "energy", "loss", "congestion"):
            rows.append(p[["delivery_date", "ts_utc", "zone", "hour_local"]].assign(
                market=m, component=c, y=p[f"{m}_{c}"].to_numpy(), scored=p[f"score_{m}"].to_numpy()))
    return pd.concat(rows, ignore_index=True)


def base_forecast(name: str, p: pd.DataFrame, d: date) -> pd.DataFrame:
    f = month_fold(d)
    model = FROZEN_BASES[name]()
    if hasattr(model, "prepare"):
        model.prepare(p)
    train = p[(p["delivery_date"] >= pd.Timestamp(f.train_start)) & (p["delivery_date"] < pd.Timestamp(f.train_end))]
    test = p[p["delivery_date"] == pd.Timestamp(d)]
    if test.empty:
        raise ValueError(f"panel has no rows for {d}: run `lmp panel --through {d}` first")
    pred = model.fit(train).predict(test)
    out = pred[KEYS + ["mean"]].copy()
    path = LIVE_DIR / name / f"date={d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


def _history(name: str, lineage: dict, outcomes: pd.DataFrame, since: pd.Timestamp) -> pd.DataFrame:
    hist = postprocess.load_run(lineage[name])
    hist = hist[hist["delivery_date"] >= since]
    files = sorted((LIVE_DIR / name).glob("date=*.parquet"))
    if files:
        live = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        live["delivery_date"] = pd.to_datetime(live["delivery_date"])
        live = live[live["delivery_date"] > hist["delivery_date"].max()]
        live = live.merge(outcomes, on=KEYS, how="left").assign(ref_mean=float("nan"))
        live["scored"] = live["scored"].fillna(False).astype(bool)
        hist = pd.concat([hist, live[hist.columns]], ignore_index=True)
    return hist


def forecast(d: date, signal: str = SIGNAL_V1) -> pd.DataFrame:
    lineage = json.loads((EXPERIMENTS_DIR / "m7_lineage.json").read_text())
    p = panel.load(end=d + timedelta(days=1))
    outcomes = _outcomes(p)
    since = pd.Timestamp(d) - pd.Timedelta(days=HISTORY_DAYS)
    folds = _folds(since.date(), d)
    cache: dict[str, pd.DataFrame] = {}

    def resolve(name: str) -> pd.DataFrame:
        if name in cache:
            return cache[name]
        if name in POST_PRESETS:
            parents, steps = POST_PRESETS[name]
            loaded = {m: resolve(m) for m in parents}
            steps = [dict(s, components=dict(s["components"])) if s["op"] == "assemble" else s for s in steps]
            df, _ = postprocess.apply(loaded, steps, p, folds)
        else:
            base_forecast(name, p, d)
            df = _history(name, lineage, outcomes, since)
        cache[name] = df
        return df

    final = resolve(signal)
    # audit trail: the exact panel rows (features as of issue) behind this day's forecast
    rows = p[p["delivery_date"] == pd.Timestamp(d)]
    (LIVE_DIR / "panel").mkdir(parents=True, exist_ok=True)
    rows.to_parquet(LIVE_DIR / "panel" / f"date={d}.parquet", index=False)
    out = final[final["delivery_date"] == pd.Timestamp(d)][KEYS + ["mean", *QCOLS]].copy()
    out.insert(0, "issue_utc", issue_utc(d))
    out.insert(0, "signal", signal)
    out["git_commit"] = registry.git_commit()
    out["created_utc"] = datetime.now(UTC)
    out["delivery_date"] = out["delivery_date"].dt.date
    with registry.connect() as con:
        con.execute(SCHEMA)
        con.execute("DELETE FROM live_forecasts WHERE signal = ? AND delivery_date = ?", [signal, d])
        con.register("o", out)
        con.execute(f"INSERT INTO live_forecasts SELECT signal, issue_utc, delivery_date, ts_utc, zone, hour_local, market, "
                    f"component, mean, {', '.join(QCOLS)}, git_commit, created_utc FROM o")
    return out


# ----------------------------------------------------------------------------- RT spike risk (M3b member, live)

SPIKE_SCHEMA = f"""CREATE TABLE IF NOT EXISTS live_spike (
    model VARCHAR, issue_utc TIMESTAMPTZ, delivery_date DATE, ts_utc TIMESTAMPTZ, zone VARCHAR, hour_local INTEGER,
    p_spike DOUBLE, thr DOUBLE, mean DOUBLE, {", ".join(f"{q} DOUBLE" for q in QCOLS)},
    git_commit VARCHAR, created_utc TIMESTAMPTZ)"""


def spike_forecast(d: date) -> pd.DataFrame:
    """M3b spike member (`spike_full`) for delivery day D, trained with the validation rule for D's month. Not part of
    signal v1 (M3b/M4 did not adopt it): a separate risk output and the RT spike input of DART v2."""
    import warnings

    from lmpsignal import spike

    warnings.filterwarnings("ignore")                              # sklearn penalty deprecation, as in spike.run
    p = panel.load(end=d + timedelta(days=1))
    if p[p["delivery_date"] == pd.Timestamp(d)].empty:
        raise ValueError(f"panel has no rows for {d}: run `lmp panel --through {d}` first")
    f = month_fold(d)
    tr, te, thr = spike.fold_data(spike.frame(p), f)
    member = spike.SpikeMember("full").fit(tr, thr)
    o = member.predict(te[te["delivery_date"] == pd.Timestamp(d)])
    out = o[["delivery_date", "ts_utc", "zone", "hour_local", "p_spike", "thr", "mean", *QCOLS]].copy()
    out.insert(0, "issue_utc", issue_utc(d))
    out.insert(0, "model", member.name)
    out["git_commit"] = registry.git_commit()
    out["created_utc"] = datetime.now(UTC)
    out["delivery_date"] = out["delivery_date"].dt.date
    path = LIVE_DIR / member.name / f"date={d}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    with registry.connect() as con:
        con.execute(SPIKE_SCHEMA)
        con.execute("DELETE FROM live_spike WHERE model = ? AND delivery_date = ?", [member.name, d])
        con.register("o", out)
        con.execute(f"INSERT INTO live_spike SELECT model, issue_utc, delivery_date, ts_utc, zone, hour_local, p_spike, thr, "
                    f"mean, {', '.join(QCOLS)}, git_commit, created_utc FROM o")
    return out
