"""Graph store: the network structure estimated by the structural congestion model, fold by fold.

Built from a structural run's artifacts into data/structure.duckdb (rebuildable; `lmp graphs`):

  constraint_catalog   fold, market, rank, key, sum_abs_shadow, bind_rate, window_start, window_end
  zone_shift_factors   fold, market, zone, key, a        zone congestion sensitivity to constraint key's shadow price
  node_shift_factors   fold, market, ptid, key, a        same for generator nodes (bipartite node-constraint graph)
  node_fit             fold, market, ptid, r2_in_window  how much of the node's congestion the top-K explain
  cobinding            fold, market, key_a, key_b, hours_both, jaccard   constraint co-binding graph (training window)
  drift                fold, market, catalog_jaccard, keys_added, keys_dropped, zone_sf_rel_change,
                       node_sf_rel_change, node_subspace_angle_deg   month-over-month structural change
  node_meta            ptid, name, zone, lat, lon (from the warehouse `nodes` table)

Drift measures compare each fold with the previous one over the constraints both catalogs share:
relative Frobenius change of the shift-factor matrix, and the largest principal angle between the
top-8 singular subspaces of the node shift-factor matrices (0 deg = same structure). Large values flag
topology or rating changes (new lines, retirements) worth refitting around.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from nyiso.config import DATA, DB_PATH
from lmpsignal import registry
from lmpsignal.structural import constraints as cs

STRUCTURE_DB = DATA / "structure.duckdb"


def _matrix(df: pd.DataFrame, row: str, keys: list[str]) -> pd.DataFrame:
    return df.pivot_table(index=row, columns="key", values="a").reindex(columns=keys)


def _angle(A: np.ndarray, B: np.ndarray, k: int = 8) -> float:
    ua = np.linalg.svd(A, full_matrices=False)[0][:, :k]
    ub = np.linalg.svd(B, full_matrices=False)[0][:, :k]
    s = np.linalg.svd(ua.T @ ub, compute_uv=False)
    return float(np.degrees(np.arccos(np.clip(s.min(), -1, 1))))


def build(run_id: str) -> dict[str, int]:
    cat = registry.artifact(run_id, "constraint_catalog")
    zsf = registry.artifact(run_id, "zone_shift_factors")
    nsf = registry.artifact(run_id, "node_shift_factors")
    nfit = registry.artifact(run_id, "node_fit")

    # co-binding graph per fold/market over the fold's training window
    sp = cs.shadow_prices(str(pd.Timestamp(cat["window_start"].min()).date()),
                          str((pd.Timestamp(cat["window_end"].max()) + pd.Timedelta(days=1)).date()))
    cob = []
    for (fold, m), c in cat.groupby(["fold", "market"]):
        keys = c.sort_values("rank")["key"].tolist()
        s = sp[(sp["market"] == m) & sp["key"].isin(keys) & (sp["d"] >= c["window_start"].iloc[0])
               & (sp["d"] <= c["window_end"].iloc[0])]
        B = pd.crosstab([s["d"], s["hr"]], s["key"]).reindex(columns=keys, fill_value=0).clip(upper=1).to_numpy()
        both = B.T @ B
        n = np.diag(both)
        ii, jj = np.triu_indices(len(keys), 1)
        union = n[ii] + n[jj] - both[ii, jj]
        e = pd.DataFrame({"fold": fold, "market": m, "key_a": np.array(keys)[ii], "key_b": np.array(keys)[jj],
                          "hours_both": both[ii, jj], "jaccard": np.where(union > 0, both[ii, jj] / np.maximum(union, 1), 0)})
        cob.append(e[e["hours_both"] >= 24])

    # month-over-month drift
    drift = []
    for m in ("da", "rt"):
        folds = sorted(cat.loc[cat["market"] == m, "fold"].unique())
        for prev, cur in zip(folds, folds[1:]):
            kp = set(cat[(cat.fold == prev) & (cat.market == m)]["key"])
            kc = set(cat[(cat.fold == cur) & (cat.market == m)]["key"])
            common = sorted(kp & kc)
            zp = _matrix(zsf[(zsf.fold == prev) & (zsf.market == m)], "zone", common)
            zc = _matrix(zsf[(zsf.fold == cur) & (zsf.market == m)], "zone", common).reindex(zp.index)
            npv = _matrix(nsf[(nsf.fold == prev) & (nsf.market == m)], "ptid", common)
            ncv = _matrix(nsf[(nsf.fold == cur) & (nsf.market == m)], "ptid", common)
            nodes = npv.index.intersection(ncv.index)
            A, B = npv.loc[nodes].fillna(0).to_numpy(), ncv.loc[nodes].fillna(0).to_numpy()
            drift.append({"fold": cur, "market": m, "catalog_jaccard": len(common) / max(len(kp | kc), 1),
                          "keys_added": len(kc - kp), "keys_dropped": len(kp - kc),
                          "zone_sf_rel_change": float(np.linalg.norm(zc.fillna(0) - zp.fillna(0)) / max(np.linalg.norm(zp.fillna(0)), 1e-9)),
                          "node_sf_rel_change": float(np.linalg.norm(B - A) / max(np.linalg.norm(A), 1e-9)),
                          "node_subspace_angle_deg": _angle(A, B) if min(A.shape) >= 8 else float("nan")})

    wh = duckdb.connect(str(DB_PATH), read_only=True)
    meta = wh.execute("SELECT ptid, name, zone, lat, lon FROM nodes").df()
    wh.close()

    con = duckdb.connect(str(STRUCTURE_DB))
    tables = {"constraint_catalog": cat, "zone_shift_factors": zsf, "node_shift_factors": nsf, "node_fit": nfit,
              "cobinding": pd.concat(cob, ignore_index=True), "drift": pd.DataFrame(drift), "node_meta": meta}
    for name, df in tables.items():
        con.register("t", df)
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM t")
        con.unregister("t")
    con.execute("CREATE OR REPLACE TABLE source AS SELECT ? AS run_id, now() AS built_utc", [run_id])
    out = {k: len(v) for k, v in tables.items()}
    con.close()
    return out
