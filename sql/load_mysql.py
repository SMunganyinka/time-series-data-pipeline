"""
Task 2 - Load the cleaned traffic data into MySQL.

Reads   data/processed/traffic_for_db.csv   (43,623 clean hourly rows, from Task 1)
and     data/raw/Metro_Interstate_Traffic_Volume.csv  (only to get holiday NAMES)
and fills the three tables created by sql/01_create_schema.sql:

    calendar_days  <- one row per date (weekday, weekend, holiday flag + name)
    traffic_records <- one row per hour, linked to calendar_days and weather_conditions
    (weather_conditions is already filled by the schema script)

Usage (from the repository root):
    mysql -u root -p < sql/01_create_schema.sql      # 1) create the tables
    python sql/load_mysql.py                         # 2) load the data

Connection settings come from environment variables or a .env file in the repo root
(see .env.example): MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB.
"""
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql

try:                                   # .env support is optional
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
CLEAN_CSV = ROOT / "data" / "processed" / "traffic_for_db.csv"
RAW_CSV = ROOT / "data" / "raw" / "Metro_Interstate_Traffic_Volume.csv"
BATCH_SIZE = 5000


def get_connection():
    """Open a MySQL connection using environment variables (with local defaults)."""
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "traffic_db"),
        charset="utf8mb4",
        autocommit=False,
    )


def build_calendar(df, raw_path):
    """One row per calendar date found in the data, with holiday names from the raw file."""
    dates = pd.DataFrame({"calendar_date": pd.to_datetime(df["date_time"].dt.date.unique())})
    dates["year"] = dates["calendar_date"].dt.year
    dates["month"] = dates["calendar_date"].dt.month
    dates["day_of_week"] = dates["calendar_date"].dt.dayofweek          # 0 = Monday
    dates["day_name"] = dates["calendar_date"].dt.day_name()
    dates["is_weekend"] = (dates["day_of_week"] >= 5).astype(int)

    # is_holiday comes from Task 1's clean data (already applied to the whole day)
    holiday_days = set(df.loc[df["is_holiday"] == 1, "date_time"].dt.normalize())
    dates["is_holiday"] = dates["calendar_date"].isin(holiday_days).astype(int)

    # holiday NAME is only in the raw file (on the midnight row of the holiday)
    raw = pd.read_csv(raw_path, usecols=["holiday", "date_time"], parse_dates=["date_time"])
    raw = raw[raw["holiday"].notna()]
    names = raw.assign(day=raw["date_time"].dt.normalize()).groupby("day")["holiday"].first()
    # name only on holiday dates; built as a new column (no in-place edit, works on pandas 2 and 3)
    holiday_name = dates["calendar_date"].map(names)
    dates["holiday_name"] = holiday_name.where(dates["is_holiday"] == 1, None)
    return dates


def insert_in_batches(cur, sql, rows, label):
    for start in range(0, len(rows), BATCH_SIZE):
        cur.executemany(sql, rows[start:start + BATCH_SIZE])
    print(f"  inserted {len(rows):,} rows into {label}")


def main():
    if not CLEAN_CSV.exists():
        sys.exit(f"Cannot find {CLEAN_CSV}. Run this script from the repository root.")

    df = pd.read_csv(CLEAN_CSV, parse_dates=["date_time"])
    print(f"Read {len(df):,} rows from {CLEAN_CSV.name}")
    calendar = build_calendar(df, RAW_CSV)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # make the load re-runnable: empty the data tables (weather lookup stays)
            cur.execute("DELETE FROM traffic_records")
            cur.execute("DELETE FROM calendar_days")

            # 1) calendar_days
            cal_rows = [
                (r.calendar_date.date(), int(r.year), int(r.month), int(r.day_of_week),
                 r.day_name, int(r.is_weekend), int(r.is_holiday),
                 None if pd.isna(r.holiday_name) else r.holiday_name)
                for r in calendar.itertuples(index=False)
            ]
            insert_in_batches(cur, """
                INSERT INTO calendar_days
                    (calendar_date, year, month, day_of_week, day_name,
                     is_weekend, is_holiday, holiday_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", cal_rows, "calendar_days")

            # 2) map weather text -> weather_id from the lookup table
            cur.execute("SELECT weather_main, weather_id FROM weather_conditions")
            weather_ids = dict(cur.fetchall())
            unknown = set(df["weather_main"]) - set(weather_ids)
            if unknown:
                raise ValueError(f"Weather types missing from weather_conditions: {unknown}")

            # 3) traffic_records
            traffic_rows = [
                (r.date_time.to_pydatetime(), r.date_time.date(), weather_ids[r.weather_main],
                 int(r.traffic_volume), round(float(r.temp), 2), round(float(r.rain_1h), 2),
                 round(float(r.snow_1h), 2), round(float(r.clouds_all), 2), int(r.is_imputed))
                for r in df.itertuples(index=False)
            ]
            insert_in_batches(cur, """
                INSERT INTO traffic_records
                    (date_time, calendar_date, weather_id, traffic_volume,
                     temp, rain_1h, snow_1h, clouds_all, is_imputed)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""", traffic_rows, "traffic_records")
        conn.commit()

        # quick sanity check
        with conn.cursor() as cur:
            for table in ("weather_conditions", "calendar_days", "traffic_records"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"  {table:<20} {cur.fetchone()[0]:>7,} rows")
        print("MySQL load complete.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
