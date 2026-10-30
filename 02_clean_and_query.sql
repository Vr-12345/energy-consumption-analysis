-- =====================================================================
-- Energy consumption project: SQL cleaning + analysis queries (SQLite)
-- Sections are separated by "-- NAME: <query_name>" markers so the
-- Python runner (02_run_sql.py) can execute and export each one.
-- =====================================================================

-- NAME: dq_before
-- Data quality audit of the raw table (what needs fixing?)
SELECT
    COUNT(*)                                                        AS total_rows,
    COUNT(*) - COUNT(DISTINCT household_id || reading_ts)           AS duplicate_rows,
    SUM(CASE WHEN kwh IS NULL THEN 1 ELSE 0 END)                    AS missing_kwh,
    SUM(CASE WHEN kwh < 0 THEN 1 ELSE 0 END)                        AS negative_kwh,
    SUM(CASE WHEN kwh > 15 THEN 1 ELSE 0 END)                       AS implausible_spikes,
    SUM(CASE WHEN outdoor_temp_c IS NULL THEN 1 ELSE 0 END)         AS missing_temp
FROM raw_readings;

-- NAME: build_clean
-- Cleaned, analysis-ready table: de-duplicated, invalid readings removed,
-- plus derived date parts for easy grouping.
DROP TABLE IF EXISTS readings_clean;
CREATE TABLE readings_clean AS
WITH dedup AS (
    SELECT household_id, reading_ts, MAX(kwh) AS kwh, MAX(outdoor_temp_c) AS outdoor_temp_c
    FROM raw_readings
    GROUP BY household_id, reading_ts
)
SELECT
    household_id,
    reading_ts,
    DATE(reading_ts)                               AS reading_date,
    CAST(strftime('%Y', reading_ts) AS INTEGER)    AS year,
    CAST(strftime('%m', reading_ts) AS INTEGER)    AS month,
    strftime('%Y-%m', reading_ts)                  AS year_month,
    CAST(strftime('%H', reading_ts) AS INTEGER)    AS hour,
    CAST(strftime('%w', reading_ts) AS INTEGER)    AS dow,            -- 0 = Sunday
    CASE WHEN strftime('%w', reading_ts) IN ('0','6') THEN 'Weekend' ELSE 'Weekday' END AS day_type,
    kwh,
    outdoor_temp_c
FROM dedup
WHERE kwh IS NOT NULL
  AND kwh >= 0
  AND kwh <= 15;          -- residential hourly use above 15 kWh = unit/sensor error

-- NAME: dq_after
-- Confirm the clean table is sound and report how many rows were dropped.
SELECT
    (SELECT COUNT(*) FROM raw_readings)     AS raw_rows,
    (SELECT COUNT(*) FROM readings_clean)   AS clean_rows,
    (SELECT COUNT(*) FROM raw_readings) - (SELECT COUNT(*) FROM readings_clean) AS rows_removed,
    (SELECT COUNT(*) FROM readings_clean WHERE kwh IS NULL OR kwh < 0 OR kwh > 15) AS remaining_bad_rows;

-- NAME: monthly_by_household
-- Total monthly consumption per household.
SELECT
    c.household_id,
    h.home_type,
    c.year_month,
    ROUND(SUM(c.kwh), 1)  AS total_kwh,
    ROUND(AVG(c.kwh), 3)  AS avg_hourly_kwh
FROM readings_clean c
JOIN households h USING (household_id)
GROUP BY c.household_id, h.home_type, c.year_month
ORDER BY c.household_id, c.year_month;

-- NAME: hourly_profile
-- Average load by hour of day (the daily "shape" of usage), split weekday vs weekend.
SELECT
    household_id,
    day_type,
    hour,
    ROUND(AVG(kwh), 3) AS avg_kwh
FROM readings_clean
GROUP BY household_id, day_type, hour
ORDER BY household_id, day_type, hour;

-- NAME: yearly_summary
-- Annual totals and year-over-year % change per household (window function: LAG).
WITH yearly AS (
    SELECT household_id, year, SUM(kwh) AS total_kwh
    FROM readings_clean
    GROUP BY household_id, year
)
SELECT
    household_id,
    year,
    ROUND(total_kwh, 0) AS total_kwh,
    ROUND(100.0 * (total_kwh - LAG(total_kwh) OVER (PARTITION BY household_id ORDER BY year))
          / LAG(total_kwh) OVER (PARTITION BY household_id ORDER BY year), 1) AS yoy_pct_change
FROM yearly
ORDER BY household_id, year;

-- NAME: seasonal_summary
-- Average daily kWh by season (Dec-Feb winter etc.).
WITH daily AS (
    SELECT household_id, reading_date, month, SUM(kwh) AS daily_kwh
    FROM readings_clean
    GROUP BY household_id, reading_date, month
)
SELECT
    household_id,
    CASE
        WHEN month IN (12, 1, 2) THEN '1 Winter'
        WHEN month IN (3, 4, 5)  THEN '2 Spring'
        WHEN month IN (6, 7, 8)  THEN '3 Summer'
        ELSE '4 Fall'
    END AS season,
    ROUND(AVG(daily_kwh), 2) AS avg_daily_kwh
FROM daily
GROUP BY household_id, season
ORDER BY household_id, season;

-- NAME: peak_days
-- The 10 highest-consumption days across all households, with that day's temperature.
SELECT
    household_id,
    reading_date,
    ROUND(SUM(kwh), 1)             AS daily_kwh,
    ROUND(AVG(outdoor_temp_c), 1)  AS avg_temp_c
FROM readings_clean
GROUP BY household_id, reading_date
ORDER BY daily_kwh DESC
LIMIT 10;

-- NAME: ev_before_after
-- Did H001's overnight (23:00-03:00) usage change around July 2024?
SELECT
    CASE WHEN reading_date >= '2024-07-01' THEN 'After Jul-2024' ELSE 'Before Jul-2024' END AS period,
    ROUND(AVG(kwh), 3) AS avg_overnight_kwh
FROM readings_clean
WHERE household_id = 'H001'
  AND (hour >= 23 OR hour <= 3)
  AND reading_date >= '2024-01-01'
GROUP BY period;
