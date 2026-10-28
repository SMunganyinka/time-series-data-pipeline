"""Create the tables and load traffic_for_db.csv into MySQL and MongoDB.

Run from the repo root:
    python -m api.setup_db            # load both databases
    python -m api.setup_db --reset    # wipe and reload both

It is safe to run twice. Rows that already exist are skipped.
"""
import argparse
import os

import pandas as pd
from pymongo import ASCENDING

from api.db_mongo import get_mongo_collection
from api.db_sql import get_sql_connection

CSV_PATH = os.path.join("data", "processed", "traffic_for_db.csv")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
BATCH = 5000


def load_csv():
    df = pd.read_csv(CSV_PATH, parse_dates=["date_time"])
    df["cal_date"] = df["date_time"].dt.date
    print(f"Read {len(df):,} rows from {CSV_PATH}")
    return df


# ---------------- MySQL ----------------

def run_schema(cur):
    """Run each CREATE TABLE statement in schema.sql."""
    with open(SCHEMA_PATH) as f:
        # Drop comment lines, then split on ';'
        lines = [l for l in f if not l.strip().startswith("--")]
    for stmt in "".join(lines).split(";"):
        if stmt.strip():
            cur.execute(stmt)


def setup_mysql(df, reset):
    conn = get_sql_connection()
    cur = conn.cursor()

    if reset:
        # Child table first, because of the foreign keys
        for t in ["traffic_records", "calendar_days", "weather_conditions"]:
            cur.execute(f"DROP TABLE IF EXISTS {t}")
    run_schema(cur)

    # 1) Weather lookup table
    weathers = sorted(df["weather_main"].unique())
    cur.executemany(
        "INSERT IGNORE INTO weather_conditions (weather_main) VALUES (%s)",
        [(w,) for w in weathers],
    )
    cur.execute("SELECT weather_id, weather_main FROM weather_conditions")
    weather_ids = {r["weather_main"]: r["weather_id"] for r in cur.fetchall()}

    # 2) Calendar table: one row per day
    days = df.groupby("cal_date")["is_holiday"].max().reset_index()
    cur.executemany(
        "INSERT IGNORE INTO calendar_days (cal_date, is_holiday) VALUES (%s, %s)",
        [(r.cal_date, int(r.is_holiday)) for r in days.itertuples()],
    )

    # 3) Hourly traffic records, in batches
    rows = [
        (
            r.date_time.to_pydatetime(), r.cal_date, weather_ids[r.weather_main],
            int(r.traffic_volume), float(r.temp), float(r.rain_1h),
            float(r.snow_1h), float(r.clouds_all), int(r.is_imputed),
        )
        for r in df.itertuples()
    ]
    sql = """INSERT IGNORE INTO traffic_records
             (date_time, cal_date, weather_id, traffic_volume, temp,
              rain_1h, snow_1h, clouds_all, is_imputed)
             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    for i in range(0, len(rows), BATCH):
        cur.executemany(sql, rows[i:i + BATCH])

    for t in ["weather_conditions", "calendar_days", "traffic_records"]:
        cur.execute(f"SELECT COUNT(*) AS n FROM {t}")
        print(f"MySQL  {t:<20} {cur.fetchone()['n']:>7,} rows")
    conn.close()


# ---------------- MongoDB ----------------

def setup_mongo(df, reset):
    col = get_mongo_collection()
    if reset:
        col.drop()

    # date_time is unique, and the index makes range queries fast
    col.create_index([("date_time", ASCENDING)], unique=True)

    # Same field names as the API contract in HANDOFF.md.
    # date_time is stored as a real date, not text, so range queries work.
    docs = [
        {
            "date_time": r.date_time.to_pydatetime(),
            "traffic_volume": int(r.traffic_volume),
            "temp": float(r.temp),
            "rain_1h": float(r.rain_1h),
            "snow_1h": float(r.snow_1h),
            "clouds_all": float(r.clouds_all),
            "weather_main": r.weather_main,
            "is_holiday": int(r.is_holiday),
            "is_imputed": int(r.is_imputed),
        }
        for r in df.itertuples()
    ]

    # Only insert hours that are not there yet
    existing = {d["date_time"] for d in col.find({}, {"date_time": 1, "_id": 0})}
    new_docs = [d for d in docs if d["date_time"] not in existing]
    for i in range(0, len(new_docs), BATCH):
        col.insert_many(new_docs[i:i + BATCH])

    print(f"Mongo  {col.name:<20} {col.count_documents({}):>7,} docs")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe and reload")
    args = parser.parse_args()

    data = load_csv()
    setup_mysql(data, args.reset)
    setup_mongo(data, args.reset)
    print("Done.")
