"""MongoDB connection.

One client is shared by the whole app. PyMongo handles the pool for us.
"""
import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Short timeout so a missing server fails fast instead of hanging.
_client = MongoClient(
    os.getenv("MONGO_URI", "mongodb://localhost:27017"),
    serverSelectionTimeoutMS=3000,
)


def get_mongo_collection():
    """Return the traffic_records collection."""
    db = _client[os.getenv("MONGO_DB", "traffic_db")]
    return db[os.getenv("MONGO_COLLECTION", "traffic_records")]
