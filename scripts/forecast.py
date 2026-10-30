"""Fetch API records and forecast traffic for one hourly record.

Run from the repository root while the API is running, for example:

    python scripts/forecast.py --database sql
    python scripts/forecast.py --database mongo --timestamp 2018-09-30T23:00:00

The API record selected by ``--timestamp`` supplies the weather and calendar
features. Its traffic volume is not used as an input feature; only earlier
traffic volumes are used to build lags and rolling statistics.
"""
import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from preprocessing import ALL_FEATURES, add_features  # noqa: E402

REQUIRED_COLUMNS = {
    "date_time",
    "traffic_volume",
    "temp",
    "rain_1h",
    "snow_1h",
    "clouds_all",
    "weather_main",
    "is_holiday",
}
HISTORY_HOURS = 168
FETCH_BUFFER_HOURS = 8


def fetch_records(api_url, start, end, limit=50000):
    """Fetch an inclusive range from one of the API database backends."""
    query = urlencode(
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": limit,
        }
    )
    request = Request(f"{api_url.rstrip('/')}/range?{query}", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API request failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the API at {api_url}: {exc.reason}") from exc

    if not isinstance(payload, list):
        raise RuntimeError("API returned an unexpected response; expected a JSON list of records")
    return payload


def _records_frame(records):
    """Convert API records to the frame expected by shared feature engineering."""
    if not records:
        raise ValueError("The API returned no records for the requested range")
    missing = REQUIRED_COLUMNS - set(records[0])
    if missing:
        raise ValueError(f"API records are missing required fields: {sorted(missing)}")

    frame = pd.DataFrame(records)
    frame["date_time"] = pd.to_datetime(frame["date_time"])
    frame = frame.sort_values("date_time").drop_duplicates("date_time").set_index("date_time")
    return frame


def build_prediction_frame(records, target_time):
    """Build model features and validate that the required history is present."""
    frame = _records_frame(records)
    target_time = pd.Timestamp(target_time)
    expected_start = target_time - pd.Timedelta(hours=HISTORY_HOURS)
    expected_index = pd.date_range(expected_start, target_time, freq="h")
    history = frame.reindex(expected_index)

    if history.isna().any().any():
        missing_times = history.index[history.isna().any(axis=1)]
        preview = ", ".join(str(value) for value in missing_times[:3])
        raise ValueError(
            "The API data does not contain 168 consecutive hours before the target "
            f"(missing values around: {preview})"
        )

    features = add_features(history)
    target_features = features.loc[[target_time], ALL_FEATURES]
    if target_features.isna().any().any():
        missing = target_features.columns[target_features.isna().any()].tolist()
        raise ValueError(f"Could not build complete model features: {missing}")
    return target_features


def forecast(api_url, model_path, metadata_path, target_time=None):
    """Fetch history, load the trained model, and return a forecast result."""
    if target_time is None:
        latest_request = Request(f"{api_url.rstrip('/')}/latest", headers={"Accept": "application/json"})
        try:
            with urlopen(latest_request, timeout=30) as response:
                latest = json.load(response)
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Could not fetch the latest API record: {exc}") from exc
        if "date_time" not in latest:
            raise RuntimeError("The API latest response does not contain date_time")
        target = pd.Timestamp(latest["date_time"])
    else:
        target = pd.Timestamp(target_time)

    start = target - timedelta(hours=HISTORY_HOURS + FETCH_BUFFER_HOURS)
    records = fetch_records(api_url, start, target)
    target_records = [record for record in records if pd.Timestamp(record["date_time"]) == target]
    if not target_records:
        raise RuntimeError(f"The API returned no record for target timestamp {target.isoformat()}")

    features = build_prediction_frame(records, target)
    model = joblib.load(model_path)
    with open(metadata_path, encoding="utf-8") as file:
        metadata = json.load(file)
    expected_features = metadata.get("features")
    if expected_features != ALL_FEATURES:
        raise RuntimeError("Model metadata feature order does not match src/preprocessing.py")

    prediction = float(np.asarray(model.predict(features)).reshape(-1)[0])
    target_record = target_records[0]
    return {
        "date_time": target.isoformat(),
        "predicted_traffic_volume": round(prediction, 2),
        "actual_traffic_volume": target_record["traffic_volume"],
        "model": metadata.get("model", model.__class__.__name__),
        "features_used": len(ALL_FEATURES),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", choices=("sql", "mongo"), default="sql")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Base URL of the running API")
    parser.add_argument("--timestamp", help="Target hour in ISO format; defaults to the API's latest record")
    parser.add_argument(
        "--model",
        type=Path,
        default=REPO_ROOT / "models" / "xgb_traffic_model.joblib",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=REPO_ROOT / "models" / "model_metadata.json",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    api_url = f"{args.api.rstrip('/')}/{args.database}/records"
    result = forecast(api_url, args.model, args.metadata, args.timestamp)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
