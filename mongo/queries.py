"""
Task 2 - Queries on the MongoDB traffic database.

Runs each query, prints it, and saves query + result to mongo/query_results.md
(ready to paste into the report). The filters/pipelines below are written exactly
as you would type them in mongosh, so they can also be run in MongoDB Compass.

Usage (from the repository root, after setup_and_load.py):
    python mongo/queries.py
"""
from datetime import datetime
from pathlib import Path

from bson import json_util

from db import DAILY, FLAT_PROJECTION, READINGS, get_db

RESULT_FILE = Path(__file__).resolve().parent / "query_results.md"


# Each query: (title, collection, kind, spec)
#   kind "find"      -> spec = dict(filter=..., projection=..., sort=..., limit=...)
#   kind "aggregate" -> spec = pipeline list
QUERIES = [
    ("M1: Latest reading in the time series (API 'latest' endpoint)",
     READINGS, "find",
     dict(filter={}, projection=FLAT_PROJECTION, sort=[("date_time", -1)], limit=1)),

    ("M2: Readings in a date range - morning of 2018-09-28 (API 'range' endpoint)",
     READINGS, "find",
     dict(filter={"date_time": {"$gte": datetime(2018, 9, 28, 5), "$lt": datetime(2018, 9, 28, 11)}},
          projection={"_id": 0, "date_time": 1, "traffic_volume": 1,
                      "weather.weather_main": 1, "weather.temp": 1},
          sort=[("date_time", 1)], limit=0)),

    ("M3: Average traffic per weather condition (aggregation on an embedded field)",
     READINGS, "aggregate",
     [{"$group": {"_id": "$weather.weather_main",
                  "category": {"$first": "$weather.category"},
                  "hours": {"$sum": 1},
                  "avg_traffic": {"$avg": "$traffic_volume"}}},
      {"$set": {"avg_traffic": {"$round": ["$avg_traffic", 0]}}},
      {"$sort": {"avg_traffic": -1}}]),

    ("M4: Morning rush hour (07:00-08:59) on weekdays - average traffic per day of the week",
     READINGS, "aggregate",
     [{"$match": {"calendar.is_weekend": 0, "calendar.is_holiday": 0,
                  "calendar.hour": {"$in": [7, 8]}}},
      {"$group": {"_id": {"dow": "$calendar.day_of_week", "day": "$calendar.day_name"},
                  "avg_traffic": {"$avg": "$traffic_volume"},
                  "hours": {"$sum": 1}}},
      {"$sort": {"_id.dow": 1}},
      {"$project": {"_id": 0, "day": "$_id.day", "hours": 1,
                    "avg_traffic": {"$round": ["$avg_traffic", 0]}}}]),

    ("M5: Holidays ranked by total daily traffic (daily_summaries collection)",
     DAILY, "find",
     dict(filter={"is_holiday": 1, "is_complete_day": True, "date": {"$gte": datetime(2017, 1, 1)}},
          projection={"_id": 1, "holiday_name": 1, "day_name": 1,
                      "total_traffic": 1, "max_traffic": 1},
          sort=[("total_traffic", 1)], limit=0)),

    ("M6: Lag and 24-hour moving average with $setWindowFields (time-series features)",
     READINGS, "aggregate",
     [{"$match": {"date_time": {"$gte": datetime(2018, 9, 23), "$lt": datetime(2018, 10, 1)}}},
      {"$setWindowFields": {
          "sortBy": {"date_time": 1},
          "output": {
              "lag_1h": {"$shift": {"output": "$traffic_volume", "by": -1}},
              "lag_24h": {"$shift": {"output": "$traffic_volume", "by": -24}},
              "moving_avg_24h": {"$avg": "$traffic_volume",
                                 "window": {"documents": [-23, 0]}}}}},
      {"$match": {"date_time": {"$gte": datetime(2018, 9, 30, 6), "$lt": datetime(2018, 9, 30, 18)}}},
      {"$project": {"_id": 0, "date_time": 1, "traffic_volume": 1, "lag_1h": 1, "lag_24h": 1,
                    "moving_avg_24h": {"$round": ["$moving_avg_24h", 0]}}}]),

    ("M7: Busiest single hour of every year",
     READINGS, "aggregate",
     [{"$sort": {"traffic_volume": -1}},
      {"$group": {"_id": "$calendar.year",
                  "max_traffic": {"$first": "$traffic_volume"},
                  "at": {"$first": "$date_time"},
                  "weather": {"$first": "$weather.weather_main"}}},
      {"$sort": {"_id": 1}}]),
]


def fmt(v):
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "NULL" if v is None else str(v)


def flatten(doc, prefix=""):
    """{'weather': {'temp': 1}} -> {'weather.temp': 1} so nested results fit a table."""
    out = {}
    for k, v in doc.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def to_markdown(docs):
    if not docs:
        return "_(no documents)_"
    rows = [flatten(d) for d in docs]
    cols = list(dict.fromkeys(c for r in rows for c in r))
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(r.get(c)) for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def to_mongosh(collection, kind, spec):
    """Show the query the way it would be typed in mongosh."""
    dumps = lambda x: json_util.dumps(x, indent=2)
    if kind == "aggregate":
        return f"db.{collection}.aggregate({dumps(spec)})"
    sort = dict(spec.get("sort") or [])
    text = f"db.{collection}.find(\n{dumps(spec['filter'])},\n{dumps(spec['projection'])}\n)"
    if sort:
        text += f".sort({json_util.dumps(sort)})"
    if spec.get("limit"):
        text += f".limit({spec['limit']})"
    return text


def run(db, collection, kind, spec):
    coll = db[collection]
    if kind == "aggregate":
        return list(coll.aggregate(spec))
    cursor = coll.find(spec["filter"], spec["projection"])
    if spec.get("sort"):
        cursor = cursor.sort(spec["sort"])
    return list(cursor.limit(spec.get("limit", 0)))


def main():
    db = get_db()
    out = ["# MongoDB query results (Task 2)", "",
           f"Generated by `mongo/queries.py` on {datetime.now():%Y-%m-%d %H:%M}.", ""]
    for title, collection, kind, spec in QUERIES:
        docs = run(db, collection, kind, spec)
        print(f"{title}  ->  {len(docs)} document(s)")
        out += [f"## {title}", "", "```javascript", to_mongosh(collection, kind, spec), "```", "",
                f"**Result ({len(docs)} documents):**", "", to_markdown(docs), ""]
    RESULT_FILE.write_text("\n".join(out), encoding="utf-8")
    print(f"Saved results to mongo/{RESULT_FILE.name}")


if __name__ == "__main__":
    main()
