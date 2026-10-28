"""MongoDB endpoints: CRUD + latest + date range.

Same URLs and same JSON as the MySQL endpoints, just under /mongo.
Each hour is one document, found by its date_time (unique index).
"""
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, HTTPException, Query
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from api.db_mongo import get_mongo_collection
from api.schemas import TrafficRecord, TrafficRecordUpdate

router = APIRouter(prefix="/mongo/records", tags=["MongoDB"])

# Never send Mongo's internal _id back to the user
NO_ID = {"_id": 0}


# ---------- time-series queries ----------
# These must come before /{date_time}, or FastAPI reads "latest" as a date.

@router.get("/latest", response_model=TrafficRecord)
def get_latest():
    """The most recent hour in the collection."""
    doc = get_mongo_collection().find_one({}, NO_ID, sort=[("date_time", DESCENDING)])
    if doc is None:
        raise HTTPException(404, "The collection is empty")
    return doc


@router.get("/range", response_model=List[TrafficRecord])
def get_range(
    start: datetime = Query(..., examples=["2018-09-01T00:00:00"]),
    end: datetime = Query(..., examples=["2018-09-07T23:00:00"]),
    limit: int = Query(1000, ge=1, le=50000, description="max docs to return"),
):
    """All hours between start and end (both included), oldest first.

    The data has gaps, so an empty list can be a correct answer.
    """
    if start > end:
        raise HTTPException(400, "start must be before end")
    cursor = (
        get_mongo_collection()
        .find({"date_time": {"$gte": start, "$lte": end}}, NO_ID)
        .sort("date_time", ASCENDING)
        .limit(limit)
    )
    return list(cursor)


# ---------- CRUD ----------

@router.post("", response_model=TrafficRecord, status_code=201)
def create_record(record: TrafficRecord):
    """Add a new hourly record."""
    doc = record.model_dump()
    try:
        get_mongo_collection().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, f"A record for {record.date_time} already exists")
    doc.pop("_id", None)  # insert_one adds _id to our dict
    return doc


@router.get("/{date_time}", response_model=TrafficRecord)
def read_record(date_time: datetime):
    """Get one hour, e.g. /mongo/records/2018-09-30T23:00:00"""
    doc = get_mongo_collection().find_one({"date_time": date_time}, NO_ID)
    if doc is None:
        raise HTTPException(404, f"No record for {date_time}")
    return doc


@router.put("/{date_time}", response_model=TrafficRecord)
def update_record(date_time: datetime, changes: TrafficRecordUpdate):
    """Change some fields of one hour. Only send what you want to change.

    is_holiday is a property of the whole day, so (like in MySQL)
    changing it updates every hour of that date.
    """
    data = changes.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "Send at least one field to update")

    col = get_mongo_collection()
    if col.find_one({"date_time": date_time}, {"_id": 1}) is None:
        raise HTTPException(404, f"No record for {date_time}")

    if "is_holiday" in data:
        day_start = datetime.combine(date_time.date(), datetime.min.time())
        col.update_many(
            {"date_time": {"$gte": day_start, "$lt": day_start + timedelta(days=1)}},
            {"$set": {"is_holiday": data.pop("is_holiday")}},
        )
    if data:
        col.update_one({"date_time": date_time}, {"$set": data})

    return col.find_one({"date_time": date_time}, NO_ID)


@router.delete("/{date_time}")
def delete_record(date_time: datetime):
    """Delete one hour."""
    result = get_mongo_collection().delete_one({"date_time": date_time})
    if result.deleted_count == 0:
        raise HTTPException(404, f"No record for {date_time}")
    return {"deleted": date_time.isoformat()}
