-- MySQL schema for the I-94 traffic data (3 tables).
-- Safe to run more than once.
--
-- weather_conditions  1 ---- * traffic_records
-- calendar_days       1 ---- * traffic_records

CREATE TABLE IF NOT EXISTS weather_conditions (
    weather_id   INT AUTO_INCREMENT PRIMARY KEY,
    weather_main VARCHAR(20) NOT NULL UNIQUE      -- e.g. Clear, Rain, Snow
);

CREATE TABLE IF NOT EXISTS calendar_days (
    cal_date   DATE PRIMARY KEY,                  -- one row per day
    is_holiday TINYINT(1) NOT NULL DEFAULT 0      -- 1 = public holiday
);

CREATE TABLE IF NOT EXISTS traffic_records (
    record_id      INT AUTO_INCREMENT PRIMARY KEY,
    date_time      DATETIME NOT NULL UNIQUE,      -- one row per hour
    cal_date       DATE NOT NULL,
    weather_id     INT NOT NULL,
    traffic_volume INT NOT NULL,                  -- target, vehicles per hour
    temp           FLOAT NOT NULL,                -- Kelvin
    rain_1h        FLOAT NOT NULL DEFAULT 0,      -- mm
    snow_1h        FLOAT NOT NULL DEFAULT 0,      -- mm
    clouds_all     FLOAT NOT NULL DEFAULT 0,      -- %
    is_imputed     TINYINT(1) NOT NULL DEFAULT 0, -- 1 = filled by interpolation
    CONSTRAINT fk_traffic_calendar FOREIGN KEY (cal_date)
        REFERENCES calendar_days (cal_date),
    CONSTRAINT fk_traffic_weather FOREIGN KEY (weather_id)
        REFERENCES weather_conditions (weather_id)
);
