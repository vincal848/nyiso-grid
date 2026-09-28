-- Aggregates built on top of the curated views (one view per dataset key).
-- rt_lbmp_zone_5m and fuel_mix_5m are built first by catalog.build() with store/timeweight.py:
-- RTD intervals are irregular (~4% are not 5 minutes), so they are time-weighted onto the
-- 5-minute grid, with `covered_s` = seconds of each bucket that had data. Anything averaged
-- from them over longer periods weights by covered_s so the result stays time-weighted.

CREATE OR REPLACE MACRO to_local(ts) AS timezone('America/New_York', ts);

CREATE OR REPLACE MACRO twavg(v, w) AS sum(v * w) / sum(w);

-- ---------- 5-minute, system-level (feeds the Conditions tab) ----------
CREATE OR REPLACE TABLE load_5m AS
SELECT ts_utc, zone, load_mw, covered_s FROM load_zone_5m
UNION ALL
SELECT ts_utc, 'NYISO' AS zone, sum(load_mw), min(covered_s) FROM load_zone_5m GROUP BY ts_utc;

CREATE OR REPLACE TABLE system_5m AS
SELECT l.ts_utc,
       to_local(l.ts_utc) AS ts_local,
       l.load_mw, l.covered_s,
       l.load_mw - w.gen_mw AS net_load_mw,                    -- load minus wind (GridStatus convention); null until fuel mix posts
       p.rt_lbmp
FROM (SELECT * FROM load_5m WHERE zone = 'NYISO') l
LEFT JOIN (SELECT ts_utc, gen_mw FROM fuel_mix_5m WHERE fuel = 'Wind') w USING (ts_utc)
LEFT JOIN (
    SELECT ts_utc, avg(lbmp) AS rt_lbmp                          -- simple average across the 11 internal zones
    FROM rt_lbmp_zone_5m
    WHERE zone NOT IN ('H Q', 'NPX', 'O H', 'PJM')
    GROUP BY 1
) p USING (ts_utc);

-- ---------- hourly zonal prices ----------
-- RT hourly = NYISO integrated value; where NYISO's archive is missing it, the time-weighted
-- average of the RTD intervals (matches NYISO's integrated value to the cent in 99.97% of hours).
CREATE OR REPLACE TABLE lbmp_zone_hourly AS
WITH integrated AS (
    SELECT ts_utc, zone, lbmp, mlc, mcc, 'integrated' AS rt_source FROM rt_lbmp_zone_hourly
), derived AS (
    SELECT date_trunc('hour', ts_utc) AS ts_utc, zone,
           twavg(lbmp, covered_s) AS lbmp, twavg(mlc, covered_s) AS mlc, twavg(mcc, covered_s) AS mcc,
           'derived_twa' AS rt_source
    FROM rt_lbmp_zone_5m GROUP BY 1, 2
), r AS (
    SELECT * FROM integrated
    UNION ALL
    SELECT * FROM derived ANTI JOIN integrated USING (ts_utc, zone)
)
SELECT coalesce(d.ts_utc, r.ts_utc) AS ts_utc,
       to_local(coalesce(d.ts_utc, r.ts_utc)) AS ts_local,
       coalesce(d.zone, r.zone) AS zone,
       d.lbmp AS da_lbmp, d.mlc AS da_mlc, d.mcc AS da_mcc,
       r.lbmp AS rt_lbmp, r.mlc AS rt_mlc, r.mcc AS rt_mcc, r.rt_source,
       -- Known, accepted misses: NYISO's integrated value disagrees with its own 5-min file
       -- (NYISO-side missing intervals, or an hour still in progress at download time).
       CASE WHEN r.rt_source = 'integrated' AND abs(r.lbmp - x.lbmp) >= 0.02
            THEN 'integrated_vs_5m_mismatch' END AS rt_flag,
       d.lbmp - r.lbmp AS da_rt_spread
FROM da_lbmp_zone d
FULL JOIN r ON d.ts_utc = r.ts_utc AND d.zone = r.zone
LEFT JOIN derived x ON x.ts_utc = r.ts_utc AND x.zone = r.zone;

-- ---------- hourly system series ----------
CREATE OR REPLACE TABLE fuel_mix_hourly AS
SELECT date_trunc('hour', ts_utc) AS ts_utc, fuel, twavg(gen_mw, covered_s) AS gen_mw
FROM fuel_mix_5m GROUP BY ALL;

CREATE OR REPLACE TABLE load_hourly AS
SELECT date_trunc('hour', ts_utc) AS ts_utc, zone, twavg(load_mw, covered_s) AS load_mw
FROM load_5m GROUP BY ALL;

-- Day-ahead forecast: the value issued the calendar day before the target (local) day.
CREATE OR REPLACE TABLE load_forecast_da AS
SELECT ts_utc, zone, load_forecast_mw
FROM load_forecast
WHERE issue_date = CAST(to_local(ts_utc) AS DATE) - INTERVAL 1 DAY;

-- ---------- constraints ----------
CREATE OR REPLACE TABLE constraints_daily AS
SELECT 'DA' AS market, CAST(ts_local AS DATE) AS day, facility, contingency,
       count(*) AS intervals, count(*) * 1.0 AS hours_binding,
       sum(shadow_price) AS sum_cost, max(abs(shadow_price)) AS max_abs_cost, avg(shadow_price) AS avg_cost
FROM da_constraints GROUP BY ALL
UNION ALL
SELECT 'RT', CAST(ts_local AS DATE), facility, contingency,
       count(*), count(*) * 5 / 60.0,
       sum(shadow_price), max(abs(shadow_price)), avg(shadow_price)
FROM rt_constraints GROUP BY ALL;

-- interface_flows_hourly: built time-weighted in catalog.build()

-- ---------- daily summary (KPI cards + Trends) ----------
CREATE OR REPLACE TABLE daily_summary AS
WITH s AS (
    SELECT CAST(ts_local AS DATE) AS day,
           twavg(load_mw, covered_s) AS avg_load_mw, max(load_mw) AS peak_load_mw,
           twavg(net_load_mw, covered_s) AS avg_net_load_mw
    FROM system_5m GROUP BY 1
), da AS (
    -- DA and RT daily prices on the same basis: hourly zonal values, simple mean over hours x 11 zones
    SELECT CAST(ts_local AS DATE) AS day, avg(da_lbmp) AS avg_da_lbmp, avg(rt_lbmp) AS avg_rt_lbmp
    FROM lbmp_zone_hourly WHERE zone NOT IN ('H Q', 'NPX', 'O H', 'PJM') GROUP BY 1
), fm AS (
    SELECT CAST(to_local(ts_utc) AS DATE) AS day, fuel, twavg(gen_mw, covered_s) AS avg_mw
    FROM fuel_mix_5m GROUP BY ALL
), fm_piv AS (
    SELECT day,
           arg_max(fuel, avg_mw) AS main_source,
           sum(avg_mw) AS avg_gen_mw,
           sum(avg_mw) FILTER (WHERE fuel IN ('Wind', 'Hydro', 'Other Renewables')) / sum(avg_mw) AS renewable_share,
           sum(avg_mw) FILTER (WHERE fuel IN ('Wind', 'Hydro', 'Other Renewables', 'Nuclear')) / sum(avg_mw) AS carbon_free_share
    FROM fm GROUP BY day
)
SELECT s.*, da.avg_da_lbmp, da.avg_rt_lbmp, fm_piv.* EXCLUDE (day)
FROM s LEFT JOIN da USING (day) LEFT JOIN fm_piv USING (day)
ORDER BY day;

CREATE OR REPLACE TABLE fuel_mix_daily AS
SELECT * FROM (
    SELECT CAST(to_local(ts_utc) AS DATE) AS day, fuel, twavg(gen_mw, covered_s) AS avg_mw
    FROM fuel_mix_5m GROUP BY ALL
    UNION ALL
    SELECT CAST(ts_local AS DATE), 'BTM Solar', avg(mw)
    FROM btm_solar WHERE zone = 'SYSTEM' GROUP BY 1
) ORDER BY day, fuel;

CREATE OR REPLACE TABLE lbmp_zone_daily AS
SELECT CAST(ts_local AS DATE) AS day, zone,
       avg(da_lbmp) AS avg_da_lbmp, avg(rt_lbmp) AS avg_rt_lbmp, avg(da_rt_spread) AS avg_spread
FROM lbmp_zone_hourly GROUP BY ALL ORDER BY day, zone;
