"""MySQL connection.

Settings come from the .env file in the repo root (same file Task 2 uses).
We open a new connection for each request and close it after.
"""
import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def get_sql_connection():
    """Return a MySQL connection. Rows come back as dicts, not tuples."""
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "traffic_db"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,  # we commit ourselves, so a POST is all-or-nothing
    )
