"""Dataset registry: the single source of truth for what we pull from NYISO MIS.

Adding a dataset = adding one `Dataset` entry here. Download, parse and storage
are all driven from these fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field

LBMP_COLS = {
    "Name": "name",
    "PTID": "ptid",
    "LBMP ($/MWHr)": "lbmp",
    "Marginal Cost Losses ($/MWHr)": "mlc",
    "Marginal Cost Congestion ($/MWHr)": "mcc",
}
ASP_COLS = {
    "Name": "zone",
    "PTID": "ptid",
    "10 Min Spinning Reserve ($/MWHr)": "spin_10",
    "10 Min Non-Synchronous Reserve ($/MWHr)": "nonsync_10",
    "30 Min Operating Reserve ($/MWHr)": "or_30",
    "NYCA Regulation Capacity ($/MWHr)": "reg_cap",
}
CONSTRAINT_COLS = {
    "Limiting Facility": "facility",
    "Facility PTID": "facility_ptid",
    "Contingency": "contingency",
    "Constraint Cost($)": "shadow_price",
}


@dataclass(frozen=True)
class Dataset:
    key: str                      # curated table name
    mis_dir: str                  # folder under /public/csv/
    stem: str                     # daily file = YYYYMMDD{stem}.csv; monthly zip = YYYYMM01{stem}_csv.zip
    interval_min: int             # native granularity
    ts_convention: str            # "start" or "end" — what the published timestamp marks
    columns: dict[str, str]       # source column -> curated column (only these are kept)
    entity: tuple[str, ...]       # curated columns identifying one series (for DST disambiguation + dedup)
    ts_col: str = "Time Stamp"
    tz_col: str | None = None     # "Time Zone" (EDT/EST) when the file has one
    wide: bool = False            # isolf-style wide table (one column per zone)
    description: str = ""
    dtypes: dict[str, str] = field(default_factory=dict)
    datetime_cols: tuple[str, ...] = ()   # extra local datetime columns -> <name>_utc
    snapshot_keys: tuple[str, ...] = ()   # if set: file is a repeated snapshot; compact to validity intervals
    snapshot_gap_min: int = 15


def _lbmp(key, mis_dir, stem, interval, conv, desc, level):
    cols = dict(LBMP_COLS)
    cols["Name"] = level  # "zone" or "node"
    return Dataset(key, mis_dir, stem, interval, conv, cols, ("ptid",), description=desc)


DATASETS: dict[str, Dataset] = {d.key: d for d in [
    _lbmp("da_lbmp_zone", "damlbmp", "damlbmp_zone", 60, "start", "Day-ahead zonal LBMP", "zone"),
    _lbmp("rt_lbmp_zone", "realtime", "realtime_zone", 5, "end", "Real-time 5-min zonal LBMP", "zone"),
    _lbmp("rt_lbmp_zone_hourly", "rtlbmp", "rtlbmp_zone", 60, "start", "Integrated (hourly) RT zonal LBMP", "zone"),
    _lbmp("da_lbmp_node", "damlbmp", "damlbmp_gen", 60, "start", "Day-ahead generator-node LBMP", "node"),
    _lbmp("rt_lbmp_node_hourly", "rtlbmp", "rtlbmp_gen", 60, "start", "Integrated (hourly) RT generator-node LBMP", "node"),
    _lbmp("rt_lbmp_node", "realtime", "realtime_gen", 5, "end", "Real-time 5-min generator-node LBMP", "node"),
    Dataset("load", "pal", "pal", 5, "start",
            {"Name": "zone", "PTID": "ptid", "Load": "load_mw"}, ("ptid",),
            tz_col="Time Zone", description="Actual 5-min load by zone"),
    Dataset("load_forecast", "isolf", "isolf", 60, "start", {}, ("zone",),
            wide=True, description="ISO load forecast (hourly, multi-day) by zone"),
    Dataset("fuel_mix", "rtfuelmix", "rtfuelmix", 5, "end",
            {"Fuel Category": "fuel", "Gen MW": "gen_mw"}, ("fuel",),
            tz_col="Time Zone", description="Real-time fuel mix"),
    Dataset("btm_solar", "btmactualforecast", "BTMEstimatedActual", 60, "start",
            {"Zone Name": "zone", "MW Value": "mw"}, ("zone",),
            tz_col="Time Zone", description="Behind-the-meter solar estimated actual"),
    Dataset("da_constraints", "DAMLimitingConstraints", "DAMLimitingConstraints", 60, "start",
            CONSTRAINT_COLS, ("facility", "contingency"),
            tz_col="Time Zone", description="Day-ahead binding constraints"),
    Dataset("rt_constraints", "LimitingConstraints", "LimitingConstraints", 5, "start",
            CONSTRAINT_COLS, ("facility", "contingency"),
            tz_col="Time Zone", description="Real-time binding constraints"),
    Dataset("interface_flows", "ExternalLimitsFlows", "ExternalLimitsFlows", 5, "start",
            {"Interface Name": "interface", "Point ID": "ptid", "Flow (MWH)": "flow_mw",
             "Positive Limit (MWH)": "pos_limit_mw", "Negative Limit (MWH)": "neg_limit_mw"},
            ("interface",), ts_col="Timestamp", description="Interface flows and limits"),
    Dataset("da_asp", "damasp", "damasp", 60, "start", ASP_COLS, ("ptid",),
            tz_col="Time Zone", description="Day-ahead ancillary service (reserve/regulation) prices by zone"),
    Dataset("rt_asp", "rtasp", "rtasp", 5, "end", {**ASP_COLS, "NYCA Regulation Movement ($/MW)": "reg_move"},
            ("ptid",), tz_col="Time Zone", description="Real-time ancillary service prices by zone"),
    Dataset("sched_outages", "schedlineoutages", "SCLineOutages", 5, "start",
            {"PTID": "ptid", "Equipment Name": "equipment",
             "Scheduled Out Date/Time": "sched_out", "Scheduled In Date/Time": "sched_in"},
            ("ptid", "equipment", "sched_out", "sched_in"), ts_col="Timestamp",
            datetime_cols=("sched_out", "sched_in"),
            snapshot_keys=("ptid", "equipment", "sched_out_utc", "sched_in_utc"),
            description="Scheduled transmission outages, compacted from 5-minute schedule snapshots"),
    Dataset("rt_line_outages", "realtimelineoutages", "RTLineOutages", 5, "start",
            {"PTID": "ptid", "Equipment Name": "equipment", "Outage Date/Time": "outage_start"},
            ("ptid", "equipment", "outage_start"), ts_col="Timestamp",
            datetime_cols=("outage_start",),
            snapshot_keys=("ptid", "equipment", "outage_start_utc"),
            description="Transmission equipment out of service in real time, compacted from snapshots"),
]}

# Backfill order: small/fast datasets first, the ~300M-row nodal RT set last.
BACKFILL_ORDER = [
    "da_lbmp_zone", "rt_lbmp_zone_hourly", "load", "fuel_mix", "btm_solar", "load_forecast",
    "da_constraints", "rt_constraints", "interface_flows", "rt_lbmp_zone",
    "da_asp", "rt_asp", "sched_outages", "rt_line_outages",
    "da_lbmp_node", "rt_lbmp_node_hourly", "rt_lbmp_node",
]
assert set(BACKFILL_ORDER) == set(DATASETS)
