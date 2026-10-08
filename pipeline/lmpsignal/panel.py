"""Point-in-time modeling panel for the anchor horizon h0 (delivery day D, issued 05:00 ET on D-1).

One row per (delivery hour, location). Targets are DA and RT hourly prices split into additive
components (energy + loss + congestion = total). Every feature block also records `_avail_<block>`,
the latest publication time of any source row it used; `check_asof` proves all of them are
<= issue_utc, so no feature can see information published after the forecast was made.

Availability rules (see docs/DATA.md "As-of availability"):
  DA prices for day X ....... 11:00 ET on X-1
  RT hourly price ........... interval end + 15 min
  ISOLF issue F ............. 08:30 ET on F   (so a 05:00 D-1 issue uses the D-2 file)
  weather_fcst / gas ........ their available_utc column
  weather_hrrr .............. available_utc = 06z run on D-1 + 2 h
  rt_asp .................... interval end + 15 min;  da_asp of day X: 11:00 ET on X-1
  da_sched_outages list X ... ~09:40 ET on X-1 (the D-1 list is used for D)
  load_fix_oos .............. inputs above (ISOLF D-2, HRRR, GFS) + a model trained on data ending 7 days before the
                              month (lmpsignal/loadfix.py); NULL before 2022-10 and until `lmp loadfix gbm --oos` runs
"""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

from lmpsignal.calendar import holiday_table
from lmpsignal.config import BURN_IN_START, FEATURES_DB, ISSUE_HOUR_ET, LOCATIONS
from nyiso.config import DB_PATH, WEATHER_STATIONS

ET = "'America/New_York'"

# ---------------------------------------------------------------------------- feature documentation
# name -> (description, availability rule). Every non-target, non-key panel column must be listed
# (tests/test_panel.py enforces it).
FEATURES: dict[str, tuple[str, str]] = {
    "hour_local": ("Local clock hour of the delivery interval (0-23; hour 1 repeats on the fall-back day).", "calendar"),
    "hour_index": ("Position of the interval within the local delivery day (0..n_hours-1).", "calendar"),
    "n_hours": ("Hours in the local delivery day (23, 24 or 25).", "calendar"),
    "dow": ("ISO day of week of D (1 = Monday).", "calendar"),
    "month": ("Month of D.", "calendar"),
    "is_weekend": ("D is Saturday or Sunday.", "calendar"),
    "is_holiday": ("D is a NERC holiday.", "calendar"),
    "doy_sin": ("sin(2π · day-of-year / 365.25).", "calendar"),
    "doy_cos": ("cos(2π · day-of-year / 365.25).", "calendar"),
    **{f"lag_da_d1_{c}": (f"DA {c} price, same zone, same local hour, delivery day D-1 ($/MWh).",
                          "DA results for D-1 posted 11:00 ET on D-2") for c in ("total", "energy", "loss", "congestion")},
    **{f"lag_da_d7_{c}": (f"DA {c} price, same zone and local hour, D-7 ($/MWh).", "posted 11:00 ET on D-8")
       for c in ("total", "energy", "loss", "congestion")},
    **{f"lag_rt_d2_{c}": (f"RT hourly {c} price, same zone and local hour, D-2 ($/MWh). D-1 RT is not used because "
                          "most of it happens after the 05:00 issue.", "interval end + 15 min")
       for c in ("total", "energy", "loss", "congestion")},
    "da_d1_mean": ("Mean DA total price of the zone over delivery day D-1.", "11:00 ET on D-2"),
    "da_d1_max": ("Max hourly DA total price of the zone on D-1.", "11:00 ET on D-2"),
    "da_d1_min": ("Min hourly DA total price of the zone on D-1.", "11:00 ET on D-2"),
    "rt_d2_mean": ("Mean RT total price of the zone over D-2.", "interval end + 15 min"),
    "rt_d2_std": ("Std of hourly RT total price of the zone over D-2 (volatility).", "interval end + 15 min"),
    "rt_latest": ("Latest RT hourly total price of the zone available at issue time (about 02:00-03:00 ET on D-1).",
                  "interval end + 15 min"),
    "load_fcst_zone": ("NYISO ISOLF load forecast for the zone and delivery hour, latest issue available (the D-2 "
                       "file). NULL for external zones (MW).", "08:30 ET on the ISOLF file date"),
    "load_fcst_nyiso": ("ISOLF NYISO-total load forecast for the delivery hour (MW).", "08:30 ET on file date"),
    "load_fcst_nyiso_daily_max": ("Max of ISOLF NYISO-total forecast over delivery day D (MW).", "08:30 ET on file date"),
    "temp_fcst_zone": ("GFS 2 m temperature forecast for the delivery hour, averaged over the zone's stations, "
                       "using the shortest lead available at issue time (°C). External zones use all stations.",
                       "weather_fcst.available_utc"),
    "temp_fcst_nyiso": ("Same, averaged over all 11 stations (°C).", "weather_fcst.available_utc"),
    "hdh_zone": ("Heating degree-hours: max(0, 18.3 − temp_fcst_zone).", "as temp_fcst_zone"),
    "cdh_zone": ("Cooling degree-hours: max(0, temp_fcst_zone − 18.3).", "as temp_fcst_zone"),
    "temp_fcst_zone_isolf": ("GFS 2 m temperature forecast for the delivery hour as available when the ISOLF file used "
                             "(D-2) was published, 08:30 ET on D-2: roughly the weather NYISO's forecast was built on (°C). "
                             "External zones use all stations.", "weather_fcst.available_utc <= 08:30 ET D-2"),
    **{f"hrrr_{c}_zone": (f"HRRR 06z (D-1) forecast for the delivery hour, zone {d}. NULL for external zones.",
                          "weather_hrrr.available_utc (06z D-1 + 2 h)")
       for c, d in (("temp", "mean 2 m temperature (°C)"), ("dewpoint", "mean 2 m dew point (°C)"),
                    ("wind80", "mean 80 m wind speed (m/s)"), ("cloud", "mean total cloud cover (%)"),
                    ("cape", "90th-percentile surface CAPE (J/kg)"),
                    ("refl40", "share of cells with composite reflectivity >= 40 dBZ"),
                    ("lightning", "mean lightning flash density"))},
    **{f"hrrr_temp_zone_d{s}": (f"{n} of hrrr_temp_zone over delivery day D (°C): daily level for thermal inertia.",
                                "as hrrr_temp_zone") for s, n in (("mean", "Mean"), ("max", "Max"), ("min", "Min"))},
    "hrrr_temp_nyiso": ("Mean over the 11 internal zones of hrrr_temp_zone (°C).", "as hrrr_temp_zone"),
    "hrrr_cape_nyiso_max": ("Max over internal zones of hrrr_cape_zone for the hour (J/kg).", "as hrrr_temp_zone"),
    "hrrr_refl40_nyiso_max": ("Max over internal zones of hrrr_refl40_zone for the hour.", "as hrrr_temp_zone"),
    "hrrr_lightning_nyiso_max": ("Max over internal zones of hrrr_lightning_zone for the hour.", "as hrrr_temp_zone"),
    "load_fix_zone": ("Weather-corrected load forecast for the zone and hour: ISOLF D-2 x (1 + predicted relative "
                      "error) from loadfix_gbm, out of sample (model trained on data ending 7 days before the month). "
                      "NULL for external zones and before 2022-10 (MW).", "max of ISOLF D-2, HRRR, GFS inputs"),
    "load_surprise_zone": ("Predicted relative error of the ISOLF D-2 forecast for the zone and hour "
                           "(load_fix_zone / load_fcst_zone - 1).", "as load_fix_zone"),
    "load_fix_nyiso": ("Sum of load_fix_zone over the 11 internal zones (NULL unless all 11 present) (MW).",
                       "as load_fix_zone"),
    "load_surprise_nyiso": ("load_fix_nyiso / sum of zonal ISOLF D-2 - 1: system load surprise.", "as load_fix_zone"),
    "load_fix_nyiso_daily_max": ("Max of load_fix_nyiso over delivery day D (MW).", "as load_fix_zone"),
    "rt_spin_max_24h": ("Max RT 10-min spinning reserve price of the zone over the 24 h before issue ($/MWh). NULL for "
                        "external zones.", "rt_asp interval end + 15 min"),
    "rt_spin_mean_24h": ("Mean RT 10-min spinning reserve price of the zone over the 24 h before issue ($/MWh).",
                         "rt_asp interval end + 15 min"),
    "rt_shortage_7d": ("Number of RT 5-min intervals in the 7 days before issue with the zone's 10-min spinning or 30-min "
                       "reserve price above $50 (reserve shortage proxy).", "rt_asp interval end + 15 min"),
    "da_spin_max_d1": ("Max DA 10-min spinning reserve price of the zone on D-1 ($/MWh).", "da_asp of D-1: 11:00 ET on D-2"),
    "dam_outages_d": ("Transmission outages on the DAM outage list of D-1 (P-54C) scheduled to still be out on D.",
                      "list of D-1 posted ~09:40 ET on D-2"),
    "dam_outages_345_d": ("Same, 345 kV equipment only.", "list of D-1 posted ~09:40 ET on D-2"),
    "gas_hh": ("Latest Henry Hub spot price available at issue time ($/MMBtu).", "gas_henry_hub.available_utc"),
    "implied_hr_d1": ("da_d1_mean / gas_hh: implied market heat rate of D-1 (MMBtu/MWh).", "max of inputs"),
}

# Named feature sets, so adding panel columns never silently changes an existing model configuration.
_WEATHER_V2 = ("temp_fcst_zone_isolf",) + tuple(c for c in FEATURES if c.startswith("hrrr_"))
_LOAD_V3 = ("load_fix_zone", "load_surprise_zone", "load_fix_nyiso", "load_surprise_nyiso", "load_fix_nyiso_daily_max")
_RESERVE_V4 = ("rt_spin_max_24h", "rt_spin_mean_24h", "rt_shortage_7d", "da_spin_max_d1", "dam_outages_d",
               "dam_outages_345_d")
FEATURE_SETS: dict[str, list[str]] = {
    "v1": [c for c in FEATURES if c not in _WEATHER_V2 + _LOAD_V3 + _RESERVE_V4],   # panel as of M2-M3 (2026-09-28)
    "v2": [c for c in FEATURES if c not in _LOAD_V3 + _RESERVE_V4],    # + HRRR weather, ISOLF-vintage GFS (2026-10-02)
    "v3": [c for c in FEATURES if c not in _RESERVE_V4],               # + weather-corrected load (2026-10-04)
    "v4": list(FEATURES),                                              # + reserve prices, DAM outage counts (2026-10-05)
}

KEYS = ["delivery_date", "ts_utc", "ts_local", "zone", "issue_utc"]
TARGETS = [f"{m}_{c}" for m in ("da", "rt") for c in ("total", "energy", "loss", "congestion")]
MASKS = ["score_da", "score_rt"]


def _sql(start: str) -> str:
    stations = ", ".join(f"('{code}', '{z}')" for code, (*_x, zones) in WEATHER_STATIONS.items() for z in zones)
    locs = ", ".join(f"'{z}'" for z in LOCATIONS)
    return f"""
SET TimeZone = 'UTC';

CREATE OR REPLACE TEMP TABLE station_zone AS SELECT * FROM (VALUES {stations}) t(station, zone);

-- hourly prices with additive components, one row per (zone, local date, local hour)
CREATE OR REPLACE TEMP TABLE px AS
SELECT zone, CAST(ts_local AS DATE) AS d, hour(ts_local) AS hr, max(ts_utc) AS ts_max,
       avg(da_lbmp) AS da_total, avg(da_lbmp - da_mlc + da_mcc) AS da_energy, avg(da_mlc) AS da_loss, avg(-da_mcc) AS da_congestion,
       avg(rt_lbmp) AS rt_total, avg(rt_lbmp - rt_mlc + rt_mcc) AS rt_energy, avg(rt_mlc) AS rt_loss, avg(-rt_mcc) AS rt_congestion
FROM wh.lbmp_zone_hourly WHERE zone IN ({locs}) GROUP BY ALL;

-- targets: one row per delivery interval
CREATE OR REPLACE TEMP TABLE tgt AS
SELECT h.ts_utc, h.ts_local, CAST(h.ts_local AS DATE) AS delivery_date, h.zone,
       timezone({ET}, CAST(CAST(h.ts_local AS DATE) - INTERVAL 1 DAY AS TIMESTAMP) + INTERVAL {ISSUE_HOUR_ET} HOUR) AS issue_utc,
       h.da_lbmp AS da_total, h.da_lbmp - h.da_mlc + h.da_mcc AS da_energy, h.da_mlc AS da_loss, -h.da_mcc AS da_congestion,
       h.rt_lbmp AS rt_total, h.rt_lbmp - h.rt_mlc + h.rt_mcc AS rt_energy, h.rt_mlc AS rt_loss, -h.rt_mcc AS rt_congestion,
       h.rt_flag
FROM wh.lbmp_zone_hourly h
WHERE h.zone IN ({locs}) AND CAST(h.ts_local AS DATE) >= DATE '{start}';

-- forecast rows for delivery days after the last priced day (targets NULL): the live forecast needs day D
-- before any of its prices exist
INSERT INTO tgt
SELECT f.ts_utc, f.ts_local, CAST(f.ts_local AS DATE),
       f.zone, timezone({ET}, CAST(CAST(f.ts_local AS DATE) - INTERVAL 1 DAY AS TIMESTAMP) + INTERVAL {ISSUE_HOUR_ET} HOUR),
       NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL
FROM future_grid f
WHERE CAST(f.ts_local AS DATE) > (SELECT max(delivery_date) FROM tgt);

CREATE OR REPLACE TEMP TABLE base AS
SELECT t.*, hour(t.ts_local) AS hour_local,
       row_number() OVER (PARTITION BY t.zone, t.delivery_date ORDER BY t.ts_utc) - 1 AS hour_index,
       count(*) OVER (PARTITION BY t.zone, t.delivery_date) AS n_hours
FROM tgt t;

-- RT hourly with availability, for the as-of 'latest RT' feature
CREATE OR REPLACE TEMP TABLE rt_avail AS
SELECT zone, ts_utc + INTERVAL 75 MINUTE AS avail_utc, rt_lbmp AS rt_total
FROM wh.lbmp_zone_hourly WHERE zone IN ({locs}) AND rt_lbmp IS NOT NULL;

CREATE OR REPLACE TEMP TABLE daily AS
SELECT zone, d, avg(da_total) AS da_mean, max(da_total) AS da_max, min(da_total) AS da_min,
       avg(rt_total) AS rt_mean, stddev_pop(rt_total) AS rt_std, max(ts_max) AS ts_max
FROM px GROUP BY ALL;

-- load forecast with ISOLF availability (08:30 ET on file date)
CREATE OR REPLACE TEMP TABLE lf AS
SELECT ts_utc, zone, load_forecast_mw,
       timezone({ET}, CAST(issue_date AS TIMESTAMP) + INTERVAL 510 MINUTE) AS avail_utc
FROM wh.load_forecast;

-- weather forecast: latest vintage available at each issue, per station and valid hour
CREATE OR REPLACE TEMP TABLE wx_need AS SELECT DISTINCT ts_utc, issue_utc FROM base;
CREATE OR REPLACE TEMP TABLE wx AS
SELECT n.ts_utc, n.issue_utc, f.station, f.temp_c, f.available_utc
FROM wx_need n CROSS JOIN (SELECT DISTINCT station FROM station_zone) s
ASOF JOIN (SELECT * FROM wh.weather_fcst ORDER BY available_utc) f
  ON f.ts_utc = n.ts_utc AND f.station = s.station AND n.issue_utc >= f.available_utc;
CREATE OR REPLACE TEMP TABLE wx_zone AS
SELECT w.ts_utc, w.issue_utc, sz.zone, avg(w.temp_c) AS temp, max(w.available_utc) AS avail
FROM wx w JOIN station_zone sz USING (station) GROUP BY ALL;
CREATE OR REPLACE TEMP TABLE wx_sys AS
SELECT ts_utc, issue_utc, avg(temp_c) AS temp, max(available_utc) AS avail FROM wx GROUP BY ALL;

-- the same GFS forecast as known when the ISOLF file in use (D-2, 08:30 ET) was published
CREATE OR REPLACE TEMP TABLE wxi_need AS
SELECT DISTINCT ts_utc, delivery_date,
       timezone({ET}, CAST(delivery_date - INTERVAL 2 DAY AS TIMESTAMP) + INTERVAL 510 MINUTE) AS isolf_utc
FROM base;
CREATE OR REPLACE TEMP TABLE wxi AS
SELECT n.ts_utc, n.isolf_utc, f.station, f.temp_c, f.available_utc
FROM wxi_need n CROSS JOIN (SELECT DISTINCT station FROM station_zone) s
ASOF JOIN (SELECT * FROM wh.weather_fcst ORDER BY available_utc) f
  ON f.ts_utc = n.ts_utc AND f.station = s.station AND n.isolf_utc >= f.available_utc;
CREATE OR REPLACE TEMP TABLE wxi_zone AS
SELECT w.ts_utc, sz.zone, avg(w.temp_c) AS temp, max(w.available_utc) AS avail
FROM wxi w JOIN station_zone sz USING (station) GROUP BY ALL;
CREATE OR REPLACE TEMP TABLE wxi_sys AS SELECT ts_utc, avg(temp_c) AS temp, max(available_utc) AS avail FROM wxi GROUP BY ALL;

-- HRRR 06z D-1 run, zone aggregates; as-of joined on its availability
CREATE OR REPLACE TEMP TABLE hr AS
SELECT b.ts_utc, b.zone, b.delivery_date, h.temp_c, h.dewpoint_c, h.wind80_ms, h.cloud_pct, h.cape_p90,
       h.refl40_share, h.lightning_density, h.available_utc
FROM (SELECT DISTINCT ts_utc, zone, delivery_date, issue_utc FROM base) b
ASOF JOIN (SELECT * FROM wh.weather_hrrr ORDER BY available_utc) h
  ON h.ts_utc = b.ts_utc AND h.zone = b.zone AND b.issue_utc >= h.available_utc;
CREATE OR REPLACE TEMP TABLE hr_day AS
SELECT zone, delivery_date, avg(temp_c) AS tmean, max(temp_c) AS tmax, min(temp_c) AS tmin, max(available_utc) AS avail
FROM hr GROUP BY ALL;
CREATE OR REPLACE TEMP TABLE hr_sys AS
SELECT ts_utc, avg(temp_c) AS temp, max(cape_p90) AS cape, max(refl40_share) AS refl, max(lightning_density) AS ltng,
       max(available_utc) AS avail
FROM hr GROUP BY ALL;

-- weather-corrected load (out-of-sample table written by `lmp loadfix gbm --oos`)
CREATE OR REPLACE TEMP TABLE lfx_sys AS
SELECT x.ts_utc, sum(x.load_fix) AS fix, sum(x.load_fix / (1 + x.r_hat)) AS isolf, count(*) AS n
FROM load_fix_oos x GROUP BY 1;
CREATE OR REPLACE TEMP TABLE lfx_day AS
SELECT timezone({ET}, ts_utc)::DATE AS d, max(fix) AS mx FROM lfx_sys WHERE n = 11 GROUP BY 1;

-- reserve prices (M3b): RT ASP as of issue (interval start + 5 min end + 15 min), DA ASP of D-1
CREATE OR REPLACE TEMP TABLE iss AS SELECT DISTINCT zone, issue_utc, delivery_date FROM base;
CREATE OR REPLACE TEMP TABLE rsv AS
SELECT i.zone, i.issue_utc,
       max(a.spin_10) FILTER (WHERE a.ts_utc >= i.issue_utc - INTERVAL 24 HOUR) AS spin_max,
       avg(a.spin_10) FILTER (WHERE a.ts_utc >= i.issue_utc - INTERVAL 24 HOUR) AS spin_mean,
       count(*) FILTER (WHERE a.spin_10 > 50 OR a.or_30 > 50) AS shortage,
       max(a.ts_utc) + INTERVAL 20 MINUTE AS avail
FROM iss i JOIN wh.rt_asp a
  ON a.zone = i.zone AND a.ts_utc >= i.issue_utc - INTERVAL 7 DAY AND a.ts_utc + INTERVAL 20 MINUTE <= i.issue_utc
GROUP BY ALL;
CREATE OR REPLACE TEMP TABLE dasp AS
SELECT zone, CAST(ts_local AS DATE) AS d, max(spin_10) AS spin_max FROM wh.da_asp GROUP BY ALL;
-- DAM outage list of D-1 (P-54C), outages still scheduled out on D
CREATE OR REPLACE TEMP TABLE damo AS
SELECT d.delivery_date,
       count(DISTINCT o.equipment) AS n, count(DISTINCT o.equipment) FILTER (WHERE o.equipment LIKE '%345%') AS n345,
       timezone({ET}, CAST(d.delivery_date - INTERVAL 2 DAY AS TIMESTAMP) + INTERVAL 10 HOUR) AS avail
FROM (SELECT DISTINCT delivery_date FROM base) d
JOIN wh.da_sched_outages o ON CAST(o.ts_local AS DATE) = d.delivery_date - INTERVAL 1 DAY
 AND o.sched_in_utc > timezone({ET}, CAST(d.delivery_date AS TIMESTAMP))
 AND o.sched_out_utc < timezone({ET}, CAST(d.delivery_date + INTERVAL 1 DAY AS TIMESTAMP))
GROUP BY ALL;

CREATE OR REPLACE TEMP TABLE hol AS SELECT * FROM holidays;

CREATE OR REPLACE TABLE panel AS
WITH lfz AS (
    SELECT b.zone, b.ts_utc, f.load_forecast_mw, f.avail_utc
    FROM base b ASOF JOIN lf f ON f.ts_utc = b.ts_utc AND f.zone = b.zone AND b.issue_utc >= f.avail_utc
), lfn AS (
    SELECT b.ts_utc, b.issue_utc, f.load_forecast_mw, f.avail_utc
    FROM (SELECT DISTINCT ts_utc, issue_utc FROM base) b
    ASOF JOIN (SELECT * FROM lf WHERE zone = 'NYISO') f ON f.ts_utc = b.ts_utc AND b.issue_utc >= f.avail_utc
), lfn_day AS (
    SELECT timezone({ET}, b.ts_utc)::DATE AS d, max(load_forecast_mw) AS mx, max(avail_utc) AS avail FROM lfn b GROUP BY 1
), gas AS (
    SELECT i.issue_utc, g.price_usd_mmbtu, g.available_utc
    FROM (SELECT DISTINCT issue_utc FROM base) i
    ASOF JOIN (SELECT * FROM wh.gas_henry_hub ORDER BY available_utc) g ON i.issue_utc >= g.available_utc
), rtl AS (
    SELECT b.zone, b.issue_utc, r.rt_total, r.avail_utc
    FROM (SELECT DISTINCT zone, issue_utc FROM base) b
    ASOF JOIN (SELECT * FROM rt_avail ORDER BY avail_utc) r ON r.zone = b.zone AND b.issue_utc >= r.avail_utc
)
SELECT
    b.delivery_date, b.ts_utc, b.ts_local, b.zone, b.issue_utc,
    -- targets
    b.da_total, b.da_energy, b.da_loss, b.da_congestion, b.rt_total, b.rt_energy, b.rt_loss, b.rt_congestion,
    -- calendar
    b.hour_local, b.hour_index, b.n_hours,
    isodow(b.delivery_date) AS dow, month(b.delivery_date) AS month,
    isodow(b.delivery_date) >= 6 AS is_weekend, hol.d IS NOT NULL AS is_holiday,
    sin(2 * pi() * dayofyear(b.delivery_date) / 365.25) AS doy_sin, cos(2 * pi() * dayofyear(b.delivery_date) / 365.25) AS doy_cos,
    -- lagged prices
    p1.da_total AS lag_da_d1_total, p1.da_energy AS lag_da_d1_energy, p1.da_loss AS lag_da_d1_loss, p1.da_congestion AS lag_da_d1_congestion,
    p7.da_total AS lag_da_d7_total, p7.da_energy AS lag_da_d7_energy, p7.da_loss AS lag_da_d7_loss, p7.da_congestion AS lag_da_d7_congestion,
    p2.rt_total AS lag_rt_d2_total, p2.rt_energy AS lag_rt_d2_energy, p2.rt_loss AS lag_rt_d2_loss, p2.rt_congestion AS lag_rt_d2_congestion,
    d1.da_mean AS da_d1_mean, d1.da_max AS da_d1_max, d1.da_min AS da_d1_min,
    d2.rt_mean AS rt_d2_mean, d2.rt_std AS rt_d2_std,
    rtl.rt_total AS rt_latest,
    -- load forecast (ISOLF)
    lfz.load_forecast_mw AS load_fcst_zone, lfn.load_forecast_mw AS load_fcst_nyiso, lfn_day.mx AS load_fcst_nyiso_daily_max,
    -- weather forecast
    coalesce(wz.temp, ws.temp) AS temp_fcst_zone, ws.temp AS temp_fcst_nyiso,
    greatest(0, 18.3 - coalesce(wz.temp, ws.temp)) AS hdh_zone, greatest(0, coalesce(wz.temp, ws.temp) - 18.3) AS cdh_zone,
    coalesce(wiz.temp, wis.temp) AS temp_fcst_zone_isolf,
    -- HRRR (06z D-1)
    hr.temp_c AS hrrr_temp_zone, hr.dewpoint_c AS hrrr_dewpoint_zone, hr.wind80_ms AS hrrr_wind80_zone,
    hr.cloud_pct AS hrrr_cloud_zone, hr.cape_p90 AS hrrr_cape_zone, hr.refl40_share AS hrrr_refl40_zone,
    hr.lightning_density AS hrrr_lightning_zone,
    hd.tmean AS hrrr_temp_zone_dmean, hd.tmax AS hrrr_temp_zone_dmax, hd.tmin AS hrrr_temp_zone_dmin,
    hs.temp AS hrrr_temp_nyiso, hs.cape AS hrrr_cape_nyiso_max, hs.refl AS hrrr_refl40_nyiso_max,
    hs.ltng AS hrrr_lightning_nyiso_max,
    -- weather-corrected load
    lx.load_fix AS load_fix_zone, lx.r_hat AS load_surprise_zone,
    CASE WHEN lxs.n = 11 THEN lxs.fix END AS load_fix_nyiso,
    CASE WHEN lxs.n = 11 THEN lxs.fix / lxs.isolf - 1 END AS load_surprise_nyiso,
    lxd.mx AS load_fix_nyiso_daily_max,
    -- reserve prices and DAM outages
    rsv.spin_max AS rt_spin_max_24h, rsv.spin_mean AS rt_spin_mean_24h, rsv.shortage AS rt_shortage_7d,
    dasp.spin_max AS da_spin_max_d1, damo.n AS dam_outages_d, damo.n345 AS dam_outages_345_d,
    -- fuel
    gas.price_usd_mmbtu AS gas_hh, d1.da_mean / nullif(gas.price_usd_mmbtu, 0) AS implied_hr_d1,
    -- scoring masks
    b.da_total IS NOT NULL AS score_da,
    b.rt_total IS NOT NULL AND b.rt_flag IS NULL AS score_rt,
    -- availability audit (latest publication time of any source row used)
    timezone({ET}, CAST(b.delivery_date - INTERVAL 2 DAY AS TIMESTAMP) + INTERVAL 11 HOUR) AS _avail_lag_da_d1,
    timezone({ET}, CAST(b.delivery_date - INTERVAL 8 DAY AS TIMESTAMP) + INTERVAL 11 HOUR) AS _avail_lag_da_d7,
    p2.ts_max + INTERVAL 75 MINUTE AS _avail_lag_rt_d2,
    d2.ts_max + INTERVAL 75 MINUTE AS _avail_rt_d2_stats,
    rtl.avail_utc AS _avail_rt_latest,
    greatest(lfz.avail_utc, lfn.avail_utc, lfn_day.avail) AS _avail_load_fcst,
    greatest(wz.avail, ws.avail) AS _avail_temp_fcst,
    greatest(wiz.avail, wis.avail) AS _avail_temp_fcst_isolf,
    greatest(hr.available_utc, hd.avail, hs.avail) AS _avail_hrrr,
    CASE WHEN coalesce(lx.load_fix, lxs.fix) IS NOT NULL
         THEN greatest(hs.avail, lfn_day.avail, lfz.avail_utc, wis.avail, wiz.avail) END AS _avail_load_fix,
    gas.available_utc AS _avail_gas,
    rsv.avail AS _avail_rt_reserve,
    CASE WHEN dasp.spin_max IS NOT NULL
         THEN timezone({ET}, CAST(b.delivery_date - INTERVAL 2 DAY AS TIMESTAMP) + INTERVAL 11 HOUR) END AS _avail_da_reserve,
    damo.avail AS _avail_dam_outages
FROM base b
LEFT JOIN px p1 ON p1.zone = b.zone AND p1.d = b.delivery_date - INTERVAL 1 DAY AND p1.hr = b.hour_local
LEFT JOIN px p7 ON p7.zone = b.zone AND p7.d = b.delivery_date - INTERVAL 7 DAY AND p7.hr = b.hour_local
LEFT JOIN px p2 ON p2.zone = b.zone AND p2.d = b.delivery_date - INTERVAL 2 DAY AND p2.hr = b.hour_local
LEFT JOIN daily d1 ON d1.zone = b.zone AND d1.d = b.delivery_date - INTERVAL 1 DAY
LEFT JOIN daily d2 ON d2.zone = b.zone AND d2.d = b.delivery_date - INTERVAL 2 DAY
LEFT JOIN rtl ON rtl.zone = b.zone AND rtl.issue_utc = b.issue_utc
LEFT JOIN lfz ON lfz.zone = b.zone AND lfz.ts_utc = b.ts_utc
LEFT JOIN lfn ON lfn.ts_utc = b.ts_utc
LEFT JOIN lfn_day ON lfn_day.d = b.delivery_date
LEFT JOIN wx_zone wz ON wz.ts_utc = b.ts_utc AND wz.zone = b.zone
LEFT JOIN wx_sys ws ON ws.ts_utc = b.ts_utc
LEFT JOIN wxi_zone wiz ON wiz.ts_utc = b.ts_utc AND wiz.zone = b.zone
LEFT JOIN wxi_sys wis ON wis.ts_utc = b.ts_utc
LEFT JOIN hr ON hr.ts_utc = b.ts_utc AND hr.zone = b.zone
LEFT JOIN hr_day hd ON hd.zone = b.zone AND hd.delivery_date = b.delivery_date
LEFT JOIN hr_sys hs ON hs.ts_utc = b.ts_utc
LEFT JOIN load_fix_oos lx ON lx.ts_utc = b.ts_utc AND lx.zone = b.zone
LEFT JOIN lfx_sys lxs ON lxs.ts_utc = b.ts_utc
LEFT JOIN lfx_day lxd ON lxd.d = b.delivery_date
LEFT JOIN rsv ON rsv.zone = b.zone AND rsv.issue_utc = b.issue_utc
LEFT JOIN dasp ON dasp.zone = b.zone AND dasp.d = b.delivery_date - INTERVAL 1 DAY
LEFT JOIN damo ON damo.delivery_date = b.delivery_date
LEFT JOIN gas ON gas.issue_utc = b.issue_utc
LEFT JOIN hol ON hol.d = b.delivery_date
ORDER BY b.ts_utc, b.zone;
"""


def future_grid(through: date | None) -> pd.DataFrame:
    """Hourly (ts_utc, ts_local, zone) rows for local delivery days up to `through` (the SQL keeps only days after
    the last priced day). DST days get 23 / 25 rows, like the priced rows."""
    if through is None:
        return pd.DataFrame({"ts_utc": pd.Series(dtype="datetime64[ns, UTC]"), "ts_local": pd.Series(dtype="datetime64[ns]"),
                             "zone": pd.Series(dtype=str)})
    t0 = pd.Timestamp(through - timedelta(days=7)).tz_localize("America/New_York")
    t1 = pd.Timestamp(through + timedelta(days=1)).tz_localize("America/New_York")
    ts = pd.date_range(t0.tz_convert("UTC"), t1.tz_convert("UTC"), freq="h", inclusive="left")
    g = pd.DataFrame({"ts_utc": ts}).merge(pd.DataFrame({"zone": LOCATIONS}), how="cross")
    g["ts_local"] = g["ts_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    return g


def build(start: str | None = None, through: date | None = None) -> int:
    """(Re)build the panel in data/features.duckdb. Returns the row count. `through`: also add feature-only rows
    for delivery days up to this date (live forecasting)."""
    start = start or str(BURN_IN_START)
    con = duckdb.connect(str(FEATURES_DB))
    con.execute(f"ATTACH '{DB_PATH.as_posix()}' AS wh (READ_ONLY)")
    hol = pd.DataFrame(holiday_table(2021, 2027), columns=["d", "name"])
    con.register("holidays_df", hol)
    con.execute("CREATE OR REPLACE TEMP TABLE holidays AS SELECT CAST(d AS DATE) AS d, name FROM holidays_df")
    con.register("future_df", future_grid(through))
    con.execute("CREATE OR REPLACE TEMP TABLE future_grid AS SELECT * FROM future_df")
    from lmpsignal.config import OOS_SCHEMA

    con.execute(OOS_SCHEMA)
    con.execute(_sql(start))
    n = con.execute("SELECT count(*) FROM panel").fetchone()[0]
    con.close()
    return n


def avail_columns(cols) -> list[str]:
    return [c for c in cols if c.startswith("_avail_")]


def check_asof(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Number of rows where a feature block used data published after issue time (must all be 0)."""
    cols = avail_columns([r[0] for r in con.execute("DESCRIBE panel").fetchall()])
    return {c: con.execute(f"SELECT count(*) FROM panel WHERE {c} > issue_utc").fetchone()[0] for c in cols}


def load(con: duckdb.DuckDBPyConnection | None = None, start=None, end=None) -> pd.DataFrame:
    """Load the panel (delivery_date in [start, end)) as a DataFrame."""
    own = con is None
    con = con or duckdb.connect(str(FEATURES_DB), read_only=True)
    con.execute("SET TimeZone = 'UTC'")
    where = []
    if start is not None:
        where.append(f"delivery_date >= DATE '{start}'")
    if end is not None:
        where.append(f"delivery_date < DATE '{end}'")
    df = con.execute("SELECT * FROM panel" + (" WHERE " + " AND ".join(where) if where else "")).df()
    if own:
        con.close()
    return df
