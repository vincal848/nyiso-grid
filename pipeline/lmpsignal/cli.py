"""`uv run lmp <command>` — LMP signal pipeline."""
from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main():
    """LMP forecasting signal: panel, cross-validation, models, reports."""


@app.command("panel")
def panel_cmd():
    """Build the point-in-time modeling panel and prove no feature uses post-issue data."""
    import time

    import duckdb

    from lmpsignal import panel
    from lmpsignal.config import FEATURES_DB

    t = time.time()
    n = panel.build()
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
    rid = runner.run(MODELS[model](), p, folds=folds, reference=Naive(runner.REFERENCE),
                     quantiles="oos_residual", log=not smoke)
    typer.echo(f"{model} -> {rid or '(smoke test, not logged)'} in {time.time() - t:.0f}s")


@app.command()
def loadfix(
    kind: str = typer.Argument(..., help="lin (classical per-zone ridge), gbm (LightGBM) or gbm_cal (ablation: no weather)"),
    smoke: int = typer.Option(0, help="Run only the first N folds WITHOUT logging (not a trial)"),
):
    """Weather-to-load correction of the ISOLF D-2 forecast, scored on the validation folds."""
    import time

    from lmpsignal import cv, loadfix as lf, panel
    from lmpsignal.config import VALIDATION_END

    t = time.time()
    p = panel.load(end=VALIDATION_END)
    rid = lf.run(kind, p, folds=cv.folds()[:smoke] if smoke else None, log=not smoke)
    typer.echo(f"loadfix_{kind} -> {rid or '(smoke test, not logged)'} in {time.time() - t:.0f}s")


POST_PRESETS = {
    # name: (parent model names, steps)
    "lear_clip": (["lear"], [{"op": "clip"}, {"op": "calibrate", "method": "oos_residual"}]),
    "lear_clip_aci": (["lear"], [{"op": "clip"}, {"op": "calibrate", "method": "aci"}]),
    "gbm_l1_aci": (["gbm_l1"], [{"op": "calibrate", "method": "aci"}]),
    "combo_eq_aci": (["lear", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                          {"op": "calibrate", "method": "aci"}]),
    "combo_inv_aci": (["lear", "gbm_l1"], [{"op": "combine", "weights": "inv_mae"}, {"op": "clip"},
                                           {"op": "calibrate", "method": "aci"}]),
    "lear2_aci": (["lear2"], [{"op": "calibrate", "method": "aci"}]),
    "combo2_eq_aci": (["lear2", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                            {"op": "calibrate", "method": "aci"}]),
    "combo2_inv_aci": (["lear2", "gbm_l1"], [{"op": "combine", "weights": "inv_mae"}, {"op": "clip"},
                                             {"op": "calibrate", "method": "aci"}]),
    # M2.5 follow-ups
    "combo3_eq_aci": (["lear_clip", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                                {"op": "calibrate", "method": "aci"}]),
    "lear2_long_aci": (["lear2"], [{"op": "windows", "use": ["w364", "w728", "wall"]},
                                   {"op": "calibrate", "method": "aci"}]),
    "assemble_v1e_v2c_aci": (["lear_clip", "lear2"], [{"op": "assemble", "components": {
        "energy": "lear_clip", "loss": "lear_clip", "congestion": "lear2"}}, {"op": "calibrate", "method": "aci"}]),
}


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
    steps = [dict(s, components={k: runs[v] for k, v in s["components"].items()}) if s["op"] == "assemble" else s
             for s in steps]
    rid, weights = postprocess.run(name, [runs[m] for m in models], steps, panel=p)
    typer.echo(f"{name} -> {rid} in {time.time() - t:.0f}s (parents: {', '.join(runs[m] for m in models)})")
    if len(weights):
        typer.echo(weights.groupby(["market", "component"]).mean(numeric_only=True).round(3).to_string())


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
