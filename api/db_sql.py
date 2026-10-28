"""MySQL connection.

We open a new connection for each request and close it after.
This is simple and safe for a small project like ours.
"""
import os

import pymysql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def get_sql_connection():
    """Return a MySQL connection. Rows come back as dicts, not tuples."""
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "traffic_db"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
