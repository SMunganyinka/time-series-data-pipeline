"""
Task 2 - Create the MongoDB collections and load the traffic data.

Collections (database `traffic_db`):
    traffic_readings  one document per hour. Weather and calendar facts are EMBEDDED
                      as sub-documents because they are always read together with the
                      traffic value (MongoDB favours "data read together lives together").
    daily_summaries   one document per day, computed from traffic_readings with an
                      aggregation pipeline ($group + $merge). Holds the 24 hourly values
                      in an array (bucket pattern) so daily questions need one small read.

Also creates:
    * a $jsonSchema validator on traffic_readings (rejects bad inserts from the API)
    * indexes: unique date_time, weather + date_time, holiday flag
    * mongo/sample_documents.json  (example documents for the report)

Usage (from the repository root):
    python mongo/setup_and_load.py
"""
import sys
from pathlib import Path

import pandas as pd
from bson import json_util
from bson.json_util import RELAXED_JSON_OPTIONS
from pymongo import ASCENDING, DESCENDING

from db import DAILY, READINGS, WEATHER_CATEGORY, get_client, get_db, record_to_document

ROOT = Path(__file__).resolve().parents[1]
CLEAN_CSV = ROOT / "data" / "processed" / "traffic_for_db.csv"
RAW_CSV = ROOT / "data" / "raw" / "Metro_Interstate_Traffic_Volume.csv"
SAMPLE_FILE = Path(__file__).resolve().parent / "sample_documents.json"

# ---------------------------------------------------------------------------
# Schema validation: MongoDB is schemaless by default; this validator makes the
# database itself reject documents with missing fields or impossible values.
# ---------------------------------------------------------------------------
READINGS_VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["date_time", "traffic_volume", "weather", "calendar", "is_imputed"],
        "properties": {
            "date_time": {"bsonType": "date", "description": "hourly timestamp (local time)"},
            "traffic_volume": {"bsonType": ["int", "long"], "minimum": 0,
                               "description": "TARGET - vehicles per hour"},
            "is_imputed": {"enum": [0, 1]},
            "weather": {
                "bsonType": "object",
                "required": ["weather_main", "temp", "rain_1h", "snow_1h", "clouds_all"],
                "properties": {
                    "weather_main": {"enum": list(WEATHER_CATEGORY)},
                    "category": {"enum": sorted(set(WEATHER_CATEGORY.values()))},
                    "temp": {"bsonType": ["double", "int"], "minimum": 200, "maximum": 340,
                             "description": "Kelvin"},
                    "rain_1h": {"bsonType": ["double", "int"], "minimum": 0},
                    "snow_1h": {"bsonType": ["double", "int"], "minimum": 0},
                    "clouds_all": {"bsonType": ["double", "int"], "minimum": 0, "maximum": 100},
                },
            },
            "calendar": {
                "bsonType": "object",
                "required": ["date", "hour", "day_of_week", "is_weekend", "is_holiday"],
                "properties": {
                    "date": {"bsonType": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
                    "hour": {"bsonType": "int", "minimum": 0, "maximum": 23},
                    "day_of_week": {"bsonType": "int", "minimum": 0, "maximum": 6},
                    "is_weekend": {"enum": [0, 1]},
                    "is_holiday": {"enum": [0, 1]},
                    "holiday_name": {"bsonType": ["string", "null"]},
                },
            },
        },
    }
}


def holiday_names(raw_path):
    """{date-string: holiday name} from the raw file (name sits on the midnight row)."""
    raw = pd.read_csv(raw_path, usecols=["holiday", "date_time"], parse_dates=["date_time"])
    raw = raw[raw["holiday"].notna()]
    return (raw.assign(day=raw["date_time"].dt.strftime("%Y-%m-%d"))
               .groupby("day")["holiday"].first().to_dict())


def build_documents(df, names):
    """Turn each CSV row into one nested traffic_readings document."""
    docs = []
    for rec in df.to_dict("records"):
        day = rec["date_time"].strftime("%Y-%m-%d")
        docs.append(record_to_document(rec, holiday_name=names.get(day)))
    return docs


# Aggregation pipeline that (re)builds daily_summaries from traffic_readings.
DAILY_PIPELINE = [
    {"$sort": {"date_time": 1}},
    {"$group": {
        "_id": "$calendar.date",
        "date": {"$first": {"$dateTrunc": {"date": "$date_time", "unit": "day"}}},
        "day_name": {"$first": "$calendar.day_name"},
        "is_weekend": {"$first": "$calendar.is_weekend"},
        "is_holiday": {"$first": "$calendar.is_holiday"},
        "holiday_name": {"$first": "$calendar.holiday_name"},
        "hours_recorded": {"$sum": 1},
        "total_traffic": {"$sum": "$traffic_volume"},
        "avg_traffic": {"$avg": "$traffic_volume"},
        "max_traffic": {"$max": "$traffic_volume"},
        "avg_temp_k": {"$avg": "$weather.temp"},
        "total_rain_mm": {"$sum": "$weather.rain_1h"},
        "hourly": {"$push": {"hour": "$calendar.hour",
                             "traffic_volume": "$traffic_volume",
                             "weather_main": "$weather.weather_main"}},
    }},
    {"$set": {
        "avg_traffic": {"$round": ["$avg_traffic", 1]},
        "avg_temp_k": {"$round": ["$avg_temp_k", 2]},
        "total_rain_mm": {"$round": ["$total_rain_mm", 2]},
        "is_complete_day": {"$eq": ["$hours_recorded", 24]},
    }},
    {"$merge": {"into": DAILY, "whenMatched": "replace", "whenNotMatched": "insert"}},
]


def main():
    if not CLEAN_CSV.exists():
        sys.exit(f"Cannot find {CLEAN_CSV}. Run this script from the repository root.")

    client = get_client()
    client.admin.command("ping")                       # fail fast if MongoDB is not running
    db = get_db(client)

    df = pd.read_csv(CLEAN_CSV, parse_dates=["date_time"])
    print(f"Read {len(df):,} rows from {CLEAN_CSV.name}")
    docs = build_documents(df, holiday_names(RAW_CSV))

    # start clean so the script can be re-run
    db.drop_collection(READINGS)
    db.drop_collection(DAILY)

    # 1) traffic_readings with validator + indexes
    db.create_collection(READINGS, validator=READINGS_VALIDATOR, validationLevel="strict")
    db[READINGS].create_index([("date_time", ASCENDING)], unique=True, name="uq_date_time")
    db[READINGS].create_index([("weather.weather_main", ASCENDING), ("date_time", ASCENDING)],
                              name="idx_weather_date_time")
    db[READINGS].create_index([("calendar.is_holiday", ASCENDING)], name="idx_is_holiday")
    db[READINGS].insert_many(docs, ordered=False)
    print(f"  inserted {db[READINGS].count_documents({}):,} documents into {READINGS}")

    # 2) daily_summaries built inside MongoDB by an aggregation pipeline
    db[READINGS].aggregate(DAILY_PIPELINE)
    db[DAILY].create_index([("date", DESCENDING)], name="idx_date")
    print(f"  built {db[DAILY].count_documents({}):,} documents in {DAILY}")

    # 3) sample documents for the report
    samples = {
        READINGS: list(db[READINGS].find({}, {"_id": 0}).sort("date_time", DESCENDING).limit(2))
                  + list(db[READINGS].find({"calendar.is_holiday": 1}, {"_id": 0}).limit(1)),
        DAILY: list(db[DAILY].find({"_id": "2018-09-03"})),      # Labor Day 2018
    }
    # Extended JSON keeps the real types visible, e.g. {"$date": "2018-09-30T23:00:00Z"}
    SAMPLE_FILE.write_text(json_util.dumps(samples, indent=2, json_options=RELAXED_JSON_OPTIONS),
                           encoding="utf-8")
    print(f"  wrote sample documents to mongo/{SAMPLE_FILE.name}")
    print("MongoDB load complete.")


if __name__ == "__main__":
    main()
