# Task 3 - CRUD and Time-Series API

A FastAPI app that reads and writes the I-94 traffic data in **both MySQL and MongoDB**.
Both databases have the same endpoints and return the same JSON, so the Task 4 forecast script can use either one.

Built by: Audric (Task 3)

## Files

| File | What it does |
|---|---|
| `main.py` | Starts the app, adds the two routers, `/health` check |
| `db_sql.py` | MySQL connection (PyMySQL) |
| `db_mongo.py` | MongoDB connection, using the Task 2 helpers in `mongo/db.py` |
| `schemas.py` | JSON shape of a record (Pydantic), shared by both databases |
| `routes_sql.py` | MySQL endpoints. All the API's SQL is in this file |
| `routes_mongo.py` | MongoDB endpoints |

The databases themselves are built by Task 2 (`sql/` and `mongo/`, see `docs/TASK2_DATABASES.md`).

## Setup

You need Python 3.10+, MySQL 8+ and MongoDB 5+, both running.

From the repo root (Git Bash on Windows):

```bash
python -m venv .venv
source .venv/Scripts/activate        # on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt -r api/requirements.txt
cp .env.example .env                 # then put your MySQL password in .env
```

Build and load both databases (Task 2 scripts):

```bash
mysql -u root -p < sql/01_create_schema.sql
python sql/load_mysql.py
python mongo/setup_and_load.py
```

On Windows, if `mysql` is not found, run the first line from MySQL Workbench instead
(File > Open SQL Script > `sql/01_create_schema.sql` > run).

## Run

```bash
uvicorn api.main:app --reload
```

- Interactive docs (try every endpoint here): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health should return `{"mysql":"ok","mongodb":"ok"}`

## Endpoints

Same endpoints for both databases. Replace `{db}` with `sql` or `mongo`.

| Method | URL | What it does |
|---|---|---|
| POST | `/{db}/records` | Add a new hourly record |
| GET | `/{db}/records/{date_time}` | Get one hour |
| PUT | `/{db}/records/{date_time}` | Change some fields of one hour |
| DELETE | `/{db}/records/{date_time}` | Delete one hour |
| GET | `/{db}/records/latest` | Most recent record |
| GET | `/{db}/records/range?start=...&end=...&limit=...` | All hours between two dates, oldest first |

`date_time` is written like `2018-09-30T23:00:00`.

### Record shape

```json
{
  "date_time": "2018-09-30T23:00:00",
  "traffic_volume": 954,
  "temp": 282.12,
  "rain_1h": 0.0,
  "snow_1h": 0.0,
  "clouds_all": 90.0,
  "weather_main": "Clouds",
  "is_holiday": 0,
  "is_imputed": 0
}
```

### Examples (curl)

```bash
# Latest record
curl http://127.0.0.1:8000/sql/records/latest

# One day of data
curl "http://127.0.0.1:8000/mongo/records/range?start=2018-09-30T00:00:00&end=2018-09-30T23:00:00"

# Create
curl -X POST http://127.0.0.1:8000/sql/records -H "Content-Type: application/json" \
  -d '{"date_time":"2018-10-01T00:00:00","traffic_volume":812,"temp":281.3,"weather_main":"Clouds"}'

# Update one field
curl -X PUT http://127.0.0.1:8000/sql/records/2018-10-01T00:00:00 -H "Content-Type: application/json" \
  -d '{"traffic_volume":900}'

# Delete
curl -X DELETE http://127.0.0.1:8000/sql/records/2018-10-01T00:00:00
```

## Design notes

- **`date_time` is the key.** There is exactly one record per hour, so every record is found by its timestamp. The databases' own ids (MySQL `record_id`, Mongo `_id`) are never shown, which keeps the JSON the same for both.
- **MySQL: read from the view, write to the tables.** Reads use the Task 2 view `v_traffic_records`, which joins `traffic_records`, `weather_conditions` and `calendar_days` into the flat shape. POST adds the day to `calendar_days` if it is new, then the hour to `traffic_records`, in one transaction (all or nothing).
- **MongoDB: flat in, nested inside.** The `traffic_readings` documents embed `weather` and `calendar` sub-documents. The API uses Task 2's `FLAT_PROJECTION` to return the flat shape and `record_to_document()` to store it. PUT rebuilds the whole document so `weather.category` stays correct.
- **Same rules as the databases.** The request model uses the same limits as the MySQL CHECK constraints and the MongoDB validator (temp 200-340 K, clouds 0-100 %, one of the 11 weather types), so bad data is rejected with a clear message before it reaches either database.
- **`is_holiday` belongs to the whole day.** Changing it with PUT updates every hour of that date, in both databases.
- **Gaps are normal.** The data has gaps (for example Aug 2014 to Jun 2015), so a date range can return an empty list. That is a correct answer, not an error.
- **Clear errors.** 404 when a record doesn't exist, 409 when you POST an hour that already exists, 400 for a bad date range or an empty PUT, 422 when the JSON is invalid (e.g. negative traffic or an unknown weather type).

## Tested

All endpoints were tested against MySQL 8.0 and MongoDB 8.0 loaded with the Task 2 scripts:
every CRUD call, latest, range, the error cases above, and the holiday update.
`GET /sql/records/range` and `GET /mongo/records/range` for 2018-09-23 to 2018-09-30 return identical JSON (192 rows).

## For Task 4

To get enough history for the model (it needs 168+ consecutive hours).
The last 8 days, 2018-09-23 to 2018-09-30, have no gaps (192 hours):

```python
import requests, pandas as pd

r = requests.get("http://127.0.0.1:8000/sql/records/range",
                 params={"start": "2018-09-23T00:00:00", "end": "2018-09-30T23:00:00"})
df = pd.DataFrame(r.json())
df["date_time"] = pd.to_datetime(df["date_time"])
```

Swap `sql` for `mongo` to use the other database. The output is the same.
