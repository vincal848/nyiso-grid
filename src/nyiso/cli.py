"""Command-line entry point: `uv run nyiso <command>`."""
from __future__ import annotations

import typer

from nyiso.config import DEFAULT_START

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main():
    """NYISO historical data warehouse + dashboard."""


@app.command()
def backfill(
    datasets: str = typer.Option(None, help="Comma-separated dataset keys (default: all)"),
    start: str = typer.Option(DEFAULT_START, help="First month, YYYY-MM"),
    end: str = typer.Option(None, help="Last month, YYYY-MM (default: current month)"),
    workers: int = typer.Option(4, help="Parallel (dataset, month) tasks"),
    rebuild: bool = typer.Option(False, help="Re-parse months that already have Parquet"),
):
    """Download NYISO MIS history and write curated Parquet."""
    from nyiso.store.backfill import backfill as run
    from nyiso.store.backfill import default_end

    keys = datasets.split(",") if datasets else None
    results = run(keys, start, end or default_end(), workers=workers, rebuild=rebuild)
    done = [r for r in results if not r.skipped and not r.error]
    errs = [r for r in results if r.error]
    typer.echo(f"wrote {len(done)} partitions ({sum(r.rows for r in done):,} rows), "
               f"skipped {sum(r.skipped for r in results)}, errors {len(errs)}")
    for r in errs:
        typer.echo(f"  ERROR {r.key} {r.year}-{r.month:02d}: {r.error}")


@app.command("external")
def external_cmd(
    sources: str = typer.Option(None, help="Comma-separated: gas_henry_hub,weather_obs,weather_fcst,weather_hrrr,outage_schedule (default: all)"),
    start: str = typer.Option(DEFAULT_START, help="First month, YYYY-MM"),
):
    """Fetch non-MIS sources (EIA gas, NOAA weather, Open-Meteo forecasts) into curated Parquet."""
    from nyiso.store.external import run

    for key, (rows, parts) in run(sources.split(",") if sources else None, start).items():
        typer.echo(f"{key:<16} {rows:>10,} rows  {parts} partitions")


@app.command("reference")
def reference_cmd(refresh: bool = typer.Option(False, help="Re-download MIS reference files")):
    """Build nodes table and approximate zone polygons."""
    import json

    from nyiso.store.catalog import build_reference

    typer.echo(json.dumps(build_reference(refresh), indent=2))


@app.command()
def build():
    """Create DuckDB views over curated Parquet and (re)build aggregate tables."""
    import time

    from nyiso.store.catalog import build as run
    from nyiso.store.catalog import connect
    from nyiso.store.docs import apply_comments, undocumented

    t = time.time()
    con = connect()
    run(con)
    apply_comments(con)
    for problem in undocumented(con):
        typer.echo(f"  WARNING undocumented: {problem}  (add it to src/nyiso/dictionary.py)")
    for (name,) in con.execute("SELECT table_name FROM duckdb_tables() ORDER BY 1").fetchall():
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        typer.echo(f"  {name:<24} {n:>12,}")
    typer.echo(f"built in {time.time() - t:.1f}s")


@app.command()
def validate(threshold: float = typer.Option(0.99, help="Flag days below this coverage")):
    """Coverage/gap report per dataset; writes data/coverage.parquet."""
    from nyiso.store.catalog import validate as run

    cov, dups = run()
    typer.echo(f"{'dataset':<22}{'days':>6}{'first':>12}{'last':>12}{'coverage':>10}{'bad days':>10}{'dup keys':>10}")
    for key, g in cov.groupby("dataset"):
        bad = g[g["coverage"] < threshold]
        typer.echo(f"{key:<22}{len(g):>6}{str(g['day'].min())[:10]:>12}{str(g['day'].max())[:10]:>12}"
                   f"{g['coverage'].mean():>10.4f}{len(bad):>10}{dups.get(key, 0):>10}")
    from nyiso.store.catalog import connect

    flagged = connect(read_only=True).execute("""
        SELECT CAST(ts_local AS DATE) AS day, count(DISTINCT ts_utc) AS hours
        FROM lbmp_zone_hourly WHERE rt_flag IS NOT NULL GROUP BY 1 ORDER BY 1""").fetchall()
    if flagged:
        typer.echo("\nFlagged RT hours (integrated vs time-weighted 5-min mismatch; accepted, see rt_flag):")
        for day, hours in flagged:
            typer.echo(f"  {day}  {hours} h")
    bad = cov[cov["coverage"] < threshold]
    if len(bad):
        typer.echo("\nDays below threshold (first 40):")
        typer.echo(bad.head(40).to_string(index=False))


@app.command()
def docs():
    """Regenerate docs/DATA.md and docs/data_dictionary.json (dictionary + live stats)."""
    from nyiso.store.catalog import connect
    from nyiso.store.docs import write_docs

    for path in write_docs(connect(read_only=True)):
        typer.echo(f"wrote {path}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """Run the dashboard."""
    import uvicorn

    uvicorn.run("nyiso.api.app:app", host=host, port=port)


if __name__ == "__main__":
    app()
