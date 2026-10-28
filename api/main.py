"""Traffic Time-Series API (Task 3).

Run from the repo root:
    uvicorn api.main:app --reload
Then open http://127.0.0.1:8000/docs
"""
from fastapi import FastAPI

from api.db_mongo import get_mongo_collection
from api.db_sql import get_sql_connection

app = FastAPI(
    title="I-94 Traffic Time-Series API",
    description="CRUD and time-series endpoints for MySQL and MongoDB.",
    version="0.1.0",
)


@app.get("/health", tags=["health"])
def health():
    """Check that both databases are reachable."""
    status = {"mysql": "ok", "mongodb": "ok"}

    try:
        conn = get_sql_connection()
        conn.ping()
        conn.close()
    except Exception as e:
        status["mysql"] = f"down: {e}"

    try:
        get_mongo_collection().database.client.admin.command("ping")
    except Exception as e:
        status["mongodb"] = f"down: {e}"

    return status
