-- =====================================================================
-- Task 2 - Relational schema for the I-94 Metro Interstate traffic data
-- Database : MySQL 8.0+  (also runs on MariaDB 10.6+)
-- Run with : mysql -u root -p < sql/01_create_schema.sql
--
-- Design (3 tables + 1 view, normalised to 3NF):
--   weather_conditions  lookup of the 11 weather types        (dimension)
--   calendar_days       one row per calendar date, holidays    (dimension)
--   traffic_records     one row per hour - the time series     (fact table)
--   v_traffic_records   view that joins them back into the flat JSON
--                       shape the API (Task 3) and forecast (Task 4) use
--
-- Why this split?
--   * weather_main repeats 43,623 times in the CSV but has only 11 values,
--     so it becomes a small lookup table referenced by a foreign key.
--   * Holiday and weekday facts belong to the DATE, not to each hour, so
--     they live once per day in calendar_days (holiday_name is only known
--     per day). This removes 24x repetition and keeps them consistent.
--   * traffic_records keeps the measurements, with a UNIQUE index on
--     date_time because every hour appears once - this index also makes
--     "latest record" and "date range" queries fast.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS traffic_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE traffic_db;

-- Drop in child -> parent order so the script can be re-run safely
DROP VIEW  IF EXISTS v_traffic_records;
DROP TABLE IF EXISTS traffic_records;
DROP TABLE IF EXISTS calendar_days;
DROP TABLE IF EXISTS weather_conditions;

-- ---------------------------------------------------------------------
-- 1. weather_conditions  (lookup / dimension table)
-- ---------------------------------------------------------------------
CREATE TABLE weather_conditions (
    weather_id        TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
    weather_main      VARCHAR(20)      NOT NULL,   -- e.g. 'Clear', 'Rain'
    category          VARCHAR(20)      NOT NULL,   -- clear_sky | cloudy | precipitation | low_visibility
    is_precipitation  TINYINT(1)       NOT NULL DEFAULT 0,
    PRIMARY KEY (weather_id),
    UNIQUE KEY uq_weather_main (weather_main),
    CONSTRAINT chk_weather_category
        CHECK (category IN ('clear_sky', 'cloudy', 'precipitation', 'low_visibility'))
) ENGINE = InnoDB;

-- The 11 weather types found in the dataset (fixed reference data)
INSERT INTO weather_conditions (weather_main, category, is_precipitation) VALUES
    ('Clear',        'clear_sky',      0),
    ('Clouds',       'cloudy',         0),
    ('Drizzle',      'precipitation',  1),
    ('Rain',         'precipitation',  1),
    ('Snow',         'precipitation',  1),
    ('Thunderstorm', 'precipitation',  1),
    ('Squall',       'precipitation',  1),
    ('Fog',          'low_visibility', 0),
    ('Haze',         'low_visibility', 0),
    ('Mist',         'low_visibility', 0),
    ('Smoke',        'low_visibility', 0);

-- ---------------------------------------------------------------------
-- 2. calendar_days  (date dimension)
-- ---------------------------------------------------------------------
CREATE TABLE calendar_days (
    calendar_date  DATE             NOT NULL,
    year           SMALLINT         NOT NULL,
    month          TINYINT UNSIGNED NOT NULL,     -- 1-12
    day_of_week    TINYINT UNSIGNED NOT NULL,     -- 0 = Monday ... 6 = Sunday (same as pandas)
    day_name       VARCHAR(9)       NOT NULL,     -- 'Monday' ...
    is_weekend     TINYINT(1)       NOT NULL DEFAULT 0,
    is_holiday     TINYINT(1)       NOT NULL DEFAULT 0,
    holiday_name   VARCHAR(50)      NULL,         -- e.g. 'Labor Day'; NULL on normal days
    PRIMARY KEY (calendar_date),
    KEY idx_calendar_holiday (is_holiday),
    CONSTRAINT chk_calendar_month CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT chk_calendar_dow   CHECK (day_of_week BETWEEN 0 AND 6)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 3. traffic_records  (fact table - the hourly time series)
-- ---------------------------------------------------------------------
CREATE TABLE traffic_records (
    record_id       INT UNSIGNED     NOT NULL AUTO_INCREMENT,
    date_time       DATETIME         NOT NULL,    -- hourly timestamp, local time
    calendar_date   DATE             NOT NULL,    -- = DATE(date_time), FK to calendar_days
    weather_id      TINYINT UNSIGNED NOT NULL,    -- FK to weather_conditions
    traffic_volume  INT UNSIGNED     NOT NULL,    -- TARGET: vehicles per hour
    temp            DECIMAL(6,2)     NOT NULL,    -- Kelvin
    rain_1h         DECIMAL(7,2)     NOT NULL DEFAULT 0,   -- mm in last hour
    snow_1h         DECIMAL(5,2)     NOT NULL DEFAULT 0,   -- mm in last hour
    clouds_all      DECIMAL(5,2)     NOT NULL DEFAULT 0,   -- cloud cover %
    is_imputed      TINYINT(1)       NOT NULL DEFAULT 0,   -- 1 = interpolated in Task 1
    created_at      TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                     ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (record_id),
    UNIQUE KEY uq_traffic_date_time (date_time),           -- one row per hour; speeds up latest/range
    KEY idx_traffic_calendar (calendar_date),
    KEY idx_traffic_weather  (weather_id),
    CONSTRAINT fk_traffic_calendar FOREIGN KEY (calendar_date)
        REFERENCES calendar_days (calendar_date)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT fk_traffic_weather FOREIGN KEY (weather_id)
        REFERENCES weather_conditions (weather_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT chk_traffic_temp    CHECK (temp BETWEEN 200 AND 340),
    CONSTRAINT chk_traffic_clouds  CHECK (clouds_all BETWEEN 0 AND 100),
    CONSTRAINT chk_traffic_rain    CHECK (rain_1h >= 0),
    CONSTRAINT chk_traffic_snow    CHECK (snow_1h >= 0),
    CONSTRAINT chk_traffic_imputed CHECK (is_imputed IN (0, 1))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 4. v_traffic_records  - flat view in the agreed API/JSON field names
--    (date_time, traffic_volume, temp, rain_1h, snow_1h, clouds_all,
--     weather_main, is_holiday, is_imputed)
-- ---------------------------------------------------------------------
CREATE VIEW v_traffic_records AS
SELECT  t.record_id,
        t.date_time,
        t.traffic_volume,
        t.temp,
        t.rain_1h,
        t.snow_1h,
        t.clouds_all,
        w.weather_main,
        c.is_holiday,
        t.is_imputed
FROM        traffic_records    t
INNER JOIN  weather_conditions w ON w.weather_id    = t.weather_id
INNER JOIN  calendar_days      c ON c.calendar_date = t.calendar_date;
