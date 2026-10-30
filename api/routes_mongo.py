"""MongoDB endpoints: CRUD + latest + date range.

Same URLs and same JSON as the MySQL endpoints, just under /mongo.

Uses the Task 2 design (mongo/db.py): each hour is one document in
traffic_readings, with weather and calendar embedded as sub-documents.
  * FLAT_PROJECTION turns a nested document into the flat API shape
  * record_to_document() turns flat API JSON into a nested document
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, WriteError

from api.db_mongo import get_mongo_collection
from api.schemas import TrafficRecord, TrafficRecordUpdate
from mongo.db import FLAT_PROJECTION, record_to_document

router = APIRouter(prefix="/mongo/records", tags=["MongoDB"])


def _get_one(col, date_time):
    """Return one record in the flat shape, or None."""
    return col.find_one({"date_time": date_time}, FLAT_PROJECTION)


# ---------- time-series queries ----------
# These must come before /{date_time}, or FastAPI reads "latest" as a date.

@router.get("/latest", response_model=TrafficRecord)
def get_latest():
    """The most recent hour in the collection."""
    doc = get_mongo_collection().find_one(
        {}, FLAT_PROJECTION, sort=[("date_time", DESCENDING)]
    )
    if doc is None:
        raise HTTPException(404, "The collection is empty")
    return doc


@router.get("/range", response_model=List[TrafficRecord])
def get_range(
    start: datetime = Query(..., examples=["2018-09-23T00:00:00"]),
    end: datetime = Query(..., examples=["2018-09-30T23:00:00"]),
    limit: int = Query(1000, ge=1, le=50000, description="max docs to return"),
):
    """All hours between start and end (both included), oldest first.

    The data has gaps, so an empty list can be a correct answer.
    """
    if start > end:
        raise HTTPException(400, "start must be before end")
    cursor = (
        get_mongo_collection()
        .find({"date_time": {"$gte": start, "$lte": end}}, FLAT_PROJECTION)
        .sort("date_time", ASCENDING)
        .limit(limit)
    )
    return list(cursor)


# ---------- CRUD ----------

@router.post("", response_model=TrafficRecord, status_code=201)
def create_record(record: TrafficRecord):
    """Add a new hourly record."""
    col = get_mongo_collection()
    try:
        col.insert_one(record_to_document(record.model_dump()))
    except DuplicateKeyError:
        raise HTTPException(409, f"A record for {record.date_time} already exists")
    except WriteError as e:
        raise HTTPException(400, f"Rejected by the database validator: {e}")
    return _get_one(col, record.date_time)


@router.get("/{date_time}", response_model=TrafficRecord)
def read_record(date_time: datetime):
    """Get one hour, e.g. /mongo/records/2018-09-30T23:00:00"""
    doc = _get_one(get_mongo_collection(), date_time)
    if doc is None:
        raise HTTPException(404, f"No record for {date_time}")
    return doc


@router.put("/{date_time}", response_model=TrafficRecord)
def update_record(date_time: datetime, changes: TrafficRecordUpdate):
    """Change some fields of one hour. Only send what you want to change.

    is_holiday belongs to the whole day, so (like in MySQL) changing it
    updates every hour of that date.
    """
    data = changes.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Send at least one field to update")

    col = get_mongo_collection()
    current = _get_one(col, date_time)
    if current is None:
        raise HTTPException(404, f"No record for {date_time}")

    # Keep the holiday name we already have (the flat shape doesn't carry it)
    old = col.find_one({"date_time": date_time}, {"calendar.holiday_name": 1})
    holiday_name = old["calendar"].get("holiday_name")

    # Rebuild the whole document so nested fields (e.g. weather.category) stay right
    new_doc = record_to_document({**current, **data}, holiday_name=holiday_name)
    try:
        col.replace_one({"date_time": date_time}, new_doc)
        if "is_holiday" in data:
            flag = data["is_holiday"]
            col.update_many(
                {"calendar.date": new_doc["calendar"]["date"]},
                {"$set": {
                    "calendar.is_holiday": flag,
                    "calendar.holiday_name": holiday_name if flag else None,
                }},
            )
    except WriteError as e:
        raise HTTPException(400, f"Rejected by the database validator: {e}")

    return _get_one(col, date_time)


@router.delete("/{date_time}")
def delete_record(date_time: datetime):
    """Delete one hour."""
    result = get_mongo_collection().delete_one({"date_time": date_time})
    if result.deleted_count == 0:
        raise HTTPException(404, f"No record for {date_time}")
    return {"deleted": date_time.isoformat()}
