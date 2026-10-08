"""Outage-to-constraint mapping for the structural congestion model (M3).

Source: da_sched_outages (MIS P-54C), the outage list NYISO uses in each day's DAM, with planned return
dates. As-of rule: the list for market day X is posted ~09:40 ET on X-1, so at the 05:00 ET D-1 issue the
latest list is the one for D-1 (posted on D-2). An outage on that list is *expected out* in hour h of D if
its scheduled window [sched_out, sched_in) covers h. Outages that start on D and are not on the D-1 list are
invisible here (known gap: the forward schedule, P-14B, is published without an archive).

Two mappings from equipment to constraints:
 1. Name match (static, nothing fitted). Equipment and constraint names share NYISO's 8-character station
    codes, e.g. outage ASTORIAE-CORONA___138_34183 and constraint ASTANNEX 138 ASTORIAE 138 1. Facility and
    contingency matches are kept apart: an outage next to the monitored facility tends to load it, while an
    outage of the contingency element removes that contingency. Interface derates (SCH-NE-NYISO_LIMIT_800)
    match interface constraints (SCH - NE - NY) on the external area code.
 2. Learned lift, fit on the fold's training days only: for each (constraint, equipment) pair with enough
    support, the shrunk log ratio of the constraint's daily binding rate on days the equipment was expected
    out to its overall binding rate.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from nyiso.config import TZ
from lmpsignal.structural import constraints as cs

_SCH_SKIP = {"NYISO", "NY", "LIMIT", ""}
_CTG_PREFIX = re.compile(r"^[A-Z]{2,4}:\s*")


def _norm(tok: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", tok.upper())[:8]


def _sch_token(body: str) -> set[str]:
    """External area code of an interface name ('NE - NY', 'PJM-NYISO_LIMIT_1700') -> {'SCH:NE'}."""
    parts = [p.strip() for p in re.split(r"[-_]", body.upper())]
    ext = [p for p in parts if p not in _SCH_SKIP and not p.isdigit()]
    return {f"SCH:{ext[0][:2]}"} if ext else set()


def _line_or_station(s: str) -> set[str]:
    """NYISO fixed-width names: 'AAAAAAAA-BBBBBBBB_kV_id' is a line between two stations; otherwise the
    first 8 characters are the station."""
    if len(s) > 8 and s[8] == "-":
        return {_norm(s[:8]), _norm(s[9:17])} - {""}
    return {_norm(s[:8])} - {""}


def equipment_tokens(equipment: str) -> set[str]:
    s = equipment.upper()
    if s.startswith("SCH-"):
        return _sch_token(s[4:])
    return _line_or_station(s)


def constraint_tokens(key: str) -> tuple[set[str], set[str]]:
    """(facility tokens, contingency tokens) for a constraint key 'facility | contingency'."""
    facility, _, contingency = (p.strip().upper() for p in key.partition(" | "))
    if facility.startswith("SCH"):
        fac = _sch_token(facility[3:])
    else:
        fac = {_norm(t) for t in facility.split() if re.search(r"[A-Z]", t)} - {""}
    ctg: set[str] = set()
    if contingency and contingency != "BASE CASE":
        body = _CTG_PREFIX.sub("", contingency)
        if len(body) > 8 and body[8] == "-":
            ctg = _line_or_station(body)
        else:
            first = re.split(r"[\s(#&_]", body, maxsplit=1)[0]
            ctg = {_norm(first)} - {""}
    return fac, ctg


def load_lists(start, end) -> pd.DataFrame:
    """DAM outage lists for market days [start, end): list_day (local date), equipment, out/in (UTC)."""
    con = cs._con()
    df = con.execute("""SELECT CAST(ts_local AS DATE) AS list_day, equipment, sched_out_utc, sched_in_utc
                        FROM da_sched_outages WHERE ts_local >= ? AND ts_local < ?""",
                     [str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date())]).df()
    con.close()
    df["list_day"] = pd.to_datetime(df["list_day"])
    return df


def hour_starts_utc(days: pd.DatetimeIndex) -> np.ndarray:
    """(n_days, 24) UTC start of each local hour (fall-back: first occurrence; spring-forward: shifted)."""
    local = (days.values[:, None] + np.arange(24) * np.timedelta64(1, "h")).reshape(-1)
    utc = (pd.DatetimeIndex(local).tz_localize(TZ, ambiguous=np.ones(len(local), dtype=bool),
                                               nonexistent="shift_forward").tz_convert("UTC"))
    return utc.as_unit("ns").asi8.reshape(len(days), 24)


class OutageMap:
    def __init__(self, lists: pd.DataFrame, shrink: float = 20.0, min_days: int = 10, max_share: float = 0.9):
        self.lists = lists
        self.shrink, self.min_days, self.max_share = shrink, min_days, max_share
        self.equipment = np.array(sorted(lists["equipment"].unique()))
        self.eq_index = pd.Series(np.arange(len(self.equipment)), index=self.equipment)
        self.eq_tokens = [equipment_tokens(e) for e in self.equipment]

    def expected_out(self, days: pd.DatetimeIndex) -> np.ndarray:
        """(n_days, 24, n_equipment) bool: on the D-1 list and scheduled out during the hour of D."""
        out = np.zeros((len(days), 24, len(self.equipment)), dtype=bool)
        di = pd.Series(np.arange(len(days)), index=days - pd.Timedelta(days=1))
        rows = self.lists[self.lists["list_day"].isin(di.index)]
        if rows.empty:
            return out
        d = di[rows["list_day"]].to_numpy()
        h0 = hour_starts_utc(days)[d]                                     # (rows, 24)
        o = rows["sched_out_utc"].dt.tz_convert("UTC").dt.as_unit("ns").astype("int64").to_numpy()[:, None]
        i = rows["sched_in_utc"].dt.tz_convert("UTC").dt.as_unit("ns").astype("int64").to_numpy()[:, None]
        hit = (o < h0 + 3_600_000_000_000) & (i > h0)
        r, h = np.nonzero(hit)
        out[d[r], h, self.eq_index[rows["equipment"].to_numpy()[r]].to_numpy()] = True
        return out

    def name_match(self, keys: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """(K, n_equipment) facility-match and contingency-match indicators."""
        Mf = np.zeros((len(keys), len(self.equipment)), dtype=np.float32)
        Mc = np.zeros_like(Mf)
        for k, key in enumerate(keys):
            fac, ctg = constraint_tokens(key)
            for e, toks in enumerate(self.eq_tokens):
                Mf[k, e] = bool(toks & fac)
                Mc[k, e] = bool(toks & ctg)
        return Mf, Mc

    def fit_lift(self, keys: list[str], days: pd.DatetimeIndex, bind_daily: np.ndarray) -> pd.DataFrame:
        """Shrunk log-lift of daily binding given 'expected out', on training days only.
        bind_daily: (n_days, K) bool. Returns rows (key, equipment, n_out_days, bind_out_days, base_rate, lift)."""
        E = self.expected_out(days).any(axis=1).astype(float)              # (days, eq)
        B = bind_daily.astype(float)
        n_days = len(days)
        n_e = E.sum(axis=0)
        support = (n_e >= self.min_days) & (n_e <= self.max_share * n_days)
        p = np.clip(B.mean(axis=0), 1.0 / n_days, 1 - 1.0 / n_days)       # (K,)
        b = B.T @ E[:, support]                                           # (K, eq_s)
        n = n_e[support][None, :]
        lift = np.log((b + self.shrink * p[:, None]) / (n + self.shrink)) - np.log(p[:, None])
        K, S = lift.shape
        return pd.DataFrame({"key": np.repeat(keys, S), "equipment": np.tile(self.equipment[support], K),
                             "n_out_days": np.tile(n_e[support], K), "bind_out_days": b.reshape(-1),
                             "base_rate": np.repeat(p, S), "lift": lift.reshape(-1)})

    def features(self, keys: list[str], days: pd.DatetimeIndex, lift: pd.DataFrame | None) -> dict[str, np.ndarray]:
        """Per (day, hour, constraint): counts of name-matched outages expected out (facility, contingency)
        and the largest positive / most negative learned lift among equipment expected out."""
        O = self.expected_out(days).reshape(len(days) * 24, -1).astype(np.float32)
        Mf, Mc = self.name_match(keys)
        K = len(keys)
        feats = {"out_fac": O @ Mf.T, "out_ctg": O @ Mc.T,
                 "lift_max": np.zeros((O.shape[0], K)), "lift_min": np.zeros((O.shape[0], K))}
        if lift is not None and len(lift):
            ki = {k: i for i, k in enumerate(keys)}
            for key, g in lift.groupby("key", sort=False):
                if key not in ki:
                    continue
                cols = self.eq_index[g["equipment"]].to_numpy()
                v = O[:, cols] * g["lift"].to_numpy()[None, :]
                feats["lift_max"][:, ki[key]] = v.max(axis=1).clip(min=0)
                feats["lift_min"][:, ki[key]] = v.min(axis=1).clip(max=0)
        return {k: v.reshape(len(days), 24, K) for k, v in feats.items()}
