"""Results page for the DART pricer (docs/experiments/dart_pricer.md): validation folds, DEVELOPMENT ONLY.

Reads the three logged candidate runs, builds the baselines on the same rows (no trade, DART v2, naive last-known spread),
applies the declared tests (block-bootstrap p with Holm, shuffled-outcome null, adoption gate) and writes markdown.
Nothing here is out-of-sample evidence: the holdout is spent and DART v2 was designed after seeing it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from lmpsignal import dart as dart_io
from lmpsignal import dart_forward as fw
from lmpsignal import dart_pricer as dp
from lmpsignal import dart_rules as dr
from lmpsignal.dart_pricer_run import CANDIDATES, LIMITS, load_run, wide_signal
from lmpsignal.diagnostics import completed_runs
from lmpsignal.overfit import holm
from lmpsignal.presets import SIGNAL_V1

N_PERM = 500
ELLIOTT = pd.to_datetime(["2022-12-23", "2022-12-24"])      # Winter Storm Elliott: 76% of DART v2's validation P&L
KEYS = ["delivery_date", "ts_utc", "zone"]
POWER_NS = [60, 120, 250, 365, 730, 1095, 2000, 3000, 4000]


def strategy_frame(runs: dict[str, str]) -> pd.DataFrame:
    """Every strategy on the same rows: x_<name> (effective MW, + INC) and pnl_<name>, plus side / bid_price / x for the null."""
    cands = {n: load_run(runs[n]) for n in CANDIDATES}
    ev = cands["dart_bidcurve"][[*KEYS, "hour_local", "y_da", "y_rt"]].copy()
    for n, c in cands.items():
        m = c[[*KEYS, "x_eff", "pnl", "x_eff_nolimit", "pnl_nolimit", "side", "bid_price", "x", "p_clear", "limit_scale", "rho"]]
        m = m.rename(columns={"x_eff": f"x_{n}", "pnl": f"pnl_{n}", "x_eff_nolimit": f"x_{n}_nolimits",
                              "pnl_nolimit": f"pnl_{n}_nolimits", "side": f"side_{n}", "bid_price": f"bid_{n}",
                              "x": f"mw_{n}", "p_clear": f"pclear_{n}", "limit_scale": f"scale_{n}", "rho": f"rho_{n}"})
        ev = ev.merge(m, on=KEYS)
    base = dart_io.positions_v2(runs[SIGNAL_V1], runs["spike_full"])
    ev = ev.merge(base[[*KEYS, "x_signal_v2", "pnl_signal_v2"]].rename(
        columns={"x_signal_v2": "x_dart_v2", "pnl_signal_v2": "pnl_dart_v2"}), on=KEYS)
    w = wide_signal(runs[SIGNAL_V1])
    nv = w[KEYS].assign(x_naive=dp.naive_last_spread(w))
    ev = ev.merge(nv, on=KEYS).rename(columns={"x_naive": "x_naive_last_spread"})
    spread = ev["y_da"] - ev["y_rt"]
    ev["pnl_naive_last_spread"] = ev["x_naive_last_spread"] * spread - dr.COST * ev["x_naive_last_spread"].abs()
    ev["x_no_trade"], ev["pnl_no_trade"] = 0.0, 0.0
    return ev


def _daily(ev: pd.DataFrame, k: str) -> pd.Series:
    return ev.groupby("delivery_date")[f"pnl_{k}"].sum()


def stats_table(ev: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    rows = []
    for k in names:
        g = ev.assign(**{f"x_{k}": ev[f"x_{k}"].abs()})
        d = _daily(ev, k)
        dx = d.drop(ELLIOTT, errors="ignore")
        s = dr.stats(g, k)
        rows.append({"strategy": k, "days": s["days"], "net_pnl": s["pnl_total"], "per_cleared_mwh": s["pnl_per_mwh"],
                     "mwh_cleared": s["mwh_traded"], "sharpe_ann": s["sharpe_ann"], "max_drawdown": s["max_drawdown"],
                     "ex_2025_06_24": s["pnl_ex_2025_06_24"], "ex_elliott": float(dx.sum()), "mean_day_ex_elliott": float(dx.mean()),
                     "elliott_two_days": float(d.reindex(ELLIOTT).sum()),
                     "p_boot": fw.bootstrap_p(d.to_numpy()) if d.std() > 0 else np.nan,
                     "p_boot_ex_elliott": fw.bootstrap_p(dx.to_numpy()) if dx.std() > 0 else np.nan})
    t = pd.DataFrame(rows)
    c = t["strategy"].isin(CANDIDATES)
    t.loc[c, "holm_p"] = holm(t.loc[c].set_index("strategy")["p_boot"]).to_numpy()
    return t


def null_table(ev: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    rows = []
    for k in names:
        if k in CANDIDATES:
            p = ev[["zone", "hour_local", "y_da", "y_rt"]].assign(side=ev[f"side_{k}"], bid_price=ev[f"bid_{k}"], x=ev[f"mw_{k}"])
        else:
            side = np.sign(ev[f"x_{k}"]).astype(int)
            p = ev[["zone", "hour_local", "y_da", "y_rt"]].assign(side=side, bid_price=-side * np.inf, x=ev[f"x_{k}"].abs())
        p["bid_price"] = p["bid_price"].where(p["side"] != 0)
        real = float(dp.realize(p, p["y_da"].to_numpy(), p["y_rt"].to_numpy())["pnl"].sum())
        nul = dp.shuffled_totals(p, N_PERM, seed=0)
        rows.append({"strategy": k, "real_net_pnl": real, "null_mean": nul.mean(), "null_p95": float(np.quantile(nul, 0.95)),
                     "share_null_ge_real": float((nul >= real).mean()), "above_null_p95": bool(real > np.quantile(nul, 0.95))})
    return pd.DataFrame(rows)


def structure_table(ev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n in CANDIDATES:
        tr = ev[f"mw_{n}"] > 0
        rows.append({"candidate": n, "share_zone_hours_traded": float(tr.mean()),
                     "mean_p_clear_when_traded": float(ev.loc[tr, f"pclear_{n}"].mean()),
                     "share_inc": float((ev.loc[tr, f"side_{n}"] > 0).mean()), "mean_mw_when_traded": float(ev.loc[tr, f"mw_{n}"].mean()),
                     "mean_rho": float(ev[f"rho_{n}"].mean()),
                     "share_days_limits_bind": float((ev.groupby("delivery_date")[f"scale_{n}"].min() < 1).mean()),
                     "net_pnl_cost_of_limits": float(ev[f"pnl_{n}_nolimits"].sum() - ev[f"pnl_{n}"].sum())})
    return pd.DataFrame(rows)


def skill_table(ev: pd.DataFrame) -> pd.DataFrame:
    """Directional skill before costs and clearing: realized DA - RT spread when each strategy is INC (+) or DEC (-)."""
    sp = ev["y_da"] - ev["y_rt"]
    rows = [{"strategy": "dart_v2", "mean_spread_when_inc": float(sp[ev["x_dart_v2"] > 0].mean()),
             "mean_spread_when_dec": float(sp[ev["x_dart_v2"] < 0].mean()), "corr_signed_mw_spread": float(np.corrcoef(ev["x_dart_v2"], sp)[0, 1])}]
    for n in CANDIDATES:
        tr = ev[f"mw_{n}"] > 0
        sgn = ev[f"side_{n}"] * ev[f"mw_{n}"]
        rows.append({"strategy": n, "mean_spread_when_inc": float(sp[tr & (ev[f"side_{n}"] > 0)].mean()),
                     "mean_spread_when_dec": float(sp[tr & (ev[f"side_{n}"] < 0)].mean()),
                     "corr_signed_mw_spread": float(np.corrcoef(sgn, sp)[0, 1])})
    return pd.DataFrame(rows)


def cost_table(ev: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    rows = []
    for k in names:
        x = ev[f"x_{k}"].abs()
        rows.append({"strategy": k, **{f"cost_{c:.2f}": float((ev[f"pnl_{k}"] + (dr.COST - c) * x).sum()) for c in (0.25, 0.5, 1.0)}})
    return pd.DataFrame(rows)


def year_table(ev: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    yr = np.where(ev["delivery_date"] < "2023-10-01", "2022-11..2023-09",
                  np.where(ev["delivery_date"] < "2024-10-01", "2023-10..2024-09", "2024-10..2025-09"))
    return ev.assign(year=yr).groupby("year")[[f"pnl_{k}" for k in names]].sum().rename(columns=lambda c: c[4:]).reset_index()


def gate(stats: pd.DataFrame, null: pd.DataFrame) -> pd.DataFrame:
    """Declared adoption rule for paper trading: positive mean daily net P&L over all days and excluding the two Elliott days,
    and real P&L above the shuffled-outcome null's 95th percentile."""
    s = stats.set_index("strategy").loc[list(CANDIDATES)]
    n = null.set_index("strategy").loc[list(CANDIDATES)]
    g = pd.DataFrame({"mean_day_all_positive": s["net_pnl"] / s["days"] > 0, "mean_day_ex_elliott_positive": s["mean_day_ex_elliott"] > 0,
                      "above_null_p95": n["above_null_p95"]})
    g["adopted_for_paper"] = g.all(axis=1)
    return g.rename_axis("candidate").reset_index()


def _fmt(df: pd.DataFrame) -> str:
    return dr.md(df.round(3))


def build() -> str:
    runs = completed_runs([*CANDIDATES, SIGNAL_V1, "spike_full"])
    ev = strategy_frame(runs)
    names = ["no_trade", "dart_v2", "naive_last_spread", *CANDIDATES]
    st = stats_table(ev, [*names, *(f"{n}_nolimits" for n in CANDIDATES)])
    nl = null_table(ev, names[1:])
    gt = gate(st, nl)
    best = st[st["strategy"].isin(gt.loc[gt["adopted_for_paper"], "candidate"])].sort_values("net_pnl", ascending=False)
    adopted = best["strategy"].iloc[0] if len(best) else None
    pw = fw.power_curve(_daily(ev, adopted or "dart_v2").to_numpy(), POWER_NS)
    d0, n_days = ev["delivery_date"].min(), ev["delivery_date"].nunique()
    out = ["# DART pricer: validation results (DEVELOPMENT ONLY)", "",
           "_Generated by `lmp dart-pricer-report`; declaration, assumptions and rules in docs/ROADMAP.md (DART pricer)._", "",
           "**These numbers are not out-of-sample evidence.** The 2025-10..2026-09 holdout is spent (M7, then DART v1 and v2 were "
           "designed after seeing it), so the 36 validation folds are development data and DART v2 was chosen on them. The only clean "
           "test is the forward live window declared in the ROADMAP.", "",
           "Runs: " + ", ".join(f"`{runs[n]}`" for n in CANDIDATES) + f". Parent signal run `{runs[SIGNAL_V1]}`. Rows: {len(ev):,} "
           f"internal zone-hours over {n_days} delivery days from {d0:%Y-%m-%d} (fold 1, 2022-10, has no stored quantiles for any "
           f"strategy; the first priced fold, 2022-11, has no earlier PIT pairs so every zone uses rho = 0, as DART v2 did). "
           f"Cost ${dp.COST:.2f} per cleared MWh; 1 MW cap per zone-hour; limits ${LIMITS.daily_loss:,.0f} daily stress loss and "
           f"${LIMITS.collateral:,.0f} collateral proxy (candidates only; `_nolimits` rows are the same draws without them).", "",
           "## Net P&L after costs by strategy", "", _fmt(st), "",
           "`p_boot`: one-sided stationary-block-bootstrap p that mean daily net P&L > 0 (10,000 resamples, block 5); `holm_p`: Holm over "
           "the three candidates. `ex_elliott` drops 2022-12-23 and 2022-12-24 (Winter Storm Elliott); `elliott_two_days` is those two "
           "days' P&L.", "",
           "## Null that must fail: realized (DA, RT) pairs shuffled across days within zone and hour "
           f"({N_PERM} permutations, positions fixed)", "", _fmt(nl), "",
           "## Adoption gate for paper trading (declared rule; not a claim of edge)", "", _fmt(gt), "",
           (f"Adopted for paper: **{adopted}**." if adopted else "**No candidate passes the gate: no pricer is adopted; result: no edge yet.**"), "",
           "## What the candidates do", "", _fmt(structure_table(ev)), "",
           "## Directional skill: realized DA - RT spread ($/MWh) when INC and when DEC (a rule with skill is positive, then negative)", "",
           _fmt(skill_table(ev)), "",
           "## Cost sensitivity (total net P&L at the all-in cost per cleared MWh)", "", _fmt(cost_table(ev, names)), "",
           "## By validation year (net P&L)", "", _fmt(year_table(ev, names)), "",
           f"## Power of the forward test on {adopted or 'DART v2'}'s validation daily P&L", "",
           "Power of the one-sided 5% block-bootstrap test of mean daily net P&L > 0, resampling that strategy's validation days "
           "(taken as the truth, which flatters it: the rule was chosen on them).", "", _fmt(pw), "",
           f"First simulated length with power >= 80%: {fw.required_n(pw):.0f} days (NaN = not reached by {POWER_NS[-1]}). The declared "
           "forward score is at 365 counted days, so it is under-powered for an effect this size; \"not shown\" there is not evidence of "
           "no edge.", ""]
    return "\n".join(out)
