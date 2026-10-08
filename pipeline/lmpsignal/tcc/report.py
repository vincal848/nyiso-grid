"""Results page for M9 (docs/experiments/tcc_pricer.md), built from the three logged runs' stored observation tables."""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal.config import EXPERIMENTS_DIR
from lmpsignal.diagnostics import completed_runs
from lmpsignal.loaders import tcc_df
from lmpsignal.overfit import holm
from lmpsignal.report import _md
from lmpsignal.tcc import evaluate as ev
from lmpsignal.tcc.run import BASELINES, CANDIDATES

ALPHA = 0.05


def _load() -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    runs = completed_runs(list(CANDIDATES))
    missing = set(CANDIDATES) - set(runs)
    if missing:
        raise ValueError(f"runs missing: {sorted(missing)}")
    obs = {}
    for name, rid in runs.items():
        d = pd.read_parquet(EXPERIMENTS_DIR / rid / "obs.parquet")
        obs[name] = d[d["illiquid"]] if name.endswith("illiquid") else d
    return obs, runs


def coverage() -> str:
    r = tcc_df("""SELECT kind, count(*) AS rounds, min(posted_date) AS first_posted, max(posted_date) AS last_posted
                  FROM tcc_rounds GROUP BY kind ORDER BY kind""")
    r[["first_posted", "last_posted"]] = r[["first_posted", "last_posted"]].astype(str).apply(lambda c: c.str[:10])
    n = tcc_df("""SELECT (SELECT count(*) FROM tcc_nodal_prices) AS nodal_price_rows,
                         (SELECT count(DISTINCT poi) FROM tcc_nodal_prices) AS pois,
                         (SELECT count(*) FROM tcc_awards) AS award_lines,
                         (SELECT count(DISTINCT round_id) FROM tcc_awards) AS rounds_with_awards""").iloc[0]
    return "\n".join([_md(r.astype({"rounds": int})), "",
                      f"{int(n.nodal_price_rows):,} nodal price rows over {int(n.pois)} POIs; {int(n.award_lines):,} award lines "
                      f"in {int(n.rounds_with_awards)} rounds (all rounds with a published result since 2014 were fetched; "
                      "the 3 fixed-price allocation rounds clear at fixed prices and are skipped)."])


def _universe(obs: pd.DataFrame) -> pd.DataFrame:
    g = obs.groupby("kind").agg(auction_periods=("auction", "nunique"), path_periods=("path", "size"),
                                with_payoff=("y", lambda s: int(s.notna().sum())))
    g["with_all_baselines"] = obs.dropna(subset=["y", "persistence", "climatology"]).groupby("kind").size()
    return g.reset_index().fillna(0).astype({"with_all_baselines": int})


def _accuracy(d: pd.DataFrame, f: str, final: bool) -> pd.DataFrame:
    """MAE / RMSE per MW-month of each forecast against the realized payoff on the rows where all exist."""
    cols = [*BASELINES, f]
    z = d[d["final"] == final].dropna(subset=["y", *cols])
    m = z["months"]
    rows = []
    for c in cols:
        e = (z["y"] - z[c]) / m
        rows.append({"forecast": {"c": "market (clearing price)"}.get(c, c), "n": len(z), "MAE": e.abs().mean(),
                     "RMSE": float(np.sqrt((e ** 2).mean())), "bias (y - f)": e.mean()})
    return pd.DataFrame(rows)


def _stat_row(label: str, s: dict) -> dict:
    pp, pa = s["pnl_path_boot"], s["pnl_auction_boot"]
    return {"set": label, "n": s["n"], "auctions": s["n_auctions"], "trades": pp["n_trades"], "P&L / MW-month": pp["mean"],
            "95% CI paths": f"[{pp['lo']:.2f}, {pp['hi']:.2f}]", "95% CI auctions": f"[{pa['lo']:.2f}, {pa['hi']:.2f}]",
            "p paths": pp["p"], "p auctions": pa["p"], "slope": s["slope"]["slope"], "slope t": s["slope"]["t"],
            "permutation p": s["placebo"]["p"], "shuffled P&L": s["placebo"]["null_mean"]}


def _posthoc(d: pd.DataFrame, f: str) -> list[dict]:
    """The buy rule driven by the candidate, by persistence, by climatology, and buying everything, on the same rows."""
    rows = []
    cols = [f, "persistence", "climatology"]
    d = d.dropna(subset=["y", *cols]).reset_index(drop=True)
    for label, sub in (("development", d[~d["final"]]), ("final test", d[d["final"]])):
        if sub.empty:
            continue
        sub = sub.reset_index(drop=True)
        s_all, o, cost = ev.edge(sub, f)
        pnl_by = {c: ev.trade_pnl(*ev.edge(sub, c)) for c in cols}
        pnl_by["buy everything"] = o - cost
        for name, pnl in pnl_by.items():
            t = pnl[np.isfinite(pnl)]
            top = np.sort(t)[::-1][: max(1, len(t) // 100)].sum() / t.sum() if t.sum() > 0 else np.nan
            perm = ev.permutation_null(sub, name, B=300) if name in cols else None
            rows.append({"set": label, "rule driven by": name, "rows": len(sub), "trades": len(t), "mean P&L": t.mean(),
                         "median P&L": float(np.median(t)), "hit rate": float((t > 0).mean()), "top 1% of trades / total": top,
                         "shuffled mean P&L": perm["null_mean"] if perm else np.nan,
                         "permutation p": perm["p"] if perm else np.nan})
        diff = np.nan_to_num(pnl_by[f]) - np.nan_to_num(pnl_by["persistence"])    # not traded = 0 on both sides
        for by in ("path", "auction"):
            b = ev.bootstrap_mean_pnl(diff, sub[by].to_numpy())
            rows.append({"set": label, "rule driven by": f"{f} minus persistence, per row, resampling {by}s", "rows": len(sub),
                         "trades": np.nan, "mean P&L": b["mean"], "median P&L": np.nan, "hit rate": np.nan,
                         "top 1% of trades / total": np.nan, "shuffled mean P&L": np.nan, "permutation p": b["p"]})
    return rows


READING = """## How to read this

- The declared P&L test asks whether the buy rule earns more than zero. In 2022-2025 the auctions' average clearing price was
  *below* the average realized payoff (see the market-bias table), so buying paths **without any model** also earns
  money: the "shuffled P&L" column is that, and it is positive. The declared test is therefore passed by a pricer with no
  skill. The permutation p (shuffled edge vs the real edge) and the post-hoc table below separate skill from that bias.
- The post-hoc table was added after the declared results above were read. It is descriptive and not part of the verdict
  rule: it runs the same buy rule with the simple baselines and with no model at all. A pricer that cannot beat the
  persistence-driven rule has not shown that its structure adds anything.
- Mean P&L is heavy-tailed (the top 1% of trades supply most of the total in the development set; the median trade earns far
  less than the mean), so a few paths and auctions decide it. Auction-level intervals are the wider and more honest ones.
- Squared error: the market price is the most accurate point forecast of the realized payoff in most comparisons; the
  pricers' gap to the price carries some information (positive slope below one) but the pricers alone are not better
  forecasts than the price.
"""


def build() -> str:
    obs, runs = _load()
    out = ["# M9 TCC pricer: results", "",
           "_Generated by `lmp tcc-report`; declaration, assumptions and verdict rule in docs/ROADMAP.md (M9)._", "",
           "Runs: " + ", ".join(f"`{r}`" for r in runs.values()) + ".", "",
           "## Data coverage (TCC ingest)", "", coverage(), "",
           "## Evaluation universe", "",
           "Awarded paths of auction periods with a full 365-day window before the cutoff (posted - 7 days) that end by "
           "2025-09-30; the holdout stays locked. Final test set = auctions posted 2025-01-01 or later.", "",
           _md(_universe(obs["tcc_struct_trailing"])), ""]
    primary, tests = {}, {}
    for name, f in CANDIDATES.items():
        d = obs[name]
        dev, fin = d[~d["final"]], d[d["final"]]
        sd = ev.summarize(dev, f, BASELINES)
        sf = ev.summarize(fin, f, BASELINES) if fin[f].notna().any() else None
        primary[name] = max(sd["pnl_path_boot"]["p"], sd["pnl_auction_boot"]["p"])
        tests[name] = (sd, sf)
    adj = holm(pd.Series(primary))
    out += ["## Buy-when-undervalued rule (long 1 MW when forecast - price exceeds the assumed cost)", "",
            "Cost = 2% of |price| + $0.50 per MW-month (assumption). P&L = realized payoff - price - cost, $ per MW-month "
            "per trade. Bootstrap p: one-sided, share of resamples with mean <= 0, resampling whole paths / whole auctions. "
            "Permutation p: the pricer's edge shuffled across the paths of each auction.", ""]
    rows = []
    for name in CANDIDATES:
        sd, sf = tests[name]
        rows.append({"candidate": name, **_stat_row("development", sd)})
        if sf:
            rows.append({"candidate": name, **_stat_row("final test", sf)})
    out += [_md(pd.DataFrame(rows)), ""]
    out += ["### Development-set primary p-values and the verdict rule", "",
            _md(pd.DataFrame({"candidate": list(primary), "primary p (max of bootstrap p)": list(primary.values()),
                              "Holm-adjusted": adj.reindex(list(primary)).to_numpy()})), ""]
    verdict = []
    for name in CANDIDATES:
        sd, sf = tests[name]
        dev_ok = adj[name] < ALPHA and sd["pnl_path_boot"]["mean"] > 0
        fin_ok = bool(sf) and sf["pnl_auction_boot"]["mean"] > 0 and sf["pnl_auction_boot"]["p"] < ALPHA
        verdict.append({"candidate": name, "development passes": dev_ok, "final test passes": fin_ok,
                        "edge": dev_ok and fin_ok})
    out += [_md(pd.DataFrame(verdict).astype(str)), "",
            "`edge` is the declared rule's outcome. Read it with the sections 'Post-hoc' and 'How to read this': the declared "
            "P&L test is also passed by buying without a model, and the persistence baseline earns what the structural "
            "candidates earn under the same rule.", ""]
    out += ["## Forecast accuracy against the realized payoff ($ per MW-month, rows where every forecast exists)", ""]
    for name, f in CANDIDATES.items():
        for final in (False, True):
            a = _accuracy(obs[name], f, final)
            if len(a) and a["n"].iloc[0]:
                out += [f"**{name}**, {'final test' if final else 'development'} set", "", _md(a), ""]
    out += ["## Diebold-Mariano: squared error of the candidate vs each baseline (per MW-month, HAC over auctions)", ""]
    rows = []
    for name in CANDIDATES:
        for label, s in zip(("development", "final test"), tests[name], strict=True):
            for b, r in (s["dm"].items() if s else []):
                rows.append({"candidate": name, "set": label, "baseline": b, "auctions": r["n_days"],
                             "mean loss diff": r["mean_diff"], "DM": r["dm_stat"], "p (candidate better)": r["p_a_better"]})
    out += [_md(pd.DataFrame(rows)), ""]
    out += ["## Post-hoc: the same buy rule driven by the baselines, and buying everything (not part of the verdict)", ""]
    ph = []
    for name, f in CANDIDATES.items():
        ph += [{"candidate": name, **r} for r in _posthoc(obs[name], f)]
    out += [_md(pd.DataFrame(ph).astype({"trades": "Int64"})), ""]
    out += ["## Cost sensitivity (development set, mean P&L per trade, $ per MW-month)", ""]
    rows = []
    for name, f in CANDIDATES.items():
        d = obs[name]
        d = d[~d["final"]]
        for fee in (0.0, ev.FEE_REL, 0.05):
            s = ev.summarize(d, f, (), B=1000, fee_rel=fee)
            rows.append({"candidate": name, "fee (share of |price|)": fee, "trades": s["pnl_path_boot"]["n_trades"],
                         "P&L / MW-month": s["pnl_path_boot"]["mean"], "p paths": s["pnl_path_boot"]["p"],
                         "p auctions": s["pnl_auction_boot"]["p"]})
    out += [_md(pd.DataFrame(rows)), ""]
    d = obs["tcc_struct_trailing"]
    d = d[d["y"].notna()]
    mb = ((d["y"] - d["c"]) / d["months"]).groupby(d["kind"]).agg(["mean", "median", "size"])
    out += ["## Market bias: realized payoff minus clearing price, $ per MW-month, by auction kind (descriptive)", "",
            _md(mb.reset_index().rename(columns={"mean": "mean (y - c)", "median": "median (y - c)", "size": "n"})
                .astype({"n": int})), ""]
    return "\n".join(out)
