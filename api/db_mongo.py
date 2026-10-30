"""MongoDB connection.

Uses the helpers from Task 2 (mongo/db.py) so we read the same
collection the same way. One client is shared by the whole app.
"""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from mongo.db import READINGS, get_client, get_db  # noqa: E402  (needs .env loaded first)

_client = get_client()


def get_mongo_collection():
    """Return the traffic_readings collection (one document per hour)."""
    return get_db(_client)[READINGS]
