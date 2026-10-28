"""MySQL endpoints: CRUD + latest + date range.

Every record is found by its date_time (it is unique, one row per hour).
All SQL for the API lives in this file.
"""
from datetime import datetime
from typing import List

import pymysql
from fastapi import APIRouter, HTTPException, Query

from api.db_sql import get_sql_connection
from api.schemas import TrafficRecord, TrafficRecordUpdate

router = APIRouter(prefix="/sql/records", tags=["MySQL"])

# One SELECT that joins the 3 tables back into the flat API shape.
SELECT_RECORD = """
    SELECT t.date_time, t.traffic_volume, t.temp, t.rain_1h, t.snow_1h,
           t.clouds_all, w.weather_main, c.is_holiday, t.is_imputed
    FROM traffic_records t
    JOIN weather_conditions w ON t.weather_id = w.weather_id
    JOIN calendar_days c ON t.cal_date = c.cal_date
"""


# ---------- small helpers ----------

def _get_one(cur, date_time):
    """Return one record as a dict, or None."""
    cur.execute(SELECT_RECORD + " WHERE t.date_time = %s", (date_time,))
    return cur.fetchone()


def _weather_id(cur, weather_main):
    """Find the id of a weather type. Add it if it's new."""
    cur.execute(
        "INSERT IGNORE INTO weather_conditions (weather_main) VALUES (%s)",
        (weather_main,),
    )
    cur.execute(
        "SELECT weather_id FROM weather_conditions WHERE weather_main = %s",
        (weather_main,),
    )
    return cur.fetchone()["weather_id"]


# ---------- time-series queries ----------
# These must come before /{date_time}, or FastAPI reads "latest" as a date.

@router.get("/latest", response_model=TrafficRecord)
def get_latest():
    """The most recent hour in the database."""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SELECT_RECORD + " ORDER BY t.date_time DESC LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "The table is empty")
    return row


@router.get("/range", response_model=List[TrafficRecord])
def get_range(
    start: datetime = Query(..., examples=["2018-09-01T00:00:00"]),
    end: datetime = Query(..., examples=["2018-09-07T23:00:00"]),
    limit: int = Query(1000, ge=1, le=50000, description="max rows to return"),
):
    """All hours between start and end (both included), oldest first.

    The data has gaps, so an empty list can be a correct answer.
    """
    if start > end:
        raise HTTPException(400, "start must be before end")
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                SELECT_RECORD
                + " WHERE t.date_time BETWEEN %s AND %s"
                + " ORDER BY t.date_time LIMIT %s",
                (start, end, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return rows


# ---------- CRUD ----------

@router.post("", response_model=TrafficRecord, status_code=201)
def create_record(record: TrafficRecord):
    """Add a new hourly record."""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            if _get_one(cur, record.date_time):
                raise HTTPException(409, f"A record for {record.date_time} already exists")

            weather_id = _weather_id(cur, record.weather_main)

            # Make sure the day exists in the calendar table
            cal_date = record.date_time.date()
            cur.execute(
                "INSERT IGNORE INTO calendar_days (cal_date, is_holiday) VALUES (%s, %s)",
                (cal_date, record.is_holiday),
            )

            cur.execute(
                """INSERT INTO traffic_records
                   (date_time, cal_date, weather_id, traffic_volume, temp,
                    rain_1h, snow_1h, clouds_all, is_imputed)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (record.date_time, cal_date, weather_id, record.traffic_volume,
                 record.temp, record.rain_1h, record.snow_1h,
                 record.clouds_all, record.is_imputed),
            )
            return _get_one(cur, record.date_time)
    except pymysql.MySQLError as e:
        raise HTTPException(500, f"MySQL error: {e}")
    finally:
        conn.close()


@router.get("/{date_time}", response_model=TrafficRecord)
def read_record(date_time: datetime):
    """Get one hour, e.g. /sql/records/2018-09-30T23:00:00"""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            row = _get_one(cur, date_time)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, f"No record for {date_time}")
    return row


@router.put("/{date_time}", response_model=TrafficRecord)
def update_record(date_time: datetime, changes: TrafficRecordUpdate):
    """Change some fields of one hour. Only send what you want to change.

    Note: is_holiday is stored per day, so changing it affects every
    hour of that date.
    """
    data = changes.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Send at least one field to update")

    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            if _get_one(cur, date_time) is None:
                raise HTTPException(404, f"No record for {date_time}")

            # These two live in other tables
            if "weather_main" in data:
                data["weather_id"] = _weather_id(cur, data.pop("weather_main"))
            if "is_holiday" in data:
                cur.execute(
                    "UPDATE calendar_days SET is_holiday = %s WHERE cal_date = %s",
                    (data.pop("is_holiday"), date_time.date()),
                )

            # Everything else is a column in traffic_records.
            # Column names come from our own model, not the user, so this is safe.
            if data:
                sets = ", ".join(f"{col} = %s" for col in data)
                cur.execute(
                    f"UPDATE traffic_records SET {sets} WHERE date_time = %s",
                    (*data.values(), date_time),
                )
            return _get_one(cur, date_time)
    except pymysql.MySQLError as e:
        raise HTTPException(500, f"MySQL error: {e}")
    finally:
        conn.close()


@router.delete("/{date_time}")
def delete_record(date_time: datetime):
    """Delete one hour. The weather and calendar rows stay."""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            n = cur.execute("DELETE FROM traffic_records WHERE date_time = %s", (date_time,))
    finally:
        conn.close()
    if n == 0:
        raise HTTPException(404, f"No record for {date_time}")
    return {"deleted": date_time.isoformat()}
