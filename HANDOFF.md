# Handoff from Task 1 - everything the team needs to start Tasks 2, 3 and 4

**Status: Task 1 is finished** (EDA, 6 analytical questions, model experiments, trained model saved).
Dataset: Metro Interstate Traffic Volume (hourly I-94 traffic + weather, Oct 2012 - Sep 2018).

## 1. Files you can use right now
| File | What it is | Who needs it |
|---|---|---|
| `data/processed/traffic_for_db.csv` | **Load this into MySQL and MongoDB.** 43,623 hourly rows, no missing values | Task 2, 3 |
| `models/xgb_traffic_model.joblib` | Trained tuned XGBoost model | Task 4 |
| `models/model_metadata.json` | Exact list/order of the 33 model features, parameters, metrics | Task 4 |
| `src/preprocessing.py` | `clean()` and `add_features()` - the preprocessing pipeline | Task 4 |
| `notebooks/01_eda_and_modeling.ipynb` | Full Task 1 analysis (for the report) | everyone |
| `outputs/` | figures, experiment table | report |

## 2. Data dictionary - `traffic_for_db.csv`
| Column | Type | Meaning |
|---|---|---|
| `date_time` | datetime, **unique**, hourly | primary timestamp (e.g. `2017-06-05 08:00:00`) |
| `traffic_volume` | int | **TARGET** - vehicles per hour (0 - 7,280) |
| `temp` | float | temperature in **Kelvin** (subtract 273.15 for degC) |
| `rain_1h` | float | rain in mm in the last hour |
| `snow_1h` | float | snow in mm in the last hour (almost always 0) |
| `clouds_all` | float | cloud cover, % |
| `weather_main` | text | Clear, Clouds, Drizzle, Fog, Haze, Mist, Rain, Smoke, Snow, Squall, Thunderstorm |
| `is_holiday` | 0/1 | 1 for every hour of a public-holiday date |
| `is_imputed` | 0/1 | 1 = value was interpolated over a short gap (<= 6 h), 0 = real reading |

Important facts for the database/API people:
* **The series has gaps** (a 10-month hole Aug 2014 - Jun 2015 plus smaller ones), so "records by date range" can legitimately return nothing for some ranges. The last record is `2018-09-30 23:00:00`.
* `date_time` is unique, so it is a natural key or unique index.
* Dates are local time with no time-zone information.

## 3. Suggested split of work (change as the group prefers)
| Member | Task | Needs from Task 1 |
|---|---|---|
| Task 1 owner | EDA, analytics, model (done) + report sections for Task 1 | - |
| Member B | **Task 2 - SQL**: schema (3+ tables), ERD, SQL scripts, 3+ queries with results | `traffic_for_db.csv` |
| Member C | **Task 2 - MongoDB** (collection design, sample docs, 3+ queries) **and MongoDB CRUD endpoints** | `traffic_for_db.csv` |
| Member D | **Task 3 - SQL CRUD endpoints + Task 4 forecast script** | model + `preprocessing.py` |
Tip: B and C should agree on the field names above so both APIs return the same JSON.

Ideas for a 3+ table SQL design (your choice): `weather_conditions` (lookup of the 11 weather types), `calendar/holidays` (date, is_holiday), `traffic_records` (timestamp, traffic_volume, weather fields, foreign keys). 

## 4. For Task 3 - API contract (so Task 4 works with either database)
Time-series endpoints should return JSON records using the column names above, e.g.
```json
{"date_time": "2018-09-30T23:00:00", "traffic_volume": 2481, "temp": 281.5, "rain_1h": 0.0,
 "snow_1h": 0.0, "clouds_all": 20, "weather_main": "Clear", "is_holiday": 0}
```
Required: `GET /.../latest` and `GET /.../range?start=...&end=...`, plus POST / GET / PUT / DELETE for both databases.

## 5. For Task 4 - how to use the model
The model predicts traffic for hour *t* and needs **the previous 168+ hours** of records (lags up to 168 h and a 168 h rolling mean) plus the weather for hour *t*.
```python
import sys, joblib, json, pandas as pd
sys.path.insert(0, "src")
from preprocessing import clean, add_features, ALL_FEATURES      # same pipeline as training
model = joblib.load("models/xgb_traffic_model.joblib")

# df = last >= 170 hourly records fetched from the API, with the raw column names
# (needs a `date_time` index/column; `holiday` text column is replaced by `is_holiday`)
# 1) build the hourly frame   2) feats = add_features(frame)   3) model.predict(feats[ALL_FEATURES].iloc[[-1]])
```
Notes: the history must be **consecutive hourly rows** (no gaps) or lag features become NaN. Because `traffic_for_db.csv` has already been cleaned, `clean()` is only needed for raw data; for API records, reindex to an hourly grid and call `add_features()`. The Task 1 owner can help wire this up.

## 6. Model results to quote in the report
Tuned XGBoost: **test RMSE 222.3 vehicles/hour, MAE 141.6, R2 0.987** (Jan-Sep 2018, unseen). Seasonal-naive reference RMSE 647.

## 7. Repo rules (rubric rewards this)
* Everyone works on their **own branch** and makes **at least 4 meaningful commits** (clear messages, e.g. `Add MySQL schema for traffic_records`).
* Put code in your own folder: `sql/`, `mongo/`, `api/`, `scripts/`. Do not edit `src/preprocessing.py` without telling the Task 1 owner (Task 4 depends on it).
* Document each part in the README and note who built what (the report needs a contributions section).
