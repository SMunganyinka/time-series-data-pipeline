"""
Shared MongoDB helpers for Task 2 (and for the Task 3 API).

    from mongo.db import get_db, FLAT_PROJECTION, record_to_document
    db = get_db()
    latest = db.traffic_readings.find_one({}, FLAT_PROJECTION, sort=[("date_time", -1)])
    db.traffic_readings.insert_one(record_to_document(flat_json_from_request))

Connection settings come from environment variables or a .env file in the repo root:
    MONGO_URI  (default mongodb://localhost:27017)    MONGO_DB (default traffic_db)
"""
import os
from datetime import datetime

from pymongo import MongoClient

try:                                   # .env support is optional
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

READINGS = "traffic_readings"          # one document per hour (main time series)
DAILY = "daily_summaries"              # one document per day (pre-aggregated)

# weather_main -> category (same mapping as the weather_conditions table in MySQL)
WEATHER_CATEGORY = {
    "Clear": "clear_sky", "Clouds": "cloudy",
    "Drizzle": "precipitation", "Rain": "precipitation", "Snow": "precipitation",
    "Thunderstorm": "precipitation", "Squall": "precipitation",
    "Fog": "low_visibility", "Haze": "low_visibility",
    "Mist": "low_visibility", "Smoke": "low_visibility",
}

# Projection that turns a nested traffic_readings document into the flat record
# agreed in HANDOFF.md, so SQL and MongoDB endpoints return identical JSON.
FLAT_PROJECTION = {
    "_id": 0,
    "date_time": 1,
    "traffic_volume": 1,
    "temp": "$weather.temp",
    "rain_1h": "$weather.rain_1h",
    "snow_1h": "$weather.snow_1h",
    "clouds_all": "$weather.clouds_all",
    "weather_main": "$weather.weather_main",
    "is_holiday": "$calendar.is_holiday",
    "is_imputed": "$is_imputed",
}


def get_client():
    return MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"),
                       serverSelectionTimeoutMS=5000)


def get_db(client=None):
    client = client or get_client()
    return client[os.getenv("MONGO_DB", "traffic_db")]


def record_to_document(record, holiday_name=None):
    """
    Convert one FLAT record (the API/CSV shape) into a nested traffic_readings document.

    record keys: date_time, traffic_volume, temp, rain_1h, snow_1h, clouds_all,
                 weather_main, is_holiday, is_imputed (optional, default 0)
    date_time may be a datetime or a string like "2018-10-01 00:00:00" / "2018-10-01T00:00:00".
    """
    ts = record["date_time"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    if hasattr(ts, "to_pydatetime"):                  # pandas Timestamp
        ts = ts.to_pydatetime()
    weather_main = record["weather_main"]
    if weather_main not in WEATHER_CATEGORY:
        raise ValueError(f"Unknown weather_main '{weather_main}'. Allowed: {list(WEATHER_CATEGORY)}")
    is_holiday = int(record.get("is_holiday", 0))
    return {
        "date_time": ts,
        "traffic_volume": int(record["traffic_volume"]),
        "weather": {
            "weather_main": weather_main,
            "category": WEATHER_CATEGORY[weather_main],
            "temp": round(float(record["temp"]), 2),
            "rain_1h": round(float(record.get("rain_1h", 0)), 2),
            "snow_1h": round(float(record.get("snow_1h", 0)), 2),
            "clouds_all": round(float(record.get("clouds_all", 0)), 2),
        },
        "calendar": {
            "date": ts.strftime("%Y-%m-%d"),
            "year": ts.year,
            "month": ts.month,
            "hour": ts.hour,
            "day_of_week": ts.weekday(),               # 0 = Monday (same as SQL/pandas)
            "day_name": ts.strftime("%A"),
            "is_weekend": int(ts.weekday() >= 5),
            "is_holiday": is_holiday,
            "holiday_name": holiday_name if is_holiday else None,
        },
        "is_imputed": int(record.get("is_imputed", 0)),
    }
