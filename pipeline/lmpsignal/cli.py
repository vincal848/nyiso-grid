"""`uv run lmp <command>` — LMP signal pipeline."""
from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main():
    """LMP forecasting signal: panel, cross-validation, models, reports."""


@app.command("panel")
def panel_cmd(through: str = typer.Option(None, help="Also add feature-only rows for delivery days up to YYYY-MM-DD "
                                                       "(live forecasting)")):
    """Build the point-in-time modeling panel and prove no feature uses post-issue data."""
    import time

    import duckdb

    from lmpsignal import panel
    from lmpsignal.config import FEATURES_DB

    t = time.time()
    from datetime import date

    n = panel.build(through=date.fromisoformat(through) if through else None)
    con = duckdb.connect(str(FEATURES_DB), read_only=True)
    leaks = panel.check_asof(con)
    typer.echo(f"panel: {n:,} rows in {time.time() - t:.1f}s")
    for col, bad in leaks.items():
        typer.echo(f"  {col:<22} rows after issue time: {bad}")
    if any(leaks.values()):
        raise typer.Exit(1)


@app.command()
def baselines():
    """Run the naive benchmarks over all 36 validation folds."""
    from lmpsignal import panel, runner
    from lmpsignal.config import VALIDATION_END
    from lmpsignal.models.naive import BASELINES, Naive

    p = panel.load(end=VALIDATION_END)          # validation never loads holdout rows
    ref = Naive(runner.REFERENCE)
    for rule in BASELINES:
        rid = runner.run(Naive(rule), p, reference=ref, verbose=False)
        typer.echo(f"{rule:<16} -> {rid}")


MODELS = {
    "lear": lambda: __import__("lmpsignal.models.lear", fromlist=["LEAR"]).LEAR(),
    "lear2": lambda: __import__("lmpsignal.models.lear", fromlist=["LEAR2"]).LEAR2(),
    "struct_cong": lambda: __import__("lmpsignal.structural.congestion", fromlist=["StructuralCongestion"]).StructuralCongestion(),
    "struct_cong_l2": lambda: __import__("lmpsignal.structural.congestion", fromlist=["StructuralCongestion"]).StructuralCongestion(
        blend_loss="l2", name="struct_cong_l2"),
    "struct_cong_out": lambda: __import__("lmpsignal.structural.congestion", fromlist=["StructuralCongestion"]).StructuralCongestion(
        outage_map=True, name="struct_cong_out"),
    "zero_congestion": lambda: __import__("lmpsignal.models.naive", fromlist=["ZeroCongestion"]).ZeroCongestion(),
    "gbm_l1": lambda: __import__("lmpsignal.models.gbm", fromlist=["GBM"]).GBM(objective="l1"),
    "gbm_l2": lambda: __import__("lmpsignal.models.gbm", fromlist=["GBM"]).GBM(objective="l2"),
    "gbm_l1_v3": lambda: __import__("lmpsignal.models.gbm", fromlist=["GBM"]).GBM(objective="l1", feature_set="v3"),
    "lear_wx": lambda: __import__("lmpsignal.models.lear", fromlist=["LEAR"]).LEAR(inputs="loadfix_hrrr"),
    # M6 (declared in docs/ROADMAP.md): needs the optional `deep` extra
    "ddnn": lambda: __import__("lmpsignal.models.ddnn", fromlist=["DDNN"]).DDNN(),
    "ddnn_v3": lambda: __import__("lmpsignal.models.ddnn", fromlist=["DDNN"]).DDNN(feature_set="v3"),
}


@app.command()
def train(
    model: str = typer.Argument(..., help=f"One of: {', '.join(MODELS)}"),
    smoke: int = typer.Option(0, help="Run only the first N folds WITHOUT logging (not a trial)"),
):
    """Run a model over the validation folds with out-of-sample residual quantiles."""
    import time

    from lmpsignal import cv, panel, runner
    from lmpsignal.config import VALIDATION_END
    from lmpsignal.models.naive import Naive

    t = time.time()
    p = panel.load(end=VALIDATION_END)          # validation never loads holdout rows
    folds = cv.folds()[:smoke] if smoke else None
    m = MODELS[model]()
    q = "model" if getattr(m, "distributional", False) else "oos_residual"     # DDNN keeps its own distribution
    rid = runner.run(m, p, folds=folds, reference=Naive(runner.REFERENCE), quantiles=q, log=not smoke)
    typer.echo(f"{model} -> {rid or '(smoke test, not logged)'} in {time.time() - t:.0f}s")


@app.command()
def loadfix(
    kind: str = typer.Argument(..., help="lin (classical per-zone ridge), gbm (LightGBM) or gbm_cal (ablation: no weather)"),
    smoke: int = typer.Option(0, help="Run only the first N folds WITHOUT logging (not a trial)"),
    oos: bool = typer.Option(False, help="Write month-by-month out-of-sample forecasts to load_fix_oos (panel feature)"),
):
    """Weather-to-load correction of the ISOLF D-2 forecast, scored on the validation folds."""
    import time

    from lmpsignal import cv, panel
    from lmpsignal import loadfix as lf
    from lmpsignal.config import VALIDATION_END

    t = time.time()
    p = panel.load(end=VALIDATION_END)
    if oos:
        rid = lf.build_oos(kind, p)
        typer.echo(f"load_fix_oos <- {rid} in {time.time() - t:.0f}s; rebuild the panel (lmp panel) to join it")
        return
    rid = lf.run(kind, p, folds=cv.folds()[:smoke] if smoke else None, log=not smoke)
    typer.echo(f"loadfix_{kind} -> {rid or '(smoke test, not logged)'} in {time.time() - t:.0f}s")


from lmpsignal.presets import FROZEN_BASES, POST_PRESETS, SIGNAL_V1  # noqa: E402


@app.command()
def post(name: str = typer.Argument(..., help=f"Preset: {', '.join(POST_PRESETS)}")):
    """Post-process stored OOS predictions (clip / combine / calibrate) -- seconds, no refits. Logged as a trial."""
    import time

    from lmpsignal import panel, postprocess
    from lmpsignal.config import VALIDATION_END
    from lmpsignal.diagnostics import completed_runs

    t = time.time()
    models, steps = POST_PRESETS[name]
    runs = completed_runs(models)
    missing = [m for m in models if m not in runs]
    if missing:
        raise typer.BadParameter(f"no completed run for {missing}")
    p = panel.load(end=VALIDATION_END) if any(s["op"] == "clip" for s in steps) else None
    steps = [dict(s, components={k: runs[v] for k, v in s["components"].items()}) if s["op"] == "assemble"
             else dict(s, base=runs[s["base"]], spike=runs[s["spike"]]) if s["op"] == "spike_mix" else s
             for s in steps]
    rid, weights = postprocess.run(name, [runs[m] for m in models], steps, panel=p)
    typer.echo(f"{name} -> {rid} in {time.time() - t:.0f}s (parents: {', '.join(runs[m] for m in models)})")
    if len(weights):
        typer.echo(weights.groupby(["market", "component"]).mean(numeric_only=True).round(3).to_string())




@app.command()
def m7(candidate: str = typer.Argument(..., help="The frozen signal v1 (a model or post preset name)")):
    """M7: the single holdout evaluation of the frozen signal v1. Requires LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7.

    Base models are refit monthly over the holdout exactly as in validation (logged as <model>_m7); the frozen
    post-processing chain then runs over validation + holdout so calibration continues without a break (logged as
    <preset>_m7); naive benchmarks are run on the holdout too. Only holdout months are scored in the summary."""
    import json
    import time

    from lmpsignal import cv, panel, postprocess, registry, runner
    from lmpsignal.config import HOLDOUT_END, HOLDOUT_START, holdout_unlocked
    from lmpsignal.diagnostics import completed_runs
    from lmpsignal.models.naive import Naive

    if not holdout_unlocked():
        raise typer.BadParameter("holdout is locked: set LMP_UNLOCK_HOLDOUT=I_AM_RUNNING_M7 for the single M7 run")
    t = time.time()
    p = panel.load(end=HOLDOUT_END)
    val_folds, hold_folds = cv.folds(), cv.folds(start=HOLDOUT_START, end=HOLDOUT_END)
    ref = Naive(runner.REFERENCE)
    resolved: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in resolved:
            return resolved[name]
        if name in POST_PRESETS:
            parents, steps = POST_PRESETS[name]
            specs = {m: resolve(m) for m in parents}
            steps = [dict(s, components={k: specs[v] for k, v in s["components"].items()}) if s["op"] == "assemble"
                     else s for s in steps]
            rid, _ = postprocess.run(name + "_m7", [specs[m] for m in parents], steps, panel=p,
                                     folds=val_folds + hold_folds)
        else:
            val = completed_runs([name])[name]
            model = (FROZEN_BASES.get(name) or MODELS[name])()
            model.name = name + "_m7"
            rid = val + "+" + runner.run(model, p, folds=hold_folds, reference=ref, quantiles="oos_residual")
        typer.echo(f"  {name} -> {rid}  ({time.time() - t:.0f}s)")
        resolved[name] = rid
        return rid

    final = resolve(candidate)
    for rule in ("persist_da_d1", "lago_naive", "zero_congestion"):
        bench = MODELS[rule]() if rule in MODELS else Naive(rule)
        bench.name = rule + "_m7"
        resolved[rule] = runner.run(bench, p, folds=hold_folds, reference=ref, verbose=False)
    (registry.EXPERIMENTS_DIR / "m7_lineage.json").write_text(json.dumps({"candidate": candidate, **resolved}, indent=1))
    typer.echo(f"M7 {candidate} -> {final}; benchmarks {resolved['persist_da_d1']}, {resolved['lago_naive']} "
               f"in {time.time() - t:.0f}s")


@app.command()
def spike(variant: str = typer.Argument("full", help="full | no_storm (declared M3b variants)"),
          smoke: int = typer.Option(0, help="Run only the first N folds WITHOUT logging (not a trial)")):
    """M3b RT spike member over the validation folds (budget: 3 full runs, see docs/ROADMAP.md)."""
    import time

    from lmpsignal import cv, panel
    from lmpsignal import spike as sp
    from lmpsignal.config import VALIDATION_END

    t = time.time()
    p = panel.load(end=VALIDATION_END)
    rid = sp.run(variant, p, folds=cv.folds()[:smoke] if smoke else None, log=not smoke)
    typer.echo(f"spike_{variant} -> {rid or '(smoke test, not logged)'} in {time.time() - t:.0f}s")


@app.command()
def forecast(day: str = typer.Option(None, "--date", help="Delivery day YYYY-MM-DD (default: tomorrow, local)")):
    """Live forecast of the frozen signal for one delivery day -> experiments.duckdb live_forecasts."""
    import time
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from lmpsignal import live

    t = time.time()
    d = date.fromisoformat(day) if day else datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    out = live.forecast(d)
    tot = out[(out["component"] == "total")].groupby("market")["mean"].mean()
    typer.echo(f"forecast {d}: {len(out):,} rows; mean total DA {tot.get('da', float('nan')):.2f}, "
               f"RT {tot.get('rt', float('nan')):.2f} $/MWh  ({time.time() - t:.0f}s)")


@app.command()
def nodes(day: str = typer.Option(None, "--date", help="Delivery day for the live node forecast (default: tomorrow)"),
          evaluate: bool = typer.Option(False, help="Score the node mapping once on the validation folds (signal v1)")):
    """Node-level forecasts from the signal's zone forecasts (energy + mapped loss and congestion)."""
    import time
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    from lmpsignal import nodes as nd

    t = time.time()
    if evaluate:
        from lmpsignal.config import EXPERIMENTS_DIR

        runs = __import__("lmpsignal.diagnostics", fromlist=["completed_runs"]).completed_runs([SIGNAL_V1])
        res = nd.evaluate(runs[SIGNAL_V1])
        out = EXPERIMENTS_DIR / "nodes_v1_validation.csv"
        res.to_csv(out, index=False)
        typer.echo(res.round(3).to_string(index=False))
        typer.echo(f"-> {out} ({time.time() - t:.0f}s)")
        return
    d = date.fromisoformat(day) if day else datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)
    out = nd.live(d, SIGNAL_V1)
    typer.echo(f"nodes {d}: {out['ptid'].nunique()} nodes, {len(out):,} rows ({time.time() - t:.0f}s)")


def _day(day: str | None):
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    return date.fromisoformat(day) if day else datetime.now(ZoneInfo("America/New_York")).date() + timedelta(days=1)


@app.command()
def risk(day: str = typer.Option(None, "--date", help="Delivery day (default: tomorrow)")):
    """Live RT spike risk (M3b spike member, not part of signal v1) -> experiments.duckdb live_spike."""
    import time

    from lmpsignal import live

    t, d = time.time(), _day(day)
    out = live.spike_forecast(d)
    top = out.groupby("zone")["p_spike"].max().sort_values(ascending=False)
    typer.echo(f"risk {d}: max P(spike) " + ", ".join(f"{z} {v:.2f}" for z, v in top.head(4).items())
               + f"  ({time.time() - t:.0f}s)")


@app.command()
def shadow(day: str = typer.Option(None, "--date", help="Delivery day (default: tomorrow)"),
           score: bool = typer.Option(False, help="Print the live record vs signal v1 instead of forecasting")):
    """M8 live shadow member (Chronos-2, zero-shot) -> live_shadow; never feeds the signal. Needs the `deep` extra."""
    import time

    from lmpsignal import shadow as sh

    if score:
        s = sh.score()
        typer.echo("no settled shadow forecasts yet" if s.empty else s.round(3).to_string(index=False))
        return
    t, d = time.time(), _day(day)
    out = sh.forecast(d)
    m = out.groupby("market")["mean"].mean()
    typer.echo(f"shadow {d}: {len(out):,} rows; mean total DA {m.get('da', float('nan')):.2f}, RT {m.get('rt', float('nan')):.2f} "
               f"({time.time() - t:.0f}s)")


@app.command()
def positions(day: str = typer.Option(None, "--date", help="Delivery day (default: tomorrow)")):
    """DART v2 paper positions for one delivery day (needs `lmp forecast` and `lmp risk`) -> live_dart."""
    from lmpsignal import dart as dt

    d = _day(day)
    out = dt.live_v2(d)
    by = out.groupby("zone")["x_mw"].sum().round(1)
    typer.echo(f"positions {d}: {(out['x_mw'] != 0).sum()} zone-hours, net MWh (+ INC / - DEC) by zone: "
               + ", ".join(f"{z} {v:+.1f}" for z, v in by.items()))


@app.command()
def paper():
    """Paper-trading track record of the live DART v2 positions (settled days only)."""
    from lmpsignal import dart as dt

    g = dt.paper()
    if g.empty:
        typer.echo("no settled paper positions yet")
        return
    typer.echo(g.round(2).to_string(index=False))
    typer.echo(f"total {g['pnl'].sum():,.2f} $ over {len(g)} days, {g['mwh'].sum():,.1f} MWh "
               f"({g['pnl'].sum() / g['mwh'].sum():.2f} $/MWh)" if g["mwh"].sum() else "")


@app.command()
def dart(rule: str = typer.Option("v1", help="v1 (prototype) or v2 (M4: distribution means, spike mix, DA/RT correlation)")):
    """DART prototype: backtest zonal virtual positions from the signal on validation and (if run) the M7 holdout."""
    from pathlib import Path

    from lmpsignal import dart as dt
    from lmpsignal.diagnostics import completed_runs

    if rule == "v2":
        runs = completed_runs([SIGNAL_V1, "spike_full"])
        res = dt.backtest_v2(runs[SIGNAL_V1], runs["spike_full"])
        out = Path(__file__).resolve().parents[2] / "docs" / "experiments" / "dart_v2.md"
        lines = ["# DART v2 backtest (validation only)", "",
                 "_Generated by `lmp dart --rule v2`; rule declared in docs/ROADMAP.md (M4)._", "", dt.md(res), ""]
        out.write_text("\n".join(lines), encoding="utf-8")
        typer.echo(res.round(3).to_string(index=False))
        typer.echo(f"-> {out}")
        return

    val = completed_runs([SIGNAL_V1])[SIGNAL_V1]
    hold = dt.lineage_holdout(SIGNAL_V1)
    summary, by_zone = dt.backtest(val, hold)
    out = Path(__file__).resolve().parents[2] / "docs" / "experiments" / "dart_prototype.md"
    dt.write_report(summary, by_zone, out)
    typer.echo(summary.round(3).to_string(index=False))
    typer.echo(f"-> {out}")


@app.command()
def m5(models: str = typer.Argument(..., help="Comma-separated declared M5 models (m5_persist, m5_lastyear, m5_norm, "
                                               "m5_anchor, m5_decay)"),
       window: str = typer.Option("validation", help="validation | holdout (the declared single check, after adoption)")):
    """M5 monthly DA products (horizons 1-6), one registry run per model. Budget: see docs/ROADMAP.md (M5 declaration)."""
    from lmpsignal import monthly

    names = models.split(",")
    cache = monthly.compute()
    for m in names:
        monthly.run(m, window, cache=cache)


@app.command()
def monthly(day: str = typer.Option(None, "--date", help="Issue on or before this date (default: today)")):
    """Live monthly forecasts (latest vintage, six target months) with the M5 choice per component -> live_monthly."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    from lmpsignal import monthly as mo
    from lmpsignal.presets import M5_CHOICE

    d = date.fromisoformat(day) if day else datetime.now(ZoneInfo("America/New_York")).date()
    out = mo.live(d, M5_CHOICE)
    s = out[out["period"] == "peak"].groupby(["component", "month"])["mean"].mean().unstack(0).round(2)
    typer.echo(f"monthly vintage {out['cutoff'].iloc[0]} ({M5_CHOICE}); on-peak means over internal zones:")
    typer.echo(s.to_string())


@app.command()
def graphs(model: str = typer.Option("struct_cong_l2", help="Structural model whose latest run's artifacts to compile")):
    """Compile structural-model artifacts into data/structure.duckdb (shift-factor, co-binding and drift graphs)."""
    from lmpsignal import graphs as g
    from lmpsignal.diagnostics import completed_runs

    rid = completed_runs([model]).get(model)
    if not rid:
        raise typer.BadParameter(f"no completed run for {model}")
    for name, n in g.build(rid).items():
        typer.echo(f"  {name:<20} {n:>10,}")
    typer.echo(f"wrote {g.STRUCTURE_DB} from {rid}")


@app.command("panel-diff")
def panel_diff(run_a: str, run_b: str):
    """Which panel columns differ between the panels two runs received (runs from 2026-10-05 on)."""
    from lmpsignal import registry

    d = registry.panel_diff(run_a, run_b)
    typer.echo("identical panels" if d.empty else d.to_string(index=False))


@app.command()
def report(models: str = typer.Option(None, help="Comma-separated model names (default: all with done runs)")):
    """Pooled validation scoreboard + Diebold-Mariano tests; writes docs/experiments/scoreboard.md."""
    from lmpsignal.report import write_scoreboard

    path = write_scoreboard(models.split(",") if models else None)
    typer.echo(f"wrote {path}")


@app.command()
def docs():
    """Write docs/FEATURES.md from the panel feature documentation."""
    from lmpsignal.report import write_feature_docs, write_structure_docs

    typer.echo(f"wrote {write_feature_docs()}")
    typer.echo(f"wrote {write_structure_docs()}")


if __name__ == "__main__":
    app()
