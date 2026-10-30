"""MySQL endpoints: CRUD + latest + date range.

Uses the Task 2 schema (sql/01_create_schema.sql):
  * reads come from the view v_traffic_records (already in the flat JSON shape)
  * writes go to the tables traffic_records and calendar_days

Every record is found by its date_time (unique, one row per hour).
"""
from datetime import datetime
from typing import List

import pymysql
from fastapi import APIRouter, HTTPException, Query

from api.db_sql import get_sql_connection
from api.schemas import TrafficRecord, TrafficRecordUpdate

router = APIRouter(prefix="/sql/records", tags=["MySQL"])

SELECT_RECORD = "SELECT * FROM v_traffic_records"
WEATHER_ID = "(SELECT weather_id FROM weather_conditions WHERE weather_main = %s)"

# MySQL error codes we turn into clear HTTP errors
DUPLICATE_KEY = 1062


def _get_one(cur, date_time):
    """Return one record as a dict, or None."""
    cur.execute(SELECT_RECORD + " WHERE date_time = %s", (date_time,))
    return cur.fetchone()


def _db_error(e):
    """Turn a MySQL error into an HTTP error."""
    if isinstance(e, pymysql.IntegrityError):
        if e.args[0] == DUPLICATE_KEY:
            return HTTPException(409, "A record for this date_time already exists")
        return HTTPException(400, f"Rejected by the database: {e.args[1]}")
    return HTTPException(500, f"MySQL error: {e}")


# ---------- time-series queries ----------
# These must come before /{date_time}, or FastAPI reads "latest" as a date.

@router.get("/latest", response_model=TrafficRecord)
def get_latest():
    """The most recent hour in the database."""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SELECT_RECORD + " ORDER BY date_time DESC LIMIT 1")
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "The table is empty")
    return row


@router.get("/range", response_model=List[TrafficRecord])
def get_range(
    start: datetime = Query(..., examples=["2018-09-23T00:00:00"]),
    end: datetime = Query(..., examples=["2018-09-30T23:00:00"]),
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
                + " WHERE date_time >= %s AND date_time <= %s"
                + " ORDER BY date_time LIMIT %s",
                (start, end, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return rows


# ---------- CRUD ----------

@router.post("", response_model=TrafficRecord, status_code=201)
def create_record(record: TrafficRecord):
    """Add a new hourly record.

    Two steps in one transaction: make sure the day exists in
    calendar_days, then insert the hour into traffic_records.
    """
    ts = record.date_time
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            if _get_one(cur, ts):
                raise HTTPException(409, f"A record for {ts} already exists")

            # 1) The day. INSERT IGNORE keeps the row if the day already exists.
            cur.execute(
                """INSERT IGNORE INTO calendar_days
                   (calendar_date, year, month, day_of_week, day_name,
                    is_weekend, is_holiday, holiday_name)
                   VALUES (DATE(%s), YEAR(%s), MONTH(%s), WEEKDAY(%s), DAYNAME(%s),
                           WEEKDAY(%s) >= 5, %s, NULL)""",
                (ts, ts, ts, ts, ts, ts, record.is_holiday),
            )
            # 2) The hour
            cur.execute(
                f"""INSERT INTO traffic_records
                    (date_time, calendar_date, weather_id, traffic_volume,
                     temp, rain_1h, snow_1h, clouds_all, is_imputed)
                    VALUES (%s, DATE(%s), {WEATHER_ID}, %s, %s, %s, %s, %s, %s)""",
                (ts, ts, record.weather_main, record.traffic_volume, record.temp,
                 record.rain_1h, record.snow_1h, record.clouds_all, record.is_imputed),
            )
            conn.commit()
            return _get_one(cur, ts)
    except pymysql.MySQLError as e:
        conn.rollback()
        raise _db_error(e)
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

    Note: is_holiday is stored per day (calendar_days), so changing it
    affects every hour of that date.
    """
    data = changes.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Send at least one field to update")

    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            if _get_one(cur, date_time) is None:
                raise HTTPException(404, f"No record for {date_time}")

            # is_holiday lives in calendar_days
            if "is_holiday" in data:
                flag = data.pop("is_holiday")
                cur.execute(
                    """UPDATE calendar_days
                       SET is_holiday = %s,
                           holiday_name = IF(%s = 1, holiday_name, NULL)
                       WHERE calendar_date = DATE(%s)""",
                    (flag, flag, date_time),
                )

            # Everything else is a column in traffic_records.
            # Column names come from our own model, not the user, so this is safe.
            sets, values = [], []
            for col, val in data.items():
                if col == "weather_main":
                    sets.append(f"weather_id = {WEATHER_ID}")
                else:
                    sets.append(f"{col} = %s")
                values.append(val)
            if sets:
                cur.execute(
                    f"UPDATE traffic_records SET {', '.join(sets)} WHERE date_time = %s",
                    (*values, date_time),
                )
            conn.commit()
            return _get_one(cur, date_time)
    except pymysql.MySQLError as e:
        conn.rollback()
        raise _db_error(e)
    finally:
        conn.close()


@router.delete("/{date_time}")
def delete_record(date_time: datetime):
    """Delete one hour. The weather and calendar rows stay."""
    conn = get_sql_connection()
    try:
        with conn.cursor() as cur:
            n = cur.execute("DELETE FROM traffic_records WHERE date_time = %s", (date_time,))
        conn.commit()
    finally:
        conn.close()
    if n == 0:
        raise HTTPException(404, f"No record for {date_time}")
    return {"deleted": date_time.isoformat()}
