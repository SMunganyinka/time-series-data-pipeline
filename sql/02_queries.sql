-- =====================================================================
-- Task 2 - Queries on the MySQL traffic database
-- Run all at once : mysql -u root -p traffic_db < sql/02_queries.sql
-- Run + save results to sql/query_results.md : python sql/run_queries.py
--
-- Each query starts with a "-- @query" line (used by run_queries.py).
-- =====================================================================
USE traffic_db;

-- @query Q1: Latest record in the time series (needed by the API "latest" endpoint)
-- Uses the UNIQUE index on date_time, so MySQL reads one index entry, not the whole table.
SELECT  date_time, traffic_volume, temp, rain_1h, snow_1h, clouds_all,
        weather_main, is_holiday, is_imputed
FROM    v_traffic_records
ORDER BY date_time DESC
LIMIT 1;

-- @query Q2: Records in a date range - morning of 2018-09-28 (API "range" endpoint)
SELECT  date_time, traffic_volume, temp, weather_main, is_holiday
FROM    v_traffic_records
WHERE   date_time >= '2018-09-28 05:00:00'
  AND   date_time <  '2018-09-28 11:00:00'
ORDER BY date_time;

-- @query Q3: Average traffic by hour of day - weekdays vs weekends (daily seasonality)
-- Joins traffic_records with calendar_days to use the weekend flag.
SELECT  HOUR(t.date_time)                                              AS hour_of_day,
        ROUND(AVG(CASE WHEN c.is_weekend = 0 THEN t.traffic_volume END)) AS avg_weekday,
        ROUND(AVG(CASE WHEN c.is_weekend = 1 THEN t.traffic_volume END)) AS avg_weekend
FROM    traffic_records t
JOIN    calendar_days   c ON c.calendar_date = t.calendar_date
GROUP BY HOUR(t.date_time)
ORDER BY hour_of_day;

-- @query Q4: Average traffic and number of hours for each weather condition
-- Joins the fact table with the weather lookup table.
SELECT  w.category,
        w.weather_main,
        COUNT(*)                       AS hours_observed,
        ROUND(AVG(t.traffic_volume))   AS avg_traffic,
        ROUND(AVG(t.temp) - 273.15, 1) AS avg_temp_celsius
FROM    traffic_records    t
JOIN    weather_conditions w ON w.weather_id = t.weather_id
GROUP BY w.category, w.weather_main
ORDER BY avg_traffic DESC;

-- @query Q5: Daily traffic on public holidays vs normal weekdays
-- Totals per day first (subquery), then average per holiday name.
SELECT  COALESCE(d.holiday_name, '(normal weekday)') AS day_type,
        COUNT(*)                                     AS days,
        ROUND(AVG(d.daily_total))                    AS avg_daily_traffic
FROM (
        SELECT  c.calendar_date, c.holiday_name, SUM(t.traffic_volume) AS daily_total
        FROM    traffic_records t
        JOIN    calendar_days   c ON c.calendar_date = t.calendar_date
        WHERE   c.is_weekend = 0
        GROUP BY c.calendar_date, c.holiday_name
        HAVING  COUNT(*) = 24                         -- only complete days
     ) AS d
GROUP BY day_type
ORDER BY avg_daily_traffic DESC;

-- @query Q6: Lag and 24-hour moving average with window functions (time-series features)
-- Same idea as Task 1's lag_1, lag_24 and roll_mean_24, computed inside the database.
-- The window is computed over the whole week, then one day is displayed.
SELECT  date_time, traffic_volume, lag_1h, lag_24h, moving_avg_24h
FROM (
        SELECT  date_time,
                traffic_volume,
                LAG(traffic_volume, 1)  OVER (ORDER BY date_time) AS lag_1h,
                LAG(traffic_volume, 24) OVER (ORDER BY date_time) AS lag_24h,
                ROUND(AVG(traffic_volume) OVER (
                        ORDER BY date_time
                        ROWS BETWEEN 23 PRECEDING AND CURRENT ROW)) AS moving_avg_24h
        FROM    traffic_records
        WHERE   date_time >= '2018-09-23 00:00:00'
          AND   date_time <  '2018-10-01 00:00:00'
     ) AS w
WHERE   date_time >= '2018-09-30 06:00:00'
  AND   date_time <  '2018-09-30 18:00:00'
ORDER BY date_time;

-- @query Q7: Yearly trend - average hourly traffic and share of rainy hours per year
SELECT  c.year,
        COUNT(*)                                           AS hours_recorded,
        ROUND(AVG(t.traffic_volume))                       AS avg_hourly_traffic,
        ROUND(100 * AVG(w.is_precipitation), 1)            AS pct_hours_with_precipitation
FROM    traffic_records    t
JOIN    calendar_days      c ON c.calendar_date = t.calendar_date
JOIN    weather_conditions w ON w.weather_id    = t.weather_id
GROUP BY c.year
ORDER BY c.year;
