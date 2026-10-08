"""M3 outage-to-constraint mapping: name parsing, as-of availability, in-fold lift."""
import numpy as np
import pandas as pd
from lmpsignal.structural.outages import OutageMap, constraint_tokens, equipment_tokens


def test_equipment_and_constraint_names_share_station_codes():
    assert equipment_tokens("ASTORIAE-CORONA___138_34183") == {"ASTORIAE", "CORONA"}
    assert equipment_tokens("DUNWODIE_345KV_7") == {"DUNWODIE"}
    assert equipment_tokens("SCH-NE-NYISO_LIMIT_800") == {"SCH:NE"}
    assert equipment_tokens("SCH-PJM-NYISO_LIMIT_1700") == {"SCH:PJ"}
    assert constraint_tokens("ASTANNEX 138 ASTORIAE 138 1 | SIN: E13THSTA Q35M&BK10&REA2") == (
        {"ASTANNEX", "ASTORIAE"}, {"E13THSTA"})
    assert constraint_tokens("SCRIBA   345 VOLNEY   345 1 | SCRIBA__-VOLNEY___345_21") == (
        {"SCRIBA", "VOLNEY"}, {"SCRIBA", "VOLNEY"})
    assert constraint_tokens("SCH - NE - NY | BASE CASE") == ({"SCH:NE"}, set())
    assert constraint_tokens("GREENWD  138 VERNON   138 1 | SCB:GOWANUS(6): 25&42232")[1] == {"GOWANUS"}


def _utc(s):
    return pd.Timestamp(s, tz="America/New_York").tz_convert("UTC")


def _lists(days, rng):
    rows = []
    for d in days:
        for e in ("ASTORIAE_138KV_1", "VOLNEY___345KV_2", "GOWANUS_-GREENWD__138_42"):
            if rng.random() < 0.5:
                rows.append({"list_day": d, "equipment": e, "sched_out_utc": _utc(d), "sched_in_utc": _utc(d + pd.Timedelta(days=3))})
    return pd.DataFrame(rows)


def test_features_for_day_d_use_only_lists_published_before_issue():
    """The list for market day X is posted ~09:40 ET on X-1, after the 05:00 D-1 issue when X = D. Features
    for D may use the list for D-1 and earlier only: changing lists for D onward must not change them."""
    days = pd.date_range("2024-01-01", "2024-02-29", freq="D")
    lists = _lists(days, np.random.default_rng(0))
    keys = ["ASTANNEX 138 ASTORIAE 138 1 | BASE CASE", "SCRIBA   345 VOLNEY   345 1 | SCRIBA__-VOLNEY___345_21"]
    target = pd.DatetimeIndex([pd.Timestamp("2024-02-15")])
    bind = np.random.default_rng(1).random((len(days), 2)) < 0.3
    lift = OutageMap(lists, min_days=3).fit_lift(keys, days[:40], bind[:40])
    base = OutageMap(lists, min_days=3).features(keys, target, lift)
    shocked = lists[lists["list_day"] < target[0]]                        # drop lists for D onward ...
    extra = pd.DataFrame({"list_day": [target[0]], "equipment": ["ASTORIAE_138KV_1"],
                          "sched_out_utc": [_utc("2024-02-15")], "sched_in_utc": [_utc("2024-02-16")]})
    shocked = pd.concat([shocked, extra], ignore_index=True)              # ... and add an outage only on D's list
    after = OutageMap(shocked, min_days=3).features(keys, target, lift)
    for k in base:
        np.testing.assert_array_equal(base[k], after[k])


def test_expected_out_follows_the_scheduled_window_by_hour():
    lists = pd.DataFrame({"list_day": [pd.Timestamp("2024-07-09")], "equipment": ["DUNWODIE_345KV_7"],
                          "sched_out_utc": [_utc("2024-07-09 08:00")], "sched_in_utc": [_utc("2024-07-10 06:30")]})
    out = OutageMap(lists).expected_out(pd.DatetimeIndex([pd.Timestamp("2024-07-10")]))[0, :, 0]
    assert out[:7].all() and not out[7:].any()                           # hours 00..06 (06:00-06:30 overlaps)


def test_lift_uses_only_the_days_it_is_given():
    days = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    lists = _lists(days, np.random.default_rng(2))
    keys = ["ASTANNEX 138 ASTORIAE 138 1 | BASE CASE"]
    bind = np.random.default_rng(3).random((len(days), 1)) < 0.3
    a = OutageMap(lists, min_days=3).fit_lift(keys, days[:60], bind[:60])
    bind2 = bind.copy()
    bind2[60:] = ~bind2[60:]                                              # change outcomes after the training days
    b = OutageMap(lists, min_days=3).fit_lift(keys, days[:60], bind2[:60])
    pd.testing.assert_frame_equal(a, b)


def test_crossfit_lift_features_never_use_their_own_block_labels():
    """With outage_lift='crossfit', a training block's lift features must not change when that block's
    binding outcomes change (they come from a table fit on the other blocks)."""
    from lmpsignal.structural.congestion import StructuralCongestion

    days = pd.date_range("2024-01-01", "2024-04-30", freq="D")
    keys = ["ASTANNEX 138 ASTORIAE 138 1 | BASE CASE", "SCRIBA   345 VOLNEY   345 1 | SCRIBA__-VOLNEY___345_21"]
    rng = np.random.default_rng(4)
    rows = [{"market": "da", "d": d, "hr": h, "key": k, "mu": 5.0}
            for d in days for h in range(24) for k in keys if rng.random() < 0.3]
    M = StructuralCongestion(k=2, outage_map=True, outage_lift="crossfit", lift_blocks=4)
    idx = pd.MultiIndex.from_product([days, range(24)], names=["delivery_date", "hour_local"])
    M.sys = pd.DataFrame({"load_fcst_nyiso": 1.0, "temp_fcst_nyiso": 1.0, "gas_hh": 1.0, "dow": 1, "month": 1}, index=idx)
    M.outages = pd.DataFrame({"n_outages": 1, "n_outages_345": 1}, index=days)
    M.omap = OutageMap(_lists(pd.date_range("2023-12-31", "2024-04-30"), rng), min_days=3)
    train = days[40:]                                         # leave 40 days of history for the lag features
    M.sp = pd.DataFrame(rows)
    base = M._train_features("da", keys, train, None)
    block0 = np.array_split(np.arange(len(train)), 4)[0]
    flipped = M.sp[~M.sp["d"].isin(train[block0])]           # remove every binding event in block 0
    M.sp = flipped
    after = M._train_features("da", keys, train, None)
    n0 = len(block0) * 24 * len(keys)
    for c in ("lift_max", "lift_min"):
        np.testing.assert_array_equal(base[c].to_numpy()[:n0], after[c].to_numpy()[:n0])
